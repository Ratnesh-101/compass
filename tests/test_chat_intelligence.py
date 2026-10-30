"""Smarter intake: dateparser fallback, validated prose extraction, example-based intent gate."""

import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.memory.db import get_pool
from backend.orchestrator import handle_message
from backend.router import route_message
from backend.services import intent_gate
from backend.services.task_intake_llm import (
    EXTRACTION_MAX_TOKENS,
    extract_prose_tasks,
    llm_available,
    looks_like_prose_task_list,
)
from backend.services.task_time import resolve_due

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)
OWNER = "test_intel_owner"
CONV = "test-intel-conv-0001"
PROSE = "add tasks: finish the lab report by Friday, call mom tomorrow and buy milk"


# ---- dateparser fallback ---------------------------------------------------------------------------
@pytest.mark.parametrize("text, label", [
    ("in two weeks", "Fri Nov 13"),
    ("3 weeks from now", "Fri Nov 20"),
    ("31 December", "Thu Dec 31"),
    ("Nov 3rd at 5pm", "Tue Nov 3, 5:00 PM (Asia/Calcutta)"),
])
def test_fallback_parser_understands_more_phrasings(text, label):
    assert resolve_due(text, "Asia/Calcutta", NOW).label == label


@pytest.mark.parametrize("text", ["10/11", "9pm", "whenever", "the 3rd", "42", "yesterday-ish maybe"])
def test_fallback_parser_never_guesses(text):
    due = resolve_due(text, "Asia/Calcutta", NOW)
    assert due.due_date is None and due.unparsed_text == text


def test_own_parser_still_wins_when_it_understands_the_text():
    assert resolve_due("Tomorrow, 5pm", "Asia/Calcutta", NOW).label == "Sat Oct 31, 5:00 PM (Asia/Calcutta)"


# ---- validated prose extraction --------------------------------------------------------------------
def _tool_response(arguments: str):
    call = SimpleNamespace(function=SimpleNamespace(name="extract_tasks", arguments=arguments))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


def _client(*responses):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=list(responses))
    return client


GOOD = json.dumps({"tasks": [
    {"title": "Finish the lab report", "domain": "coursework", "priority": "high", "due_text": "Friday"},
    {"title": "Call mom", "due_text": "tomorrow"},
    {"title": "Buy milk"},
]})


@pytest.mark.asyncio
async def test_prose_extraction_returns_validated_items_with_a_forced_bounded_call():
    client = _client(_tool_response(GOOD))
    items = await extract_prose_tasks(client, "router-model", PROSE)
    assert [(i.title, i.domain, i.priority, i.due_text) for i in items] == [
        ("Finish the lab report", "coursework", "high", "Friday"),
        ("Call mom", "general", "medium", "tomorrow"),
        ("Buy milk", "general", "medium", ""),
    ]
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == EXTRACTION_MAX_TOKENS == 1500 and kwargs["temperature"] == 0
    assert kwargs["tool_choice"]["function"]["name"] == "extract_tasks"
    assert client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_invalid_output_is_retried_once_with_the_error_then_given_up():
    client = _client(_tool_response("not json"), _tool_response(GOOD))
    assert len(await extract_prose_tasks(client, "m", PROSE)) == 3
    retry_messages = client.chat.completions.create.call_args.kwargs["messages"]
    assert "invalid" in retry_messages[-1]["content"]

    failing = _client(_tool_response("{}"), _tool_response('{"tasks": "x"}'))
    assert await extract_prose_tasks(failing, "m", PROSE) == []
    assert failing.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_due_text_that_is_not_a_quote_of_the_message_is_dropped():
    out = json.dumps({"tasks": [{"title": "Call mom", "due_text": "next Tuesday at noon"}, {"title": "?"}]})
    items = await extract_prose_tasks(_client(_tool_response(out)), "m", "add tasks: call mom, buy milk and pay rent")
    assert [(i.title, i.due_text) for i in items] == [("Call mom", "")]


@pytest.mark.asyncio
async def test_more_than_twenty_drafts_fail_validation():
    out = json.dumps({"tasks": [{"title": f"Task {n}"} for n in range(21)]})
    assert await extract_prose_tasks(_client(_tool_response(out), _tool_response(out)), "m", PROSE) == []


@pytest.mark.parametrize("message, expected", [
    (PROSE, True),
    ("remind me to call mom, pay rent and email the professor, add these reminders", True),
    ("add task buy milk", False),
    ("can you add tasks, deadlines and reminders for me?", False),
    ("I have tasks, deadlines and meetings", False),
    ("", False),
])
def test_prose_list_gate(message, expected):
    assert looks_like_prose_task_list(message) is expected


def test_placeholder_keys_disable_the_model_call():
    assert not llm_available("") and not llm_available("mock-nebius-key") and not llm_available("your_nebius_key")
    assert llm_available("real-looking-key-123")


@pytest.mark.asyncio
async def test_router_previews_prose_tasks_and_falls_back_without_a_key():
    client = _client(_tool_response(GOOD))
    with patch("backend.router.get_openai_client", return_value=client), patch("backend.router.llm_available", return_value=True):
        skill, args, _ = await route_message(PROSE)
    assert skill == "add_tasks_preview" and [i["title"] for i in args["items"]] == [
        "Finish the lab report", "Call mom", "Buy milk"]

    with patch("backend.router.get_openai_client", return_value=_client()) as factory:
        skill, _, _ = await route_message(PROSE)  # placeholder key in tests: no model call
    assert skill != "add_tasks_preview"


@pytest.mark.asyncio
async def test_router_ignores_a_failed_extraction():
    failing = MagicMock()
    failing.chat.completions.create = AsyncMock(side_effect=RuntimeError("upstream down"))
    with patch("backend.router.get_openai_client", return_value=failing), patch("backend.router.llm_available", return_value=True):
        skill, _, _ = await route_message(PROSE)
    assert skill != "add_tasks_preview"


# ---- example-based intent gate ---------------------------------------------------------------------
_VOCAB = sorted({w for s in (*intent_gate.CREATE_TASK_EXAMPLES, *intent_gate.NOT_A_TASK_EXAMPLES) for w in re.findall(r"[a-z0-9]+", s)})


async def fake_embed(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [float(words.count(v)) for v in _VOCAB] + [0.01]


@pytest.fixture(autouse=True)
def _fresh_gate():
    intent_gate.reset_cache()
    yield
    intent_gate.reset_cache()


@pytest.mark.asyncio
async def test_gate_separates_requests_from_chatter():
    assert await intent_gate.classify_task_intent("add a task to submit the report by friday", fake_embed) is True
    assert await intent_gate.classify_task_intent("i was thinking i should probably start the project soon", fake_embed) is False


@pytest.mark.asyncio
async def test_gate_is_unknown_when_embeddings_fail_or_are_ambiguous():
    async def broken(text):
        return None

    async def raising(text):
        raise RuntimeError("down")

    assert await intent_gate.classify_task_intent("add a task to submit the report", broken) is None
    assert await intent_gate.classify_task_intent("add a task to submit the report", raising) is None
    intent_gate.reset_cache()
    assert await intent_gate.classify_task_intent("zzz qqq", fake_embed) is None


@pytest.mark.asyncio
async def test_gate_embeds_examples_once():
    calls = {"n": 0}

    async def counting(text):
        calls["n"] += 1
        return await fake_embed(text)

    await intent_gate.classify_task_intent("add a task to submit the report", counting)
    first = calls["n"]
    await intent_gate.classify_task_intent("what is due this week", counting)
    assert calls["n"] == first + 1


@pytest.mark.asyncio
async def test_default_gate_is_skipped_for_placeholder_keys():
    assert await intent_gate.classify_task_intent("buy milk maybe") is None


# ---- orchestrator integration ----------------------------------------------------------------------
@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    if p is None:
        pytest.skip("local Postgres is not available")
    await _wipe(p)
    yield p
    await _wipe(p)


async def _wipe(p):
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM agent_audit_log WHERE approved_by = $1", OWNER)
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", OWNER)
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = $1", OWNER)
        await conn.execute("DELETE FROM chat_request_log WHERE owner_identity = $1", OWNER)


async def _count(p):
    async with p.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM tasks WHERE user_id = $1 AND deleted_at IS NULL", OWNER)


async def _model_adds(message, title="Start the project", **kwargs):
    return await handle_message(conversation_id=CONV, message=message, user_id=OWNER, persist=False,
                                pre_routed_skill="add_task", pre_routed_args={"title": title}, **kwargs)


@pytest.mark.asyncio
async def test_model_inferred_task_from_chatter_asks_instead_of_saving(pool):
    with patch("backend.services.intent_gate.classify_task_intent", AsyncMock(return_value=False)):
        res = await _model_adds("i should probably start the project soon")
    assert res["success"] is False and "Do you want me to add" in res["response"] and "Done" not in res["response"]
    assert await _count(pool) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", [True, None])
async def test_model_inferred_task_saves_when_gate_agrees_or_is_unsure(pool, verdict):
    with patch("backend.services.intent_gate.classify_task_intent", AsyncMock(return_value=verdict)):
        res = await _model_adds("start the project soon")
    assert res["success"] is True and await _count(pool) == 1


@pytest.mark.asyncio
async def test_explicit_requests_never_consult_the_gate(pool):
    gate = AsyncMock(return_value=False)
    with patch("backend.services.intent_gate.classify_task_intent", gate):
        res = await _model_adds("please add a task to start the project tomorrow")
    assert res["success"] is True and gate.await_count == 0


@pytest.mark.asyncio
async def test_prose_preview_then_confirm_creates_the_tasks(pool):
    items = [{"title": "Finish the lab report", "domain": "coursework", "priority": "high", "duration_minutes": None, "due_text": "Friday"},
             {"title": "Call mom", "domain": "general", "priority": "medium", "duration_minutes": None, "due_text": "tomorrow"},
             {"title": "Buy milk", "domain": "general", "priority": "medium", "duration_minutes": None, "due_text": ""}]
    with patch("backend.router._prose_task_items", AsyncMock(return_value=items)), patch("backend.router.llm_available", return_value=True):
        preview = await handle_message(conversation_id=CONV, message=PROSE, user_id=OWNER, persist=False, tz="Asia/Calcutta")
    assert preview["skill_used"] == "add_tasks_preview" and "I found 3 tasks" in preview["response"]
    assert await _count(pool) == 0
    done = await handle_message(conversation_id=CONV, message="Confirm", user_id=OWNER, persist=False, tz="Asia/Calcutta")
    assert done["success"] is True and await _count(pool) == 3


@pytest.mark.asyncio
async def test_plain_chat_never_touches_the_request_log(pool):
    await handle_message(conversation_id=CONV, message="thanks, that was really helpful", user_id=OWNER,
                         persist=False, request_id="req-plain-chat-1")
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM chat_request_log WHERE owner_identity = $1", OWNER) == 0
    res = await handle_message(conversation_id=CONV, message="add task buy milk tomorrow", user_id=OWNER,
                               persist=False, request_id="req-plain-chat-2")
    assert res["success"] is True
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM chat_request_log WHERE owner_identity = $1", OWNER) == 1
