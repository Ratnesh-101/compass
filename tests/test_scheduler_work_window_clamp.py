"""Scheduling windows are clamped to the local work window of working days."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.services.scheduler import (
    allocate_task_slots,
    ceil_to_quarter_hour,
    get_available_windows,
)

IST = ZoneInfo("Asia/Kolkata")
TZ = "Asia/Kolkata"


def _now(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=IST).astimezone(timezone.utc)


def _plan(now, tasks, work_days=None):
    start = ceil_to_quarter_hour(now)
    windows = get_available_windows(
        [], start, start + timedelta(days=14),
        work_start_time="09:00", work_end_time="18:00",
        work_days=work_days, buffer_minutes=15, tz_name=TZ,
    )
    res = allocate_task_slots(
        tasks, windows, buffer_minutes=15, now=now, tz_name=TZ,
    )
    blocks = []
    for s in res["scheduled"]:
        a = datetime.fromisoformat(s["scheduled_start"]).astimezone(IST)
        b = datetime.fromisoformat(s["scheduled_end"]).astimezone(IST)
        blocks.append((s["task_id"], a, b))
    return res, sorted(blocks, key=lambda x: x[1])


def _check_invariants(blocks, now):
    prev_end = None
    for _tid, a, b in blocks:
        assert a.date() == b.date()
        assert a.weekday() < 5, "weekend used"
        assert a.hour >= 9
        assert (b.hour, b.minute) <= (18, 0)
        assert a >= now.astimezone(IST)
        if prev_end is not None:
            assert a >= prev_end
        prev_end = b


def test_friday_evening_mixed_tasks():
    now = _now(2026, 11, 27, 17, 10)
    tasks = [
        {"id": 1, "title": "Call", "duration_minutes": 30, "due_date": "2026-11-28"},
        {"id": 2, "title": "Groceries", "duration_minutes": 60, "due_date": "2026-11-28"},
        {"id": 3, "title": "DBMS", "duration_minutes": 60, "due_date": "2026-12-04"},
    ]
    res, blocks = _plan(now, tasks)
    _check_invariants(blocks, now)
    by_id = {t: (a, b) for t, a, b in blocks}
    if 1 in by_id:
        assert by_id[1][0].strftime("%H:%M") == "17:15"
        assert by_id[1][1].strftime("%H:%M") == "17:45"
    assert 2 not in by_id
    assert [u["task_id"] for u in res["unassigned"]].count(2) == 1
    a3 = by_id[3][0]
    assert a3.weekday() == 0 and a3.strftime("%H:%M") >= "09:00"


def test_friday_after_hours_goes_to_monday():
    now = _now(2026, 11, 27, 18, 30)
    tasks = [{"id": 1, "title": "T", "duration_minutes": 60, "due_date": "2026-12-04"}]
    _res, blocks = _plan(now, tasks)
    _check_invariants(blocks, now)
    assert len(blocks) == 1
    assert blocks[0][1].weekday() == 0
    assert blocks[0][1].strftime("%H:%M") == "09:00"


def test_saturday_goes_to_monday_nine():
    now = _now(2026, 11, 28, 10, 0)
    tasks = [{"id": 1, "title": "T", "duration_minutes": 45}]
    _res, blocks = _plan(now, tasks)
    assert blocks[0][1].weekday() == 0
    assert blocks[0][1].strftime("%H:%M") == "09:00"


def test_friday_early_starts_at_work_start():
    now = _now(2026, 11, 27, 8, 0)
    tasks = [{"id": 1, "title": "T", "duration_minutes": 30}]
    _res, blocks = _plan(now, tasks)
    assert blocks[0][1].day == 27
    assert blocks[0][1].strftime("%H:%M") == "09:00"


def test_empty_working_days_means_weekdays():
    now = _now(2026, 11, 28, 10, 0)
    tasks = [{"id": 1, "title": "T", "duration_minutes": 30}]
    _res, blocks = _plan(now, tasks, work_days=[])
    assert blocks[0][1].weekday() == 0


def test_no_overlap_many_tasks():
    now = _now(2026, 11, 27, 16, 40)
    tasks = [{"id": i, "title": f"T{i}", "duration_minutes": 60} for i in range(1, 9)]
    _res, blocks = _plan(now, tasks)
    _check_invariants(blocks, now)
    assert len(blocks) == 8
