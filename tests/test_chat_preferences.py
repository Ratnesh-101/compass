"""Tests for chat planning-preferences intent parsing and the confirm-before-save handler (no database)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import router_helpers
from backend.services import chat_preferences as cp
from backend.services.chat_preferences import parse_preferences_intent

COMBINED = "Change my planning hours to 8am to 4pm, working days Monday to Saturday and the break between tasks to 10 minutes"


def _get(result, *names):
    for name in names:
        if name in result:
            return result[name]
    return None


def _hours(r):
    return _get(r, "work_start_time"), _get(r, "work_end_time")


def _days(r):
    return _get(r, "work_days", "working_days")


def _break(r):
    return _get(r, "break_minutes", "buffer_minutes")


def test_hours_only_returns_only_hours():
    r = parse_preferences_intent("Change my planning hours to 8am to 4pm")
    assert r is not None
    assert _hours(r) == ("08:00", "16:00")
    assert _days(r) is None
    assert _break(r) is None


def test_working_days_monday_to_saturday():
    r = parse_preferences_intent("make my working days Monday to Saturday")
    assert r is not None
    assert list(_days(r)) == [1, 2, 3, 4, 5, 6]
    assert _hours(r) == (None, None)
    assert _break(r) is None


def test_break_minutes_only():
    r = parse_preferences_intent("set the break between tasks to 10 minutes")
    assert r is not None
    assert _break(r) == 10
    assert _hours(r) == (None, None)
    assert _days(r) is None


def test_combined_sentence_parses_all_three():
    r = parse_preferences_intent(COMBINED)
    assert r is not None
    assert _hours(r) == ("08:00", "16:00")
    assert list(_days(r)) == [1, 2, 3, 4, 5, 6]
    assert _break(r) == 10


def test_work_hours_9_to_5():
    r = parse_preferences_intent("work hours 9 to 5")
    assert r is not None
    assert _hours(r) == ("09:00", "17:00")


def test_from_830_to_1600_planning_hours():
    r = parse_preferences_intent("from 8:30 to 16:00 planning hours")
    assert r is not None
    assert _hours(r) == ("08:30", "16:00")


def test_weekdays():
    r = parse_preferences_intent("set my working days to weekdays")
    assert r is not None
    assert list(_days(r)) == [1, 2, 3, 4, 5]


def test_invalid_hours_rejected():
    r = parse_preferences_intent("planning hours to 25 to 30")
    assert r is None or _hours(r) == (None, None)


@pytest.mark.parametrize("message", [
    "Add a task: set the break table",
    "Can I finish this in 2 hours a day?",
    "set my alarm to 8am",
])
def test_messages_without_cue_return_none(message):
    assert parse_preferences_intent(message) is None


def test_not_explicit_task_creation():
    assert router_helpers.is_explicit_task_creation(COMBINED) is False


@pytest.mark.parametrize("message", [
    "Can I finish all of this in 2 hours a day?",
    "Can I get all my tasks done in a week?",
    "I have 30 hours of work and only 2.5 days left. Is that doable?",
])
def test_feasibility_questions_route_to_feasibility(message):
    skill, _args, _reply = router_helpers._fallback_route(message)
    assert skill == "assess_feasibility"


def test_add_task_is_not_feasibility():
    skill, _args, _reply = router_helpers._fallback_route("Add a task to buy milk")
    assert skill != "assess_feasibility"


def test_huge_whitespace_message_is_fast():
    for message in (" " * 50000, "planning hours" + " " * 50000, "planning hours 8" + " " * 50000 + "to"):
        start = time.perf_counter()
        parse_preferences_intent(message)
        assert time.perf_counter() - start < 1.0


# ---------------------------------------------------------------------------
# Handler: confirm before save
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


def _patch_common(monkeypatch, update):
    create = AsyncMock(side_effect=lambda *a, **k: {"id": 7, "action": k.get("action")})
    monkeypatch.setattr(cp, "create_chat_pending_action", create)
    monkeypatch.setattr(cp.structured, "update_scheduling_preferences", update)
    monkeypatch.setattr(cp.conversations, "get_or_create_conversation", AsyncMock(return_value="c1"))
    monkeypatch.setattr(cp.conversations, "add_message", AsyncMock(return_value=1))
    return create


def test_handler_creates_pending_and_saves_nothing(monkeypatch):
    update = AsyncMock(return_value={"ok": True})
    create = _patch_common(monkeypatch, update)

    result = asyncio.run(cp.handle_chat_preferences_stream(COMBINED, "c1", "user-1", None, _fake_pool(MagicMock())))

    assert result is not None
    assert create.await_count == 1
    assert create.await_args.kwargs["action"] == "update_preferences"
    assert not update.called
    assert not result["response"].lstrip().lower().startswith("done")
    assert result["data"]["pending_action"]


def _confirm_setup(monkeypatch, update):
    meta = {"work_start_time": "08:00", "work_end_time": "16:00", "work_days": [1, 2, 3, 4, 5, 6], "buffer_minutes": 10}
    active = {"id": 7, "action": "update_preferences", "task_titles": [meta]}
    monkeypatch.setattr(cp, "get_active_chat_pending_action", AsyncMock(return_value=active))
    monkeypatch.setattr(cp, "resolve_chat_pending_action", AsyncMock(return_value=True))
    monkeypatch.setattr(cp.structured, "update_scheduling_preferences", update)


def test_confirm_calls_update_once_and_says_done(monkeypatch):
    update = AsyncMock(return_value={"work_start_time": "08:00"})
    _confirm_setup(monkeypatch, update)

    result = asyncio.run(cp.handle_chat_preferences_stream("Confirm", "c1", "user-1", None, _fake_pool(MagicMock())))

    assert result is not None
    assert update.await_count == 1
    kwargs = update.await_args.kwargs
    assert kwargs["work_start_time"] == "08:00"
    assert kwargs["work_end_time"] == "16:00"
    assert list(kwargs["work_days"]) == [1, 2, 3, 4, 5, 6]
    assert 10 in kwargs.values()
    assert result["response"].startswith("Done")
    assert result["success"] is True


def test_failed_update_is_honest_and_not_done(monkeypatch):
    update = AsyncMock(side_effect=RuntimeError("db down"))
    _confirm_setup(monkeypatch, update)

    try:
        result = asyncio.run(cp.handle_chat_preferences_stream("Confirm", "c1", "user-1", None, _fake_pool(MagicMock())))
    except RuntimeError:
        pytest.fail("handler let the update exception escape instead of replying honestly")

    assert update.await_count == 1
    assert result is not None
    assert not result["response"].lstrip().lower().startswith("done")
    assert result["success"] is False


def test_falsy_update_result_is_not_done(monkeypatch):
    update = AsyncMock(return_value=None)
    _confirm_setup(monkeypatch, update)

    result = asyncio.run(cp.handle_chat_preferences_stream("Confirm", "c1", "user-1", None, _fake_pool(MagicMock())))

    assert result is not None
    assert not result["response"].lstrip().lower().startswith("done")
    assert result["success"] is False
