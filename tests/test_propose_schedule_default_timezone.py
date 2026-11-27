"""propose_schedule must use the request timezone when no explicit zone is passed (chat path)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from zoneinfo import ZoneInfo

from backend.services.task_time import request_timezone

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)  # Fri 12:00 UTC = 17:30 IST


class _Conn:
    pass


class _Acq:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *exc):
        return None


class _Pool:
    def acquire(self):
        return _Acq()


def _patch(monkeypatch):
    class FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW

    tasks = [
        {"id": i, "title": f"T{i}", "priority": "medium", "domain": "general", "status": "open",
         "due_date": None, "duration_minutes": 90, "owner_id": "u1"}
        for i in range(1, 7)
    ]
    prefs = {"work_start_time": "09:00:00", "work_end_time": "18:00:00",
             "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}
    monkeypatch.setattr("backend.skills.handlers.calendar.datetime", FixedDT)
    monkeypatch.setattr("backend.memory.structured.list_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.memory.structured.get_scheduling_preferences", AsyncMock(return_value=prefs))
    monkeypatch.setattr("backend.memory.structured.get_all_dependencies_map", AsyncMock(return_value={}))
    monkeypatch.setattr("backend.services.calendar.get_calendar_freebusy", AsyncMock(return_value=[]))


async def _propose(args):
    from backend.skills.handlers.calendar import handle_propose_schedule

    return (await handle_propose_schedule({"user_id": "u1", **args}, _Pool()))["data"]


@pytest.mark.asyncio
async def test_context_zone_used_when_no_timezone_arg(monkeypatch):
    _patch(monkeypatch)
    token = request_timezone.set("Asia/Kolkata")
    try:
        data = await _propose({})
    finally:
        request_timezone.reset(token)
    assert data["timezone"] == "Asia/Kolkata"
    assert data["scheduled"]
    for b in data["scheduled"]:
        s = datetime.fromisoformat(b["scheduled_start"]).astimezone(IST)
        e = datetime.fromisoformat(b["scheduled_end"]).astimezone(IST)
        assert s.isoweekday() <= 5
        assert s.date() == e.date()
        assert (s.hour, s.minute) >= (9, 0), b
        assert (e.hour, e.minute) <= (18, 0), b


@pytest.mark.asyncio
async def test_explicit_timezone_arg_wins_over_context(monkeypatch):
    _patch(monkeypatch)
    token = request_timezone.set("Asia/Kolkata")
    try:
        data = await _propose({"timezone": "UTC"})
    finally:
        request_timezone.reset(token)
    assert data["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_falls_back_to_utc_with_neither(monkeypatch):
    _patch(monkeypatch)
    assert request_timezone.get() is None
    data = await _propose({})
    assert data["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_repair_plan_blocks_passes_request_zone(monkeypatch):
    from backend.agents import schedule_deterministic as sd

    prefs = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "working_days": [1, 2, 3, 4, 5]}
    monkeypatch.setattr(sd, "fetch_saved_preferences", AsyncMock(return_value=prefs))
    fake = AsyncMock(return_value={"data": {"scheduled": [{"task_id": 1}]}})
    monkeypatch.setattr("backend.skills.handlers.calendar.handle_propose_schedule", fake)
    bad = [{"task_id": 1, "title": "X", "scheduled_start": "2020-01-01T00:00:00+00:00",
            "scheduled_end": "2020-01-01T01:00:00+00:00"}]
    token = request_timezone.set("Asia/Kolkata")
    try:
        out = await sd.repair_plan_blocks(bad, object(), "u1", "Asia/Kolkata", {1: {"id": 1}})
    finally:
        request_timezone.reset(token)
    assert out == [{"task_id": 1}]
    fake.assert_awaited_once()
    assert fake.await_args.args[0]["timezone"] == "Asia/Kolkata"
