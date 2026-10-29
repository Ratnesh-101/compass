"""Scheduler working window and workday boundaries follow the user's IANA timezone (no schema change)."""

from datetime import datetime, timezone

import pytest

from backend.services.scheduler import allocate_task_slots, get_available_windows
from backend.services.user_timezone import resolve_timezone_name
from backend.skills import SKILL_REGISTRY


def _windows(tz, start, end):
    return [(w.start.isoformat(), w.end.isoformat()) for w in get_available_windows([], start, end, tz_name=tz)]


# ---- validation -------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", "  ", "Not/AZone", "../../etc/passwd", "/etc/passwd",
                                 "Asia/Kolkata\n; drop", "A" * 200, 123, "Asia//Kolkata", "zone.tab", "UTC\x00"])
def test_unknown_or_hostile_timezone_falls_back_to_utc(raw):
    assert resolve_timezone_name(raw) == "UTC"


@pytest.mark.parametrize("raw", ["Asia/Kolkata", "America/New_York", "Pacific/Auckland", "UTC", "Pacific/Apia"])
def test_valid_timezone_is_kept(raw):
    assert resolve_timezone_name(raw) == raw


# ---- window computation -----------------------------------------------------

def test_default_without_timezone_stays_utc():
    start = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)  # Monday
    wins = get_available_windows([], start, datetime(2026, 9, 21, 23, 59, tzinfo=timezone.utc))
    assert [(w.start.hour, w.end.hour) for w in wins] == [(9, 18)]


def test_kolkata_window_is_0330_to_1230_utc():
    start = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
    got = _windows("Asia/Kolkata", start, datetime(2026, 9, 21, 23, 59, tzinfo=timezone.utc))
    assert got == [("2026-09-21T03:30:00+00:00", "2026-09-21T12:30:00+00:00")]


def test_kolkata_workdays_are_monday_to_friday_local():
    start = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 27, 23, 59, tzinfo=timezone.utc)
    starts = [s for s, _ in _windows("Asia/Kolkata", start, end)]
    assert starts[0] == "2026-09-21T03:30:00+00:00"
    assert starts[-1] == "2026-09-25T03:30:00+00:00"
    assert len(starts) == 5


def test_new_york_window_shifts_across_dst_end():
    # US DST ends Sunday 2026-11-01. Fri Oct 30 is EDT (UTC-4): 13:00Z. Mon Nov 2 is EST (UTC-5): 14:00Z.
    start = datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 11, 2, 23, 59, tzinfo=timezone.utc)
    got = _windows("America/New_York", start, end)
    assert got == [
        ("2026-10-30T13:00:00+00:00", "2026-10-30T22:00:00+00:00"),
        ("2026-11-02T14:00:00+00:00", "2026-11-02T23:00:00+00:00"),
    ]


def test_new_york_spring_forward_week():
    # DST starts Sunday 2026-03-08: Fri Mar 6 EST 14:00Z, Mon Mar 9 EDT 13:00Z.
    start = datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 9, 23, 59, tzinfo=timezone.utc)
    got = _windows("America/New_York", start, end)
    assert [s for s, _ in got] == ["2026-03-06T14:00:00+00:00", "2026-03-09T13:00:00+00:00"]


def test_plus_13_zone_workday_straddles_utc_date():
    # Pacific/Auckland in January is NZDT (UTC+13). Mon 2027-01-04 09:00 local = Sun 2027-01-03 20:00Z.
    start = datetime(2027, 1, 3, 0, 0, tzinfo=timezone.utc)
    end = datetime(2027, 1, 4, 23, 59, tzinfo=timezone.utc)
    got = _windows("Pacific/Auckland", start, end)
    assert got[0] == ("2027-01-03T20:00:00+00:00", "2027-01-04T05:00:00+00:00")


def test_search_start_clips_local_window():
    start = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)  # 11:30 IST
    got = _windows("Asia/Kolkata", start, datetime(2026, 9, 21, 23, 59, tzinfo=timezone.utc))
    assert got == [("2026-09-21T06:00:00+00:00", "2026-09-21T12:30:00+00:00")]


def test_allocator_date_only_due_uses_local_end_of_day():
    # Due 2026-09-21 (date only): IST end of day is 18:29:59Z, so a slot at 19:00Z is too late for IST users.
    from backend.services.scheduler import TimeWindow
    late = [TimeWindow(start=datetime(2026, 9, 21, 19, 0, tzinfo=timezone.utc),
                       end=datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc))]
    task = [{"id": 1, "title": "t", "duration_minutes": 30, "due_date": "2026-09-21"}]
    assert allocate_task_slots(task, late, tz_name="Asia/Kolkata")["conflicts"]
    assert allocate_task_slots(task, late)["scheduled"]


# ---- handlers ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_availability_handler_uses_timezone_and_echoes_it():
    handler = SKILL_REGISTRY["get_calendar_availability"]
    result = await handler(
        {"start_date": "2026-09-21", "end_date": "2026-09-21", "timezone": "Asia/Kolkata"}, pool=None)
    data = result["data"]
    assert data["timezone"] == "Asia/Kolkata"
    assert data["free_windows"][0]["start"].startswith("2026-09-21T03:30")
    assert data["free_windows"][0]["end"].startswith("2026-09-21T12:30")


@pytest.mark.asyncio
async def test_availability_handler_unknown_timezone_is_utc():
    handler = SKILL_REGISTRY["get_calendar_availability"]
    result = await handler(
        {"start_date": "2026-09-21", "end_date": "2026-09-21", "timezone": "Mars/Olympus"}, pool=None)
    assert result["data"]["timezone"] == "UTC"
    assert result["data"]["free_windows"][0]["start"].startswith("2026-09-21T09:00")


@pytest.mark.asyncio
async def test_propose_handler_echoes_timezone():
    handler = SKILL_REGISTRY["propose_schedule"]
    result = await handler({"target_date": "2099-01-05", "timezone": "Asia/Kolkata"}, pool=None)
    assert result["data"]["timezone"] == "Asia/Kolkata"
    default = await handler({"target_date": "2099-01-05"}, pool=None)
    assert default["data"]["timezone"] == "UTC"


@pytest.mark.asyncio
async def test_availability_endpoint_accepts_tz_query(client, auth_headers):
    res = await client.get("/api/calendar/availability",
                           params={"start_date": "2026-09-21", "end_date": "2026-09-21", "tz": "Asia/Kolkata"},
                           headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["timezone"] == "Asia/Kolkata"


# ---- user-facing deadline classification -------------------------------------

def test_task_countdown_uses_requested_timezone():
    from backend.services.task_service import build_frontend_task
    now = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)  # Sep 22 01:30 IST
    row = {"id": 1, "title": "x", "due_date": "2026-09-21", "status": "open", "priority": "medium"}
    utc_out = build_frontend_task(row, now=now, user_tz_name="UTC")
    ist_out = build_frontend_task(row, now=now, user_tz_name="Asia/Kolkata")
    assert utc_out.countdown != ist_out.countdown
    assert "overdue" in ist_out.countdown.lower()
