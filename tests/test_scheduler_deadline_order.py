"""Deadline-first ordering and honest unassigned reporting in the scheduler (no database)."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.services.scheduler import allocate_task_slots, get_available_windows

TZ_NAME = "America/New_York"
ZONE = ZoneInfo(TZ_NAME)
NOW_UTC = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
NOW_LOCAL = datetime(2026, 11, 25, 10, 0, tzinfo=ZONE)  # Wednesday, 15:00Z (EST)


def _sort(tasks, now):
    from backend.services.scheduler import sort_tasks_for_scheduling

    return sort_tasks_for_scheduling(tasks, now)


def _ids(tasks):
    return [t["id"] for t in tasks]


def _task(tid, due, minutes=60, priority="medium"):
    return {"id": tid, "title": f"T{tid}", "due_date": due, "duration_minutes": minutes, "priority": priority}


def _windows(now_local, days=10):
    start = now_local.astimezone(timezone.utc)
    return get_available_windows([], start, start + timedelta(days=days), tz_name=TZ_NAME)


def _allocate(tasks, windows):
    return allocate_task_slots(
        tasks, windows, buffer_minutes=15, not_before=NOW_LOCAL.astimezone(timezone.utc), tz_name=TZ_NAME
    )


def _eod_utc(day):
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=ZONE).astimezone(timezone.utc)


# ---- (1) ordering -------------------------------------------------------------

def test_mixed_deadline_types_sort_earliest_first_and_unusable_last():
    tasks = [
        _task(1, None),
        _task(2, "not-a-date"),
        _task(3, date(2026, 11, 27)),                                  # date-only: end of 27th
        _task(4, datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)),   # datetime on the 26th
        _task(5, "2026-11-28T09:00:00+00:00"),                          # ISO string
        _task(6, "2026-11-27"),                                         # ISO date-only string, same as id 3
        _task(7, datetime(2026, 11, 26, 8, 0)),                         # naive datetime
    ]
    got = _ids(_sort(tasks, NOW_UTC))
    assert got[:5] == [7, 4, 3, 6, 5]
    assert set(got[5:]) == {1, 2}


def test_date_only_deadline_means_end_of_that_day():
    tasks = [
        _task(1, "2026-11-26"),                                         # end of day 26th
        _task(2, "2026-11-26T20:00:00+00:00"),                          # earlier than end of day 26th
    ]
    assert _ids(_sort(tasks, NOW_UTC)) == [2, 1]


def test_sort_does_not_mutate_input():
    tasks = [_task(2, "2026-11-30"), _task(1, "2026-11-26")]
    snapshot = list(tasks)
    _sort(tasks, NOW_UTC)
    assert tasks == snapshot


# ---- (4) tie-breaks -----------------------------------------------------------

def test_same_deadline_higher_priority_first():
    tasks = [
        _task(1, "2026-11-30", priority="low"),
        _task(2, "2026-11-30", priority="urgent"),
        _task(3, "2026-11-30", priority="medium"),
        _task(4, "2026-11-30", priority="high"),
    ]
    assert _ids(_sort(tasks, NOW_UTC)) == [2, 4, 3, 1]


def test_same_deadline_and_priority_shorter_duration_then_id():
    tasks = [
        _task(9, "2026-11-30", minutes=120),
        _task(5, "2026-11-30", minutes=30),
        _task(3, "2026-11-30", minutes=30),
    ]
    assert _ids(_sort(tasks, NOW_UTC)) == [3, 5, 9]


def test_earlier_deadline_beats_higher_priority():
    tasks = [_task(1, "2026-11-30", priority="urgent"), _task(2, "2026-11-26", priority="low")]
    assert _ids(_sort(tasks, NOW_UTC)) == [2, 1]


# ---- (5) overdue --------------------------------------------------------------

def test_overdue_task_goes_first():
    tasks = [
        _task(1, "2026-11-26", priority="urgent"),
        _task(2, None, priority="urgent"),
        _task(3, "2026-11-20", minutes=600, priority="low"),
    ]
    assert _ids(_sort(tasks, NOW_UTC))[0] == 3


def test_overdue_task_is_placed_first_by_allocator_when_possible():
    # Overdue deadline is in the past, so it cannot be placed before it; it must still be reported, not hidden.
    tasks = [_task(1, "2026-11-20", minutes=60), _task(2, "2026-11-30", minutes=60)]
    result = _allocate(tasks, _windows(NOW_LOCAL))
    assert [s["task_id"] for s in result["scheduled"]] == [2]
    assert [u["task_id"] for u in result["unassigned"]] == [1]
    assert "0 unassigned" not in result["summary"]


# ---- (2) QA scenario ----------------------------------------------------------

def test_qa_scenario_earliest_deadline_is_placed_first_and_meets_deadline():
    tasks = [
        _task(2, "2026-12-03", minutes=180),
        _task(4, None, minutes=60),
        _task(1, "2026-11-26", minutes=120),
        _task(3, "2026-11-27", minutes=240),
    ]
    result = _allocate(tasks, _windows(NOW_LOCAL))
    placed = {s["task_id"]: s for s in result["scheduled"]}
    assert set(placed) == {1, 2, 3, 4}
    assert result["unassigned"] == []

    start = {k: datetime.fromisoformat(v["scheduled_start"]) for k, v in placed.items()}
    end = {k: datetime.fromisoformat(v["scheduled_end"]) for k, v in placed.items()}
    assert start[1] < start[2]
    assert start[1] < start[3]
    assert end[1] <= _eod_utc(date(2026, 11, 26))
    assert end[3] <= _eod_utc(date(2026, 11, 27))
    assert end[2] <= _eod_utc(date(2026, 12, 3))
    assert "unassigned" not in result["summary"] and "could not be placed" not in result["summary"]


def test_qa_scenario_sort_order():
    tasks = [
        _task(2, "2026-12-03", minutes=180),
        _task(4, None, minutes=60),
        _task(1, "2026-11-26", minutes=120),
        _task(3, "2026-11-27", minutes=240),
    ]
    assert _ids(_sort(tasks, NOW_LOCAL)) == [1, 3, 2, 4]


# ---- (3) a task that cannot fit -----------------------------------------------

def test_task_that_cannot_fit_is_not_placed_and_counted():
    # 600 minutes due tomorrow; only 8 free hours today and 9 tomorrow, none long enough.
    tasks = [_task(1, "2026-11-26", minutes=600), _task(2, "2026-11-30", minutes=60)]
    windows = _windows(NOW_LOCAL, days=1)
    result = _allocate(tasks, windows)
    assert [s["task_id"] for s in result["scheduled"]] == [2]
    assert [u["task_id"] for u in result["unassigned"]] == [1]
    summary = result["summary"]
    assert "0 unassigned" not in summary
    assert "1" in summary
    assert "could not be placed" in summary.lower()


def test_task_that_fits_a_window_only_after_its_deadline_is_unassigned():
    # Free time exists only after the deadline (Nov 25 12:00 local); 120 min needs a 2h block before then.
    due = datetime(2026, 11, 25, 12, 0, tzinfo=ZONE)
    # Occupy 10:00-18:00 today so the first free time is after the deadline.
    busy = [{"start": NOW_LOCAL.astimezone(timezone.utc),
             "end": datetime(2026, 11, 25, 18, 0, tzinfo=ZONE).astimezone(timezone.utc)}]
    start = NOW_LOCAL.astimezone(timezone.utc)
    windows = get_available_windows(busy, start, start + timedelta(days=5), tz_name=TZ_NAME)
    result = _allocate([_task(1, due, minutes=120)], windows)
    assert result["scheduled"] == []
    assert [u["task_id"] for u in result["unassigned"]] == [1]
    summary = result["summary"]
    assert "0 unassigned" not in summary
    assert "1 task could not be placed before its deadline" in summary


def test_summary_counts_match_unassigned_list():
    tasks = [_task(1, "2026-11-26", minutes=600), _task(2, "2026-11-26", minutes=700), _task(3, None, minutes=30)]
    result = _allocate(tasks, _windows(NOW_LOCAL, days=1))
    assert len(result["unassigned"]) == 2
    assert "0 unassigned" not in result["summary"]
    assert "2" in result["summary"]
