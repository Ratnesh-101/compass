"""allocate_task_slots reports whether each placed task has a deadline (no database)."""

from datetime import datetime, timedelta, timezone

from backend.services.scheduler import allocate_task_slots, get_available_windows

START = datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc)  # Wednesday


def _windows():
    return get_available_windows([], START, START + timedelta(days=10), tz_name="UTC")


def _task(tid, due, minutes=60):
    return {"id": tid, "title": f"T{tid}", "due_date": due, "duration_minutes": minutes, "priority": "medium"}


def _allocate(tasks):
    return allocate_task_slots(tasks, _windows(), buffer_minutes=15, not_before=START, tz_name="UTC")


def test_dated_task_has_deadline_true():
    result = _allocate([_task(1, "2026-12-03")])
    assert [s["has_deadline"] for s in result["scheduled"]] == [True]


def test_undated_task_has_deadline_false():
    result = _allocate([_task(1, None)])
    assert [s["has_deadline"] for s in result["scheduled"]] == [False]


def test_mixed_flags_follow_each_task_and_dated_come_first():
    result = _allocate([_task(1, None), _task(2, "2026-12-03"), _task(3, None, minutes=30)])
    assert [s["task_id"] for s in result["scheduled"]] == [2, 3, 1]
    flags = {s["task_id"]: s["has_deadline"] for s in result["scheduled"]}
    assert flags == {2: True, 1: False, 3: False}


def test_has_deadline_is_a_real_bool():
    result = _allocate([_task(1, "2026-12-03"), _task(2, None)])
    assert all(type(s["has_deadline"]) is bool for s in result["scheduled"])
