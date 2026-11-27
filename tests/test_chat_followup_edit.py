"""Unit tests for chat follow-up edits ("make it 6pm instead"); no database, no network."""

import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import chat_followup_edit as fe

MOD = "backend.services.chat_followup_edit"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def test_time_only_edit():
    r = fe.parse_followup_edit("make it 6pm instead")
    assert r is not None and r["action"] == "edit_last_task"
    assert "6pm" in r["due_time"].lower().replace(" ", "")
    assert "due_date" not in r and "priority" not in r and "title" not in r


def test_weekday_edit():
    r = fe.parse_followup_edit("change it to Friday")
    assert r is not None and r["action"] == "edit_last_task"
    assert r["due_date"].lower() in WEEKDAYS
    assert "due_time" not in r


@pytest.mark.parametrize("message,expected", [
    ("move it to tomorrow", "tomorrow"),
    ("push that to next Monday", "monday"),
])
def test_date_edits(message, expected):
    r = fe.parse_followup_edit(message)
    assert r is not None and r["action"] == "edit_last_task"
    assert expected in r["due_date"].lower()
    assert "due_time" not in r


def test_priority_edit():
    r = fe.parse_followup_edit("set it to high priority")
    assert r is not None
    assert r["action"] == "edit_last_task"
    assert r["priority"] == "high"


def test_rename_edit():
    r = fe.parse_followup_edit("rename it to Call bank about loan")
    assert r is not None
    assert r["action"] == "edit_last_task"
    assert r["title"] == "Call bank about loan"


@pytest.mark.parametrize("message", [
    "Mark the hackathon task as done",
    "Change the due date of Hackathon project proposal to December 5",
    "make it better",
    "it is raining",
])
def test_non_followups_return_none(message):
    assert fe.parse_followup_edit(message) is None


def test_bounded_regex_on_huge_whitespace():
    start = time.perf_counter()
    result = fe.parse_followup_edit(" " * 50000)
    assert time.perf_counter() - start < 1.0
    assert result is None


def _pool(conn):
    @asynccontextmanager
    async def acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = acquire
    return pool


@pytest.mark.asyncio
async def test_no_recent_task_is_honest_and_creates_no_pending():
    conn = AsyncMock()
    create = AsyncMock()
    with patch(f"{MOD}.get_last_recent_task", AsyncMock(return_value=None)), \
            patch(f"{MOD}.create_chat_pending_action", create):
        out = await fe.handle_followup_edit(
            {"action": "edit_last_task", "due_time": "6pm"}, "make it 6pm instead",
            "c1", "u1", _pool(conn), tz="UTC",
        )
    create.assert_not_called()
    assert out["success"] is False
    assert "don't see a task" in out["response"]
    assert not (out.get("data") or {}).get("pending_action")


def _task(**kw):
    base = {"id": 7, "title": "Submit report", "status": "todo",
            "created_at": datetime.now(timezone.utc), "due_date": date(2026, 12, 5)}
    base.update(kw)
    return base


async def _propose(args, message, task, create):
    conn = AsyncMock()
    update = AsyncMock()
    with patch(f"{MOD}.get_last_recent_task", AsyncMock(return_value=task)), \
            patch(f"{MOD}.create_chat_pending_action", create), \
            patch(f"{MOD}.structured.update_task", update):
        out = await fe.handle_followup_edit(args, message, "c1", "u1", _pool(conn), tz="UTC")
    return out, update


def _create_mock():
    return AsyncMock(return_value={"id": 99, "action": "edit_last_task"})


@pytest.mark.asyncio
async def test_one_recent_task_creates_pending_without_updating():
    create = _create_mock()
    out, update = await _propose(
        {"action": "edit_last_task", "due_time": "6pm"}, "make it 6pm instead", _task(), create)
    update.assert_not_called()
    create.assert_awaited_once()
    assert create.await_args.kwargs["action"] == "edit_last_task"
    assert create.await_args.kwargs["task_ids"] == [7]
    assert out["success"] is True
    assert out["data"]["pending_action"]["id"] == 99
    assert "confirm" in out["response"].lower() and "cancel" in out["response"].lower()


def _active_from(create):
    kw = create.await_args.kwargs
    return {"id": 99, "action": "edit_last_task", "task_ids": kw["task_ids"],
            "task_titles": kw["task_titles"]}


@pytest.mark.asyncio
async def test_confirm_time_only_keeps_existing_date_and_says_done():
    create = _create_mock()
    await _propose({"action": "edit_last_task", "due_time": "6pm"}, "make it 6pm instead", _task(), create)
    active = _active_from(create)
    conn = AsyncMock()
    update = AsyncMock(return_value={"id": 7, "title": "Submit report"})
    with patch(f"{MOD}.resolve_chat_pending_action", AsyncMock(return_value=True)), \
            patch(f"{MOD}.structured.update_task", update):
        reply, data, ok = await fe.execute_pending_edit_last_task(conn, active, "u1", "confirm")
    update.assert_awaited_once()
    assert update.await_args.kwargs["due_date"] == date(2026, 12, 5)
    assert reply.startswith("Done")
    assert ok is True and data is not None


@pytest.mark.asyncio
async def test_confirm_priority_calls_update_once_with_new_value():
    create = _create_mock()
    await _propose({"action": "edit_last_task", "priority": "high"}, "set it to high priority", _task(), create)
    active = _active_from(create)
    update = AsyncMock(return_value={"id": 7, "title": "Submit report"})
    with patch(f"{MOD}.resolve_chat_pending_action", AsyncMock(return_value=True)), \
            patch(f"{MOD}.structured.update_task", update):
        reply, _, ok = await fe.execute_pending_edit_last_task(AsyncMock(), active, "u1", "confirm")
    update.assert_awaited_once()
    assert update.await_args.kwargs["priority"] == "high"
    assert reply.startswith("Done") and ok is True


@pytest.mark.asyncio
async def test_failing_update_is_honest_and_not_done():
    create = _create_mock()
    await _propose({"action": "edit_last_task", "due_time": "6pm"}, "make it 6pm instead", _task(), create)
    active = _active_from(create)
    update = AsyncMock(return_value=None)
    with patch(f"{MOD}.resolve_chat_pending_action", AsyncMock(return_value=True)), \
            patch(f"{MOD}.structured.update_task", update):
        reply, data, ok = await fe.execute_pending_edit_last_task(AsyncMock(), active, "u1", "confirm")
    assert not reply.startswith("Done")
    assert "Done" not in reply
    assert "nothing was changed" in reply
    assert data is None and ok is False
