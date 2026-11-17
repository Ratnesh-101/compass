"""N-004: relative-date arithmetic ("next <weekday>", "this <weekday>", tomorrow, in N days).

NOT RUN when written (the author had no shell). Pure functions only; no database needed.

Rules under test (backend/services/task_dates.py):
  next <weekday> = first occurrence strictly after today
  this <weekday> = upcoming occurrence, today included
  bare <weekday> = same as next
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.router_helpers import _parse_natural_date
from backend.services.task_dates import (
    WEEKDAY_INDEX,
    reconcile_due_date,
    relative_dates,
    weekday_date,
    weekday_label,
)
from backend.services.task_time import local_today, resolve_due

IST = "Asia/Kolkata"
MONDAY = date(2026, 11, 16)  # the day N-004 was reported
FULL_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _expected_next(today: date, weekday: int) -> date:
    for delta in range(1, 8):  # strictly after today
        cand = today + timedelta(days=delta)
        if cand.weekday() == weekday:
            return cand
    raise AssertionError("unreachable")


def _expected_this(today: date, weekday: int) -> date:
    for delta in range(0, 7):  # today included
        cand = today + timedelta(days=delta)
        if cand.weekday() == weekday:
            return cand
    raise AssertionError("unreachable")


def test_reported_case_next_wednesday_on_monday_is_the_18th_not_the_19th():
    got, _, _ = _parse_natural_date("remind me to finish my slides by next wednesday", today=MONDAY)
    assert got == date(2026, 11, 18)
    assert got.strftime("%a") == "Wed"
    assert got != date(2026, 11, 19)  # a Thursday, the bug as reported


@pytest.mark.parametrize("offset", range(7))  # every weekday as "today"
@pytest.mark.parametrize("name", FULL_NAMES)  # every weekday as the target
def test_next_this_and_bare_weekday_for_every_pair(offset, name):
    today = MONDAY + timedelta(days=offset)
    target = WEEKDAY_INDEX[name]
    assert weekday_date(today, target, "next") == _expected_next(today, target)
    assert weekday_date(today, target, "this") == _expected_this(today, target)
    assert weekday_date(today, target, None) == _expected_next(today, target)
    # the same through the text parser used by the chat path
    assert _parse_natural_date(f"due next {name}", today=today)[0] == _expected_next(today, target)
    assert _parse_natural_date(f"due this {name}", today=today)[0] == _expected_this(today, target)
    assert _parse_natural_date(f"due {name}", today=today)[0] == _expected_next(today, target)


def test_next_weekday_is_never_today_and_never_more_than_seven_days_away():
    for offset in range(14):
        today = MONDAY + timedelta(days=offset)
        for target in range(7):
            d = weekday_date(today, target, "next")
            assert 1 <= (d - today).days <= 7 and d.weekday() == target


def test_first_weekday_in_the_text_wins_not_dictionary_order():
    # "monday" comes first in the weekday table, but the user said friday first.
    got, _, _ = _parse_natural_date("submit on friday, review again monday", today=MONDAY)
    assert got == date(2026, 11, 20)


RELATIVE_TABLE = [
    ("tomorrow", date(2026, 11, 17)),
    ("do it tomorrow", date(2026, 11, 17)),
    ("day after tomorrow", date(2026, 11, 18)),
    ("by the day after tomorrow", date(2026, 11, 18)),
    ("in 3 days", date(2026, 11, 19)),
    ("in 1 day", date(2026, 11, 17)),
    ("in 2 weeks", date(2026, 11, 30)),
    ("today", date(2026, 11, 16)),
    ("tonight", date(2026, 11, 16)),
]


@pytest.mark.parametrize("text,expected", RELATIVE_TABLE)
def test_relative_phrases_from_monday(text, expected):
    assert _parse_natural_date(text, today=MONDAY)[0] == expected
    assert relative_dates(text, MONDAY) == {expected}


def test_day_after_tomorrow_is_not_also_tomorrow():
    assert relative_dates("day after tomorrow", MONDAY) == {date(2026, 11, 18)}


# ---- reconcile_due_date: the model's date is replaced by the message's own phrase --------------------
def test_reconcile_replaces_the_models_wrong_weekday_arithmetic():
    msg = "remind me to finish my database presentation slides by next wednesday"
    assert reconcile_due_date(msg, date(2026, 11, 19), MONDAY) == date(2026, 11, 18)


def test_reconcile_fills_a_date_the_model_forgot():
    assert reconcile_due_date("add task buy milk tomorrow", None, MONDAY) == date(2026, 11, 17)


def test_reconcile_keeps_the_models_date_when_the_message_has_no_relative_phrase():
    assert reconcile_due_date("add task buy milk", date(2026, 12, 1), MONDAY) == date(2026, 12, 1)
    assert reconcile_due_date("add task buy milk", None, MONDAY) is None


def test_reconcile_does_not_guess_when_the_message_has_two_different_phrases():
    msg = "add task report, draft tomorrow and final on friday"
    assert reconcile_due_date(msg, date(2026, 11, 20), MONDAY) == date(2026, 11, 20)


def test_reconcile_leaves_explicit_calendar_dates_alone():
    for msg in (
        "submit friday 20 nov",
        "submit by 2026-11-20, a friday",
        "submit on nov 20, friday deadline",
    ):
        assert reconcile_due_date(msg, date(2026, 11, 20), MONDAY) == date(2026, 11, 20), msg


def test_reconcile_ignores_ordinary_words_that_look_like_abbreviations():
    # "sat", "sun", "mon" alone are not trusted as weekdays
    assert reconcile_due_date("I sat down and wrote the report", date(2026, 11, 20), MONDAY) == date(2026, 11, 20)
    assert reconcile_due_date("watch the sun set", None, MONDAY) is None


# ---- timezone and midnight edges --------------------------------------------------------------------
# 2026-11-15 20:00 UTC is 01:30 on Monday 16 Nov in Asia/Kolkata but still Sunday 15 Nov in UTC.
LATE_SUNDAY_UTC = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)


def test_local_today_follows_the_users_zone_across_midnight():
    assert local_today(IST, LATE_SUNDAY_UTC) == date(2026, 11, 16)
    assert local_today("UTC", LATE_SUNDAY_UTC) == date(2026, 11, 15)


def test_tomorrow_across_the_midnight_edge_differs_by_zone():
    assert resolve_due("tomorrow", IST, LATE_SUNDAY_UTC).due_date == date(2026, 11, 17)
    assert resolve_due("tomorrow", "UTC", LATE_SUNDAY_UTC).due_date == date(2026, 11, 16)


def test_next_wednesday_in_kolkata_just_after_midnight_monday():
    assert resolve_due("next wednesday", IST, LATE_SUNDAY_UTC).due_date == date(2026, 11, 18)


def test_next_monday_on_a_monday_in_kolkata_is_a_week_away_but_utc_sunday_is_tomorrow():
    assert resolve_due("next monday", IST, LATE_SUNDAY_UTC).due_date == date(2026, 11, 23)
    assert resolve_due("next monday", "UTC", LATE_SUNDAY_UTC).due_date == date(2026, 11, 16)


def test_just_before_midnight_in_kolkata_is_still_the_previous_day():
    # 18:29 UTC = 23:59 IST on Sunday 15 Nov
    now = datetime(2026, 11, 15, 18, 29, tzinfo=timezone.utc)
    assert local_today(IST, now) == date(2026, 11, 15)
    assert resolve_due("tomorrow", IST, now).due_date == date(2026, 11, 16)


def test_resolved_label_carries_the_weekday():
    label = resolve_due("next wednesday", IST, LATE_SUNDAY_UTC).label
    assert label.startswith("Wed Nov 18")


def test_weekday_label_format():
    assert weekday_label(date(2026, 11, 18)) == "Wed, 18 Nov 2026"
    assert weekday_label(None) == ""
