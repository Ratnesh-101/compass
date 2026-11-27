"""Schedule answers: 'tomorrow' honesty, Asia/Kolkata times, contradiction scrub, Due column (no database).

Today is Friday 2026-11-27 in these tests.
"""

import time
from datetime import date

import pytest

import backend.agents.schedule_deterministic as sd

TODAY = date(2026, 11, 27)
TOMORROW = date(2026, 11, 28)

REAL_TASKS = {
    1: {"id": 1, "title": "Buy groceries", "due_date": "2026-11-28", "priority": "medium"},
    2: {
        "id": 2,
        "title": "Call the bank",
        "due_date": "2026-11-28",
        "due_at": "2026-11-28T11:30:00+00:00",
        "priority": "high",
    },
    3: {"id": 3, "title": "DBMS assignment", "due_date": "2026-12-04", "priority": "high"},
}


def _block(task_id, title, start, end):
    return {
        "task_id": task_id,
        "title": title,
        "scheduled_start": start,
        "scheduled_end": end,
        "start": start,
        "end": end,
    }


BLOCKS = [
    _block(1, "Buy groceries", "2026-11-27T09:00:00+00:00", "2026-11-27T10:00:00+00:00"),
    _block(2, "Call the bank", "2026-11-27T09:45:00+00:00", "2026-11-27T10:15:00+00:00"),
    _block(3, "DBMS assignment", "2026-11-30T04:00:00+00:00", "2026-11-30T06:00:00+00:00"),
]


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    if hasattr(sd, "extract_schedule_target_date"):
        real = sd.extract_schedule_target_date

        def fixed(query, base_date=None, **kwargs):
            return real(query, base_date or TODAY, **kwargs)

        monkeypatch.setattr(sd, "extract_schedule_target_date", fixed)


def _row(out, title):
    rows = [ln for ln in out.splitlines() if ln.startswith("|") and title in ln]
    assert rows, f"no table row for {title!r} in:\n{out}"
    return rows[0]


def _tomorrow_answer(blocks, tasks=REAL_TASKS, committed=False):
    return sd.patch_schedule_answer(
        "Here is your plan.", blocks, tasks, "What's on my schedule tomorrow?", committed
    )


# (1) tomorrow answer -------------------------------------------------------------


def test_tomorrow_lists_tasks_due_tomorrow_with_real_dates():
    out = _tomorrow_answer(BLOCKS)
    assert "Buy groceries" in out
    assert "Call the bank" in out
    assert "Nov 28" in out or "2026-11-28" in out


def test_tomorrow_does_not_list_dbms_under_tomorrow_heading():
    out = _tomorrow_answer(BLOCKS)
    assert "Buy groceries" in out and "Call the bank" in out
    assert "DBMS assignment" not in out  # due Dec 4, not tomorrow


def test_tomorrow_does_not_present_friday_blocks_as_tomorrows():
    out = _tomorrow_answer(BLOCKS)
    assert "tomorrow" in out.lower() or "Saturday" in out
    # Friday's proposed slots must never appear under tomorrow's answer
    assert "Fri Nov 27" not in out
    assert "Nothing is scheduled for Saturday, November 28 yet." in out


def test_tomorrow_nothing_scheduled_says_so_and_never_claims_saving():
    out = _tomorrow_answer([], tasks={})
    low = out.lower()
    assert "nothing" in low and "scheduled" in low
    for bad in ("saved to your calendar", "i saved", "i've saved", "added to your calendar", "scheduled for you"):
        assert bad not in low


def test_tomorrow_unsaved_plan_not_claimed_as_saved():
    out = _tomorrow_answer(BLOCKS).lower()
    for bad in ("saved to your calendar", "i saved", "i've saved", "added to your calendar"):
        assert bad not in out


# (2) plan table in Asia/Kolkata --------------------------------------------------


def test_plan_table_converts_block_times_to_kolkata_with_date():
    out = sd.build_deterministic_schedule_table(BLOCKS, REAL_TASKS)
    row = _row(out, "Buy groceries")
    assert "Fri Nov 27" in row
    assert "2:30" in row and "3:30 PM" in row
    assert "09:00" not in row
    dbms = _row(out, "DBMS assignment")
    assert "Mon Nov 30" in dbms
    assert "9:30-11:30 AM" in dbms


def test_plan_heading_range_covers_first_and_last_block_dates():
    out = sd.build_deterministic_schedule_table(BLOCKS, REAL_TASKS)
    heading = next(ln for ln in out.splitlines() if ln.lstrip().startswith("#"))
    assert "Nov 27" in heading and "Nov 30" in heading


def test_plan_table_shows_no_date_the_blocks_do_not_have():
    out = sd.build_deterministic_schedule_table(BLOCKS, REAL_TASKS)
    slot_text = "\n".join(
        _row(out, t) for t in ("Buy groceries", "Call the bank", "DBMS assignment")
    )
    for stray in ("Nov 28", "Nov 29", "Dec 4"):
        # due dates may mention Nov 28 / Dec 4, but the slot cells may not
        for ln in slot_text.splitlines():
            cells = [c.strip() for c in ln.strip("|").split("|")]
            slot = cells[2]
            assert stray not in slot, f"slot cell shows unexpected date {stray}: {slot}"


# (3) contradicting-sentence scrub ------------------------------------------------


def _drop_fn():
    for name in ("drop_contradicting_sentences", "drop_contradicting_preference_sentences"):
        fn = getattr(sd, name, None)
        if callable(fn):
            return fn
    pytest.fail("drop_contradicting_sentences not found in backend.agents.schedule_deterministic")


_PREFS = {
    "work_start": "09:00",
    "work_end": "18:00",
    "break_minutes": 15,
    "preferred_start": "09:00",
    "preferred_end": "18:00",
    "preferred_work_start": "09:00",
    "preferred_work_end": "18:00",
    "break_duration_minutes": 15,
}


def test_contradicting_preference_sentence_dropped_and_fact_kept():
    fn = _drop_fn()
    text = (
        "All tasks fit within your preferred 08:00-16:00 working window, with 10-minute breaks. "
        "DBMS is due Dec 4."
    )
    out = fn(text, "", REAL_TASKS, allowed_facts=["09:00-18:00", "15-minute breaks"])
    assert "08:00-16:00" not in out
    assert "10-minute" not in out
    assert "DBMS is due Dec 4." in out


def test_matching_preference_sentence_is_kept():
    fn = _drop_fn()
    text = "All tasks fit within your preferred 09:00-18:00 working window, with 15-minute breaks."
    out = fn(text, "", [], allowed_facts=["09:00-18:00", "15-minute breaks"])
    assert "09:00-18:00" in out


# (4) Due column ------------------------------------------------------------------


def test_due_column_shows_kolkata_time_when_due_at_present():
    out = sd.build_deterministic_schedule_table(BLOCKS, REAL_TASKS)
    assert "Sat Nov 28, 5:00 PM" in _row(out, "Call the bank")


def test_due_column_date_only_when_due_at_absent():
    tasks = {k: dict(v) for k, v in REAL_TASKS.items()}
    tasks[2].pop("due_at")
    out = sd.build_deterministic_schedule_table(BLOCKS, tasks)
    row = _row(out, "Call the bank")
    assert "Nov 28" in row or "2026-11-28" in row
    assert "5:00 PM" not in row


# bounded time --------------------------------------------------------------------


def test_large_whitespace_input_is_fast():
    text = "a" + " " * 50000 + "b."
    start = time.perf_counter()
    sd.patch_schedule_answer(text, BLOCKS, REAL_TASKS, "What's on my schedule tomorrow?", False)
    fn = getattr(sd, "drop_contradicting_sentences", None)
    if callable(fn):
        fn(text, "", [], allowed_facts=["09:00-18:00"])
    assert time.perf_counter() - start < 1.0
