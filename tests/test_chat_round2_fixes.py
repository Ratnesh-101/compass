"""Round 2 chat fixes: task-action routing, honest not-found, claim guard, unsupported capabilities.

No database, no network. Pool and memory functions are replaced with fakes.
"""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import router_helpers
from backend.services import chat_task_actions as cta
from backend.services.action_claim_guard import guard_unbacked_action_claims
from backend.services.chat_task_actions import parse_task_action_intent

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# (1) Task-action messages are deterministic in chat_stream
# ---------------------------------------------------------------------------

def test_chat_stream_treats_task_actions_as_deterministic():
    source = (ROOT / "backend" / "services" / "chat_stream.py").read_text(encoding="utf-8")
    start = source.index("is_safety_intent = (")
    window = source[start : start + 600]
    assert "parse_task_action_intent" in window or "task_action" in window, window


@pytest.mark.parametrize(
    "message,action",
    [
        ("Mark the Operating Systems assignment as done", "complete"),
        ("Change the due date of the Hackathon project proposal to December 5", "reschedule"),
        ("Mark the hackathon task as done", "complete"),
    ],
)
def test_task_action_intent_detected(message, action):
    result = parse_task_action_intent(message)
    assert result is not None, message
    assert result["action"] == action


def test_non_task_message_is_not_a_task_action():
    assert parse_task_action_intent("mark my day as great") is None


# ---------------------------------------------------------------------------
# (2) Not-found reply and disambiguation choice
# ---------------------------------------------------------------------------

class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


def _fake_pool(conn):
    pool = MagicMock()
    pool.acquire = lambda: _Acquire(conn)
    return pool


OPEN_TASKS = [
    {"id": 1, "title": "Operating Systems assignment", "status": "open"},
    {"id": 2, "title": "Physics assignment", "status": "open"},
]


async def test_unmatched_task_name_gives_honest_not_found_and_no_pending(monkeypatch):
    conn = MagicMock()
    create = AsyncMock(return_value={"id": 99})
    monkeypatch.setattr(cta, "get_all_active_tasks_for_user", AsyncMock(return_value=OPEN_TASKS))
    monkeypatch.setattr(cta, "create_chat_pending_action", create)

    result = await cta.handle_chat_task_action(
        {"action": "complete", "target": "zebra migration xylophone"},
        message="Mark the zebra migration xylophone task as done",
        conv_id="c1",
        owner_identity="user-1",
        pool=_fake_pool(conn),
        persist=False,
    )

    reply = result["response"]
    first_sentence = re.split(r"(?<=[.!?])\s", reply.strip())[0].lower()
    assert re.search(r"(couldn'?t|could not|can'?t|cannot|did not|didn'?t|no)\b.*\b(find|found|match)", first_sentence), reply
    assert not create.called, "a pending action was created for an unmatched task"
    assert "pending_action" not in (result.get("data") or {})


@pytest.mark.parametrize(
    "act_type,expected_action,reply_text",
    [
        ("complete_task_disambiguation", "complete_task", "1"),
        ("reschedule_task_disambiguation", "reschedule_task", "the second one"),
    ],
)
async def test_disambiguation_choice_creates_new_confirm_not_applied(
    monkeypatch, act_type, expected_action, reply_text
):
    conn = MagicMock()
    conn.execute = AsyncMock()
    create = AsyncMock(return_value={"id": 100})
    resolve = AsyncMock(return_value=True)
    update = AsyncMock(return_value={"id": 1, "title": "x"})
    monkeypatch.setattr(cta, "create_chat_pending_action", create)
    monkeypatch.setattr(cta, "resolve_chat_pending_action", resolve)
    monkeypatch.setattr(cta.structured, "update_task", update)

    active = {
        "id": 55,
        "action": act_type,
        "task_ids": [1, 2],
        "task_titles": [
            {"id": 1, "title": "Operating Systems assignment", "due_date": "2026-12-05", "due_label": "Sat Dec 5, 2026"},
            {"id": 2, "title": "Physics assignment", "due_date": "2026-12-05", "due_label": "Sat Dec 5, 2026"},
        ],
    }

    text, data, applied = await cta.execute_pending_task_action(conn, active, "user-1", reply_text)

    assert not update.called, "task was mutated straight from the disambiguation choice"
    assert applied is False
    assert create.called, "no new confirm/cancel pending action was created"
    assert create.call_args.kwargs.get("action") == expected_action
    assert len(create.call_args.kwargs.get("task_ids")) == 1
    low = text.lower()
    assert "confirm" in low and "cancel" in low, text
    assert not low.startswith("done"), text


# ---------------------------------------------------------------------------
# (3) Unbacked action-claim guard
# ---------------------------------------------------------------------------

REPLACED = [
    "Updated task: 1. Submit DBMS lab - Thu Nov 26 6 PM",
    "Research area created. You can now assign tasks or store notes under that category.",
    "Category created.",
    "Chat deleted.",
]

KEPT = [
    "Would you like me to create a research area?",
    "Research area created? No, I can't create areas.",
    "I can create an area if you tell me the name.",
]


@pytest.mark.parametrize("text", REPLACED)
def test_guard_replaces_unbacked_claims(text):
    out, replaced = guard_unbacked_action_claims(text, False)
    assert replaced is True, f"input={text!r} output={out!r}"
    assert out != text


@pytest.mark.parametrize("text", REPLACED)
def test_guard_is_idempotent_on_own_output(text):
    out, _ = guard_unbacked_action_claims(text, False)
    again, replaced_again = guard_unbacked_action_claims(out, False)
    assert again == out
    assert replaced_again is False


@pytest.mark.parametrize("text", KEPT)
def test_guard_keeps_offers_and_negations(text):
    out, replaced = guard_unbacked_action_claims(text, False)
    assert (out, replaced) == (text, False)


@pytest.mark.parametrize("text", REPLACED + KEPT)
def test_guard_keeps_everything_when_action_executed(text):
    out, replaced = guard_unbacked_action_claims(text, True)
    assert (out, replaced) == (text, False)


# ---------------------------------------------------------------------------
# (4) Unsupported capability replies
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "message",
    [
        "Create a new area called Research",
        "Delete this chat",
        "Start a new chat",
        "Export my calendar",
        "Save the first one to my watchlist",
        "Prepare an application for the first one",
    ],
)
def test_unsupported_capability_reply_is_honest(message):
    reply = router_helpers.unsupported_capability_reply(message)
    assert isinstance(reply, str) and reply.strip(), message
    low = reply.lower()
    for claim in ("created", "deleted", "saved"):
        assert not re.search(rf"\b{claim}\b", low) or re.search(
            rf"(not|n't|never|no)\b[^.]*\b{claim}\b", low
        ), f"{claim!r} appears as a claim in {reply!r}"


@pytest.mark.parametrize(
    "message",
    [
        "Add a task to buy milk",
        "Delete the task buy milk",
        "Show my tasks",
        "Find internships in AI",
    ],
)
def test_supported_requests_are_not_flagged_unsupported(message):
    assert router_helpers.unsupported_capability_reply(message) is None, message
