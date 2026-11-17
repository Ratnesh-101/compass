"""T-014 / N-025 / fallback title bug: task titles, domains, and the single-add approval preview.

NOT RUN when written (the author had no shell). The orchestrator tests use a fake pool and patch the
database helpers, so no Postgres is needed.
"""

import json
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.router_helpers import _extract_task_creation_args
from backend.services.task_context import enrich_title, find_context, infer_domain
from backend.services.task_intake_llm import extract_prose_tasks
from backend.services.task_title_clean import clean_title, extract_priority, tidy_title

MONDAY = date(2026, 11, 16)


# ---- fallback title parser ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("Submit audit report by , high priority, hackathon domain", "Submit audit report"),
    ("Submit audit report by friday, high priority, hackathon domain", "Submit audit report by friday"),
    ("Write report by", "Write report"),
    ("Call mom by ,", "Call mom"),
    ("Fix login bug, priority: urgent", "Fix login bug"),
    ("Draft slides with low priority", "Draft slides"),
    ("Review notes for exam", "Review notes for exam"),  # a connector inside a title is kept
    ("Finish lab, domain=coursework", "Finish lab"),
])
def test_clean_title_removes_priority_domain_and_dangling_connectors(raw, expected):
    assert clean_title(raw) == expected


def test_tidy_title_never_leaves_by_comma():
    for raw in ("Pay rent by , ", "Pay rent on ,, ", "Pay rent due ;"):
        out = tidy_title(raw)
        assert out == "Pay rent" and "by ," not in out


@pytest.mark.parametrize("text,expected", [
    ("submit it, high priority", "high"),
    ("priority: urgent", "urgent"),
    ("critical priority", "urgent"),
    ("normal priority", "medium"),
    ("a high-stakes task", None),
    ("no level here", None),
])
def test_extract_priority(text, expected):
    assert extract_priority(text) == expected


def test_fallback_parser_reproduces_and_fixes_the_reported_title():
    args = _extract_task_creation_args("add task Submit audit report by friday, high priority, hackathon domain")
    assert args["title"] == "Submit audit report"
    assert args["domain"] == "hackathon"
    assert args["priority"] == "high"
    assert "by ," not in args["title"] and "priority" not in args["title"].lower()


def test_fallback_parser_remind_me_form_strips_trailing_fragments():
    args = _extract_task_creation_args("remind me to submit audit report, high priority by friday")
    assert args["title"] == "Submit audit report"
    assert args["priority"] == "high"


def test_fallback_parser_next_wednesday_title_has_no_date_words():
    args = _extract_task_creation_args("remind me to finish my database presentation slides by next wednesday")
    assert args["title"] == "Finish my database presentation slides"


def test_presentation_is_not_a_code_domain_just_because_it_contains_pr():
    args = _extract_task_creation_args("add task prepare presentation slides tomorrow")
    assert args["domain"] != "code"


def test_standalone_pr_still_means_code_domain():
    assert _extract_task_creation_args("add task review the PR tomorrow")["domain"] == "code"


# ---- context kept in names and domain -----------------------------------------------------------------
EXAM_MSG = "add tasks: arrays tomorrow, linked lists on thursday and trees on friday for my data structures exam"


def test_find_context():
    assert find_context(EXAM_MSG) == ("Data Structures", "exam")
    assert find_context("add tasks for my exam") is None  # no subject named
    assert find_context("buy milk, call mom") is None


@pytest.mark.parametrize("title,expected", [
    ("arrays", "Study arrays - Data Structures exam"),
    ("Linked lists", "Study linked lists - Data Structures exam"),
    ("trees", "Study trees - Data Structures exam"),
    ("Review sorting", "Review sorting - Data Structures exam"),
    ("Study arrays - Data Structures exam", "Study arrays - Data Structures exam"),
    ("Data Structures cheat sheet", "Data Structures cheat sheet"),
])
def test_enrich_title(title, expected):
    assert enrich_title(title, EXAM_MSG) == expected


def test_enrich_title_is_a_no_op_without_context():
    assert enrich_title("arrays", "add tasks: arrays tomorrow, trees friday") == "arrays"


def test_infer_domain_only_upgrades_general():
    assert infer_domain("general", EXAM_MSG) == "coursework"
    assert infer_domain("hackathon", EXAM_MSG) == "hackathon"
    assert infer_domain("general", "add tasks: buy milk, call mom") == "general"


def _tool_response(arguments: str):
    call = SimpleNamespace(function=SimpleNamespace(name="extract_tasks", arguments=arguments))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


@pytest.mark.asyncio
async def test_prose_extraction_keeps_exam_context_and_coursework_domain():
    out = json.dumps({"tasks": [
        {"title": "arrays", "due_text": "tomorrow"},
        {"title": "linked lists", "due_text": "thursday"},
        {"title": "trees", "due_text": "friday"},
    ]})
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_tool_response(out))
    items = await extract_prose_tasks(client, "m", EXAM_MSG)
    assert [i.title for i in items] == [
        "Study arrays - Data Structures exam",
        "Study linked lists - Data Structures exam",
        "Study trees - Data Structures exam",
    ]
    assert {i.domain for i in items} == {"coursework"}
    system = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "Study arrays - Data Structures exam" in system  # the prompt itself asks for context in names


# ---- single add_task now previews first (T-014 / N-025) -----------------------------------------------
class _Conn:
    pass


class _Pool:
    @asynccontextmanager
    async def _acq(self):
        yield _Conn()

    def acquire(self):
        return self._acq()


def _preview_reply(items):
    return {
        "conversation_id": "c1", "response": "I found 1 task. Nothing has been added yet:", "message": "",
        "skill_used": "add_tasks_preview", "success": True,
        "data": {"pending_action": {"items": items}}, "verifiable": False, "routing_latency_ms": 1,
    }


async def _send_single(message, args, preview_mock, create_mock):
    from backend.orchestrator import handle_message

    with patch("backend.orchestrator.structured.list_tasks", AsyncMock(return_value=[])), \
         patch("backend.orchestrator.structured.create_task", create_mock), \
         patch("backend.services.task_intake.handle_intake_preview", preview_mock), \
         patch("backend.router_helpers._current_today", return_value=MONDAY):
        return await handle_message(
            message=message, user_id="owner-a", persist=False, history=[], memory_context="",
            pool=_Pool(), tz="Asia/Kolkata", pre_routed_skill="add_task", pre_routed_args=args,
        )


@pytest.mark.asyncio
async def test_single_add_returns_the_preview_and_writes_nothing():
    preview = AsyncMock(return_value=_preview_reply([]))
    create = AsyncMock()
    res = await _send_single(
        "add task buy milk tomorrow", {"title": "Buy milk", "due_date": "2026-11-17"}, preview, create)
    assert res["skill_used"] == "add_tasks_preview"
    create.assert_not_called()
    kwargs = preview.call_args.kwargs
    assert kwargs["owner_identity"] == "owner-a" and len(kwargs["items"]) == 1
    assert kwargs["items"][0]["title"] == "Buy milk"


@pytest.mark.asyncio
async def test_n004_models_thursday_is_corrected_to_wednesday_before_the_preview():
    preview = AsyncMock(return_value=_preview_reply([]))
    create = AsyncMock()
    msg = "remind me to finish my database presentation slides by next wednesday"
    await _send_single(
        msg, {"title": "Finish my database presentation slides", "due_date": "2026-11-19"}, preview, create)
    item = preview.call_args.kwargs["items"][0]
    assert item["due_text"] == "2026-11-18"  # Wed 18 Nov, not Thu 19 Nov
    create.assert_not_called()


@pytest.mark.asyncio
async def test_single_add_title_is_cleaned_before_the_preview():
    preview = AsyncMock(return_value=_preview_reply([]))
    await _send_single(
        "add task Submit audit report by friday, high priority, hackathon domain",
        {"title": "Submit audit report by , high priority, hackathon domain", "domain": "hackathon",
         "priority": "high", "due_date": "2026-11-20"},
        preview, AsyncMock())
    assert preview.call_args.kwargs["items"][0]["title"] == "Submit audit report"


def test_preview_text_for_one_task_says_confirm_to_add_it():
    from backend.services.task_intake import _preview_text
    from backend.services.task_intake_parse import IntakeItem, ParsedIntake

    items = [{"title": "Buy milk", "domain": "general", "priority": "medium", "duration_minutes": None,
              "due_label": "Wed Nov 18", "due_unparsed": None}]
    parsed = ParsedIntake((IntakeItem("Buy milk", "general", "medium", None, "wednesday"),), 1, ())
    text = _preview_text(items, parsed, "Asia/Kolkata")
    assert "Nothing has been added yet" in text and "Wed Nov 18" in text
    assert 'Reply "Confirm" to add it' in text and "add all" not in text


def test_phrasal_verb_titles_keep_their_last_word():
    """'Sign in', 'Log in' and 'Check in' are complete titles; only dangling connectors are stripped."""
    from backend.services.task_title_clean import clean_title

    assert clean_title("Sign in") == "Sign in"
    assert clean_title("Log in") == "Log in"
    assert clean_title("Check in") == "Check in"
    assert clean_title("Remind me to call mom for") == "Remind me to call mom"
