"""Scheduling from 'now' inside today's planning window, in IST (no database, no clock)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.services.scheduler import (
    allocate_task_slots,
    earliest_schedulable_start,
    get_available_windows,
)

TZ_NAME = "Asia/Kolkata"
IST = ZoneInfo(TZ_NAME)


def _task(tid, due, minutes=60, priority="medium"):
    return {"id": tid, "title": f"T{tid}", "due_date": due, "duration_minutes": minutes, "priority": priority}


def _plan(tasks, now_local):
    """Mirror propose_schedule: clamp start to now, 09:00-18:00 Mon-Fri, empty calendar."""
    now = now_local.astimezone(timezone.utc)
    start = earliest_schedulable_start(now, now)
    windows = get_available_windows(
        [],
        start,
        start + timedelta(days=7),
        work_start_time="09:00:00",
        work_end_time="18:00:00",
        work_days=[1, 2, 3, 4, 5],
        buffer_minutes=15,
        tz_name=TZ_NAME,
    )
    result = allocate_task_slots(tasks, windows, buffer_minutes=15, not_before=start, tz_name=TZ_NAME)
    return now, result


def _local(iso):
    return datetime.fromisoformat(iso).astimezone(IST)


def test_friday_morning_task_due_saturday_is_placed_today_after_now():
    now_local = datetime(2026, 11, 27, 10, 10, tzinfo=IST)  # Friday
    assert now_local.isoweekday() == 5
    now, result = _plan([_task(1, "2026-11-28")], now_local)

    assert result["unassigned"] == []
    assert [s["task_id"] for s in result["scheduled"]] == [1]
    start = _local(result["scheduled"][0]["scheduled_start"])
    assert start.date() == now_local.date()
    assert start >= datetime(2026, 11, 27, 10, 15, tzinfo=IST)
    assert start.astimezone(timezone.utc) >= now


def test_friday_after_hours_task_due_saturday_is_not_placed_and_reported_once():
    now_local = datetime(2026, 11, 27, 18, 30, tzinfo=IST)
    _, result = _plan([_task(1, "2026-11-28")], now_local)

    assert result["scheduled"] == []
    assert [u["task_id"] for u in result["unassigned"]] == [1]
    assert len(result["unassigned"]) == 1
    assert len([c for c in result["conflicts"] if c["task_id"] == 1]) <= 1
    assert result["summary"].count("1 task could not be placed") == 1


def test_monday_early_morning_task_due_monday_starts_at_work_start():
    now_local = datetime(2026, 11, 30, 8, 0, tzinfo=IST)  # Monday
    assert now_local.isoweekday() == 1
    now, result = _plan([_task(1, "2026-11-30")], now_local)

    assert result["unassigned"] == []
    start = _local(result["scheduled"][0]["scheduled_start"])
    assert start >= datetime(2026, 11, 30, 9, 0, tzinfo=IST)
    assert start.date() == now_local.date()
    assert start.astimezone(timezone.utc) >= now


def test_undated_tasks_go_after_dated_ones_and_have_no_deadline_flag():
    now_local = datetime(2026, 11, 30, 8, 0, tzinfo=IST)
    tasks = [_task(1, None), _task(2, None), _task(3, "2026-12-02"), _task(4, "2026-12-01")]
    _, result = _plan(tasks, now_local)

    assert result["unassigned"] == []
    by_id = {s["task_id"]: s for s in result["scheduled"]}
    assert set(by_id) == {1, 2, 3, 4}
    start = {k: _local(v["scheduled_start"]) for k, v in by_id.items()}
    assert start[4] < start[3] < min(start[1], start[2])
    assert by_id[1]["has_deadline"] is False
    assert by_id[2]["has_deadline"] is False
    assert by_id[3]["has_deadline"] is True
    assert by_id[4]["has_deadline"] is True


def test_unplaceable_task_is_listed_once_and_summary_counts_it_once():
    now_local = datetime(2026, 11, 27, 10, 10, tzinfo=IST)
    # 10 hours cannot fit in any 9-hour planning window before the deadline.
    tasks = [_task(1, "2026-11-28", minutes=600), _task(2, "2026-12-02", minutes=60)]
    _, result = _plan(tasks, now_local)

    assert [u["task_id"] for u in result["unassigned"]] == [1]
    assert [s["task_id"] for s in result["scheduled"]] == [2]
    summary = result["summary"]
    assert summary.count("1 task could not be placed") == 1
    # Placed count must not include the unplaceable task.
    assert "Scheduled 2" not in summary
    assert "(1 unassigned" not in summary
