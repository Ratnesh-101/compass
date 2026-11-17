"""Deterministic relative-date arithmetic for chat task intake (N-004).

Weekday rules, in one place so every caller agrees:

* ``next <weekday>``: the first occurrence strictly after today ("next Wednesday" on Monday 16 Nov
  is Wednesday 18 Nov; "next Monday" on a Monday is 7 days away).
* ``this <weekday>``: the upcoming occurrence, today included.
* bare ``<weekday>``: the next occurrence strictly after today (same as ``next``).

The model's own date arithmetic is not trusted for these phrases: ``reconcile_due_date`` replaces a
model-supplied date with the deterministic one when the user's message contains exactly one
unambiguous relative phrase.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

WEEKDAY_INDEX = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
# Abbreviations that are also ordinary English words ("I sat down", "the sun"); never trusted on their own.
_AMBIGUOUS_ABBREVIATIONS = frozenset({"mon", "sat", "sun"})

_NAMES = sorted(WEEKDAY_INDEX, key=len, reverse=True)
_WEEKDAY_RX = re.compile(r"\b(?:(next|this)\s+)?(" + "|".join(_NAMES) + r")\b", re.IGNORECASE)
_DAY_AFTER_TOMORROW = re.compile(r"\bday\s+after\s+tomorrow\b", re.IGNORECASE)
_TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
_TODAY = re.compile(r"\b(?:today|tonight)\b", re.IGNORECASE)
_IN_DAYS = re.compile(r"\bin\s+(\d{1,3})\s+days?\b", re.IGNORECASE)
_IN_WEEKS = re.compile(r"\bin\s+(\d{1,2})\s+weeks?\b", re.IGNORECASE)
_MONTHS = (
    "jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    "sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
# An explicit calendar date in the message means the weekday word is probably a label, not the due date.
_EXPLICIT_DATE = re.compile(
    rf"\b\d{{4}}-\d{{1,2}}-\d{{1,2}}\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\b"
    rf"|\b(?:{_MONTHS})\s+\d{{1,2}}\b|\b\d{{1,2}}[/.]\d{{1,2}}(?:[/.]\d{{2,4}})?\b",
    re.IGNORECASE,
)


def weekday_date(today: date, weekday: int, qualifier: Optional[str] = None) -> date:
    """Date of ``weekday`` (0=Monday) relative to ``today`` using the rules in the module docstring."""
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0 and (qualifier or "").lower() != "this":
        ahead = 7
    return today + timedelta(days=ahead)


def find_weekday_dates(text: str, today: date, *, allow_ambiguous: bool = True) -> list[date]:
    """Every weekday phrase in ``text``, in order of appearance, resolved against ``today``."""
    out: list[date] = []
    for m in _WEEKDAY_RX.finditer(text or ""):
        name = m.group(2).lower()
        if not allow_ambiguous and name in _AMBIGUOUS_ABBREVIATIONS:
            continue
        out.append(weekday_date(today, WEEKDAY_INDEX[name], m.group(1)))
    return out


def first_weekday_date(text: str, today: date) -> Optional[date]:
    """The weekday phrase that appears first in ``text`` (not first in dictionary order)."""
    found = find_weekday_dates(text, today)
    return found[0] if found else None


def relative_dates(text: str, today: date) -> set[date]:
    """Distinct dates named by relative phrases (today, tomorrow, in N days, weekdays) in ``text``."""
    msg = text or ""
    found: set[date] = set()
    if _DAY_AFTER_TOMORROW.search(msg):
        found.add(today + timedelta(days=2))
        msg = _DAY_AFTER_TOMORROW.sub(" ", msg)
    if _TOMORROW.search(msg):
        found.add(today + timedelta(days=1))
    if _TODAY.search(msg):
        found.add(today)
    for m in _IN_DAYS.finditer(msg):
        found.add(today + timedelta(days=int(m.group(1))))
    for m in _IN_WEEKS.finditer(msg):
        found.add(today + timedelta(days=7 * int(m.group(1))))
    found.update(find_weekday_dates(msg, today, allow_ambiguous=False))
    return found


def reconcile_due_date(message: str, model_date: Optional[date], today: date) -> Optional[date]:
    """The due date to store: the message's own relative phrase wins over the model's arithmetic.

    Returns ``model_date`` unchanged when the message has no relative phrase, has several different
    ones, or also contains an explicit calendar date (nothing is guessed in those cases).
    """
    if not message or _EXPLICIT_DATE.search(message):
        return model_date
    dates = relative_dates(message, today)
    if len(dates) == 1:
        return next(iter(dates))
    return model_date


def weekday_label(day: Optional[date]) -> str:
    """'Wed, 18 Nov 2026' for confirmations; '' when there is no date."""
    return f"{day.strftime('%a')}, {day.day} {day.strftime('%b %Y')}" if day else ""
