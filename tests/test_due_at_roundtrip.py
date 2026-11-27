"""due_at round trip: output model, chat reschedule/edit actions, ICS export, and the real DB."""

from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest

from backend.memory import structured
from backend.services import chat_followup_edit, chat_task_actions
from backend.services.calendar_ics import generate_ics_feed
from backend.services.task_service import build_frontend_task

UTC = datetime.timezone.utc
DUE_DATE = datetime.date(2026, 11, 28)
DUE_AT = datetime.datetime(2026, 11, 28, 12, 30, tzinfo=UTC)
DUE_AT_ISO = "2026-11-28T12:30:00+00:00"


def _row(**over):
    row = {
        "id": 7,
        "title": "Lab report",
        "domain": "academics",
        "status": "open",
        "priority": "medium",
        "due_date": DUE_DATE,
        "created_at": datetime.datetime(2026, 11, 20, 9, 0, tzinfo=UTC),
    }
    row.update(over)
    return row


# ---- (1) output model -----------------------------------------------------


def test_output_model_exposes_due_at_as_iso_string():
    out = build_frontend_task(_row(due_at=DUE_AT))
    assert isinstance(out.due_at, str)
    assert datetime.datetime.fromisoformat(out.due_at) == DUE_AT
    assert out.model_dump()["due_at"] == out.due_at


@pytest.mark.parametrize("row_extra", [{}, {"due_at": None}])
def test_output_model_due_at_is_null_when_absent(row_extra):
    out = build_frontend_task(_row(**row_extra))
    assert out.due_at is None
    assert out.model_dump()["due_at"] is None


# ---- (2) chat actions -----------------------------------------------------


class _Conn:
    def __init__(self):
        self.executed: list[tuple] = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "UPDATE 1"


@pytest.fixture
def captured_update(monkeypatch):
    calls: list[dict] = []

    async def fake_update_task(conn, task_id, owner_id=None, **kwargs):
        calls.append({"task_id": task_id, "owner_id": owner_id, **kwargs})
        return {"id": task_id, "title": "Lab report"}

    async def fake_resolve(conn, action_id, status):
        return True

    monkeypatch.setattr(structured, "update_task", fake_update_task)
    monkeypatch.setattr(chat_task_actions, "resolve_chat_pending_action", fake_resolve)
    monkeypatch.setattr(chat_followup_edit, "resolve_chat_pending_action", fake_resolve)
    return calls


@pytest.mark.asyncio
async def test_reschedule_task_with_time_passes_due_at(captured_update):
    action = {
        "id": 1,
        "action": "reschedule_task",
        "task_ids": [7],
        "task_titles": [{
            "id": 7, "title": "Lab report",
            "due_date": "2026-11-28", "due_at": DUE_AT_ISO, "due_label": "Sat Nov 28, 2026 at 6:00 PM",
        }],
    }
    conn = _Conn()
    msg, data, ok = await chat_task_actions.execute_pending_task_action(conn, action, "u1", "confirm")
    assert ok is True, msg
    assert len(captured_update) == 1
    call = captured_update[0]
    assert call["due_date"] == DUE_DATE
    assert call["due_at"] == DUE_AT


@pytest.mark.asyncio
async def test_reschedule_task_date_only_does_not_set_due_at(captured_update):
    action = {
        "id": 2,
        "action": "reschedule_task",
        "task_ids": [7],
        "task_titles": [{
            "id": 7, "title": "Lab report",
            "due_date": "2026-11-28", "due_at": None, "due_label": "Sat Nov 28, 2026",
        }],
    }
    conn = _Conn()
    msg, data, ok = await chat_task_actions.execute_pending_task_action(conn, action, "u1", "confirm")
    assert ok is True, msg
    assert len(captured_update) == 1
    call = captured_update[0]
    assert call["due_date"] == DUE_DATE
    assert call.get("due_at") is None  # a date-only change on a task with no time stays without a time
    assert conn.executed == []


@pytest.mark.asyncio
async def test_edit_last_task_time_only_passes_due_at_and_keeps_date(monkeypatch, captured_update):
    task = {"id": 7, "title": "Lab report", "due_date": DUE_DATE, "status": "open"}
    created: list[dict] = []

    async def fake_last_task(conn, owner, within_minutes=60, include_demo=False):
        return task

    async def fake_create_pending(conn, **kwargs):
        created.append(kwargs)
        return {"id": 99, **kwargs}

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return False

    class _Pool:
        def acquire(self):
            return _Acquire()

    monkeypatch.setattr(chat_followup_edit, "get_last_recent_task", fake_last_task)
    monkeypatch.setattr(chat_followup_edit, "create_chat_pending_action", fake_create_pending)

    result = await chat_followup_edit.handle_followup_edit(
        args={"action": "edit_last_task", "due_text": "6 PM", "due_time": "6 PM"},
        message="make it 6 PM",
        conv_id="c1",
        owner_identity="u1",
        pool=_Pool(),
        tz="Asia/Kolkata",
    )
    assert result["success"] is True
    assert len(created) == 1

    pending = {
        "id": 99,
        "action": "edit_last_task",
        "task_ids": created[0]["task_ids"],
        "task_titles": created[0]["task_titles"],
    }
    conn = _Conn()
    msg, data, ok = await chat_followup_edit.execute_pending_edit_last_task(conn, pending, "u1", "confirm")
    assert ok is True, msg
    assert len(captured_update) == 1
    call = captured_update[0]
    assert call["due_date"] == DUE_DATE
    assert call["due_at"] == DUE_AT


# ---- (3) ICS --------------------------------------------------------------


def test_ics_uses_timed_event_for_serialised_task_with_due_at():
    out = build_frontend_task(_row(due_at=DUE_AT)).model_dump()
    assert out["due_date"] == "2026-11-28"
    ics = generate_ics_feed([out])
    assert "DTSTART:20261128T123000Z" in ics
    assert "DTSTART;VALUE=DATE" not in ics


# ---- (4) real DB (CI only; skipped locally without a database) -------------


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_real_db_due_at_roundtrip_create_list_update():
    from backend.memory.db import get_pool

    try:
        pool = await asyncio.wait_for(get_pool(), timeout=15.0)
    except Exception as exc:  # no database reachable locally
        pytest.skip(f"database unavailable: {exc!r}")
    if not pool:
        pytest.skip("database unavailable")

    user_id = f"due-at-{uuid.uuid4().hex}"
    new_at = datetime.datetime(2026, 12, 1, 4, 0, tzinfo=UTC)
    task_id = None
    try:
        async with pool.acquire() as conn:
            created = await structured.create_task(
                conn, domain="general", title="due_at roundtrip", due_date=DUE_DATE,
                due_at=DUE_AT, user_id=user_id,
            )
            task_id = created["id"]

            rows = await structured.list_tasks(conn, user_id=user_id)
            row = next(r for r in rows if r["id"] == task_id)
            assert isinstance(row["due_at"], datetime.datetime)
            assert row["due_at"] == DUE_AT
            assert row["due_date"] == DUE_DATE

            updated = await structured.update_task(
                conn, task_id, owner_id=user_id,
                due_date=datetime.date(2026, 12, 1), due_at=new_at,
            )
            assert updated is not None

            rows = await structured.list_tasks(conn, user_id=user_id)
            row = next(r for r in rows if r["id"] == task_id)
            assert row["due_at"] == new_at
            assert row["due_date"] == datetime.date(2026, 12, 1)
    finally:
        if task_id is not None:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)
