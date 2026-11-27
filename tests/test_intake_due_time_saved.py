"""A due time given in task intake is saved as a timed deadline (due_at) and exported as a timed event."""

import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.services import task_intake
from backend.services.calendar_ics import _task_time_fields
from backend.services.task_intake import _create_all, _preview_items
from backend.services.task_intake_parse import IntakeItem, ParsedIntake

TZ = "Asia/Kolkata"


class _Conn:
    async def execute(self, *args, **kwargs):
        return "INSERT 0 1"


def _commit(due_text: str) -> dict:
    """Preview then commit one 'call the bank' item; return the kwargs passed to create_task."""
    bare_time = len(due_text) == 5 and due_text[2] == ":" and due_text[:2].isdigit() and due_text[3:].isdigit()
    item = IntakeItem(
        title="call the bank", domain="general", priority="medium", duration_minutes=None,
        due_text="" if bare_time else due_text, due_time=due_text if bare_time else None,
    )
    items = _preview_items(ParsedIntake((item,), 1, ()), TZ)
    seen: dict = {}

    async def fake_create_task(conn, **kwargs):
        seen.update(kwargs)
        return {"id": 1, "title": kwargs["title"]}

    with patch.object(task_intake.structured, "create_task", fake_create_task):
        asyncio.run(_create_all(_Conn(), items, "owner-1", "conv-1"))
    return seen


def test_ics_due_date_and_due_at_is_timed():
    lines = _task_time_fields({"due_date": "2026-11-28", "due_at": "2026-11-28T11:30:00+00:00"})
    assert lines == ["DTSTART:20261128T113000Z", "DTEND:20261128T123000Z"]


def test_ics_due_date_only_is_all_day():
    lines = _task_time_fields({"due_date": "2026-11-28"})
    assert lines is not None and lines[0] == "DTSTART;VALUE=DATE:20261128"


def test_ics_scheduled_start_wins_over_due_at():
    lines = _task_time_fields({
        "due_date": "2026-11-28",
        "due_at": "2026-11-28T11:30:00+00:00",
        "scheduled_start": "2026-11-28T08:00:00+00:00",
        "scheduled_end": "2026-11-28T09:00:00+00:00",
    })
    assert lines == ["DTSTART:20261128T080000Z", "DTEND:20261128T090000Z"]


def test_ics_due_at_only_is_timed():
    lines = _task_time_fields({"due_at": "2026-11-28T11:30:00+00:00"})
    assert lines == ["DTSTART:20261128T113000Z", "DTEND:20261128T123000Z"]


def test_commit_with_date_and_time_saves_due_at_in_utc():
    seen = _commit("2026-11-28 17:00")
    assert seen["title"] == "call the bank"
    assert seen["due_at"] == datetime.fromisoformat("2026-11-28T11:30:00+00:00")
    assert seen["due_date"].isoformat() == "2026-11-28"


def test_commit_without_time_has_no_due_at():
    seen = _commit("2026-11-28")
    assert seen["due_at"] is None
    assert seen["due_date"].isoformat() == "2026-11-28"


def test_commit_with_time_but_no_date_uses_today_in_zone():
    seen = _commit("17:00")
    today = datetime.now(ZoneInfo(TZ)).date()
    assert seen["due_at"] is not None
    assert seen["due_date"] == today
    assert seen["due_at"].astimezone(ZoneInfo(TZ)).date() == today
    assert seen["due_at"].astimezone(ZoneInfo(TZ)).strftime("%H:%M") == "17:00"
