"""Single-day schedule questions return only the deterministic answer."""

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.agents.schedule_deterministic import patch_schedule_answer, scrub_internal_agent_text

TZ = "Asia/Kolkata"
CANNED = "I haven't changed anything yet, so I won't say I did anything."
FOOTNOTE = "\\*Durations are based on the earlier proposal (you can adjust them if needed)."
OFFER = "Keep the Friday plan as-is?"
MODEL_PROSE = f"Here is your day.\n\n{CANNED}\n\n{FOOTNOTE}\n\n{OFFER}"


def _tomorrow():
    return datetime.now(ZoneInfo(TZ)).date() + timedelta(days=1)


def _tasks():
    d = _tomorrow()
    due_at = datetime(d.year, d.month, d.day, 17, 0, tzinfo=ZoneInfo(TZ))
    return {
        1: {"id": 1, "title": "Buy groceries", "due_date": d.isoformat(), "priority": "medium"},
        2: {"id": 2, "title": "Call the bank", "due_at": due_at, "priority": "high"},
    }


def test_tomorrow_answer_is_deterministic_only():
    out = patch_schedule_answer(
        MODEL_PROSE, [], _tasks(), "What's on my schedule tomorrow?", committed=False, tz_name=TZ
    )
    assert "Buy groceries" in out
    assert "Call the bank" in out
    assert "Due tomorrow" in out
    assert "haven't changed anything" not in out
    assert "Durations are based" not in out
    assert "\\*" not in out
    assert "Keep the Friday plan" not in out


def test_other_day_blocks_get_honest_week_sentence():
    d = _tomorrow() + timedelta(days=3)
    block = {
        "task_id": 1,
        "scheduled_start": datetime(d.year, d.month, d.day, 10, 0, tzinfo=ZoneInfo(TZ)).isoformat(),
        "scheduled_end": datetime(d.year, d.month, d.day, 11, 0, tzinfo=ZoneInfo(TZ)).isoformat(),
    }
    out = patch_schedule_answer(MODEL_PROSE, [block], _tasks(), "what is on tomorrow", tz_name=TZ)
    assert 'Nothing is saved yet. Say "plan my week" to see a proposal.' in out
    assert "Keep the Friday plan" not in out


def test_empty_day_line():
    out = patch_schedule_answer(MODEL_PROSE, [], {}, "schedule tomorrow", tz_name=TZ)
    assert "Nothing is scheduled for" in out
    assert "haven't changed" not in out


def test_plan_my_week_keeps_table():
    d = _tomorrow()
    block = {
        "task_id": 1,
        "scheduled_start": datetime(d.year, d.month, d.day, 10, 0, tzinfo=ZoneInfo(TZ)).isoformat(),
        "scheduled_end": datetime(d.year, d.month, d.day, 11, 0, tzinfo=ZoneInfo(TZ)).isoformat(),
    }
    out = patch_schedule_answer("Plan below.", [block], _tasks(), "plan my week", tz_name=TZ)
    assert "| Task | Domain | Scheduled Slot | Due Date | Priority |" in out
    assert "Buy groceries" in out
    assert "Nothing is saved yet." in out


def test_scrub_removes_escaped_footnote_keeps_text():
    text = "Normal line.\n\\*Durations are based on x.\n  \\* another\nLast line."
    out = scrub_internal_agent_text(text)
    assert "\\*" not in out
    assert "Normal line." in out and "Last line." in out
    assert scrub_internal_agent_text(out) == out


def test_scrub_large_whitespace_is_fast():
    start = time.perf_counter()
    scrub_internal_agent_text(" " * 50000 + "\\*x\n" + " " * 50000 + "ok")
    assert time.perf_counter() - start < 2.0
