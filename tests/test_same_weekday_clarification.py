"""A bare weekday equal to today's weekday means next week; the intake card must say so."""

from datetime import date, datetime, timezone

import pytest

from backend.services.task_intake import _line, _preview_items
from backend.services.task_intake_parse import IntakeItem, ParsedIntake

TZ = "Asia/Kolkata"
NOW = datetime(2026, 11, 27, 6, 0, tzinfo=timezone.utc)  # Friday 11:30 IST
SUFFIX = ' (next Friday: say "today" for today)'


def _card(due_text: str):
    item = IntakeItem("DBMS assignment", "coursework", "medium", None, due_text)
    it = _preview_items(ParsedIntake((item,), 1, ()), TZ, NOW)[0]
    return it, _line(1, it)


@pytest.mark.parametrize("text", ["due Friday", "due friday"])
def test_bare_same_weekday_is_next_week_with_suffix(text):
    it, line = _card(text)
    assert it["due_date"] == date(2026, 12, 4).isoformat()
    assert line.endswith(SUFFIX)


@pytest.mark.parametrize("text,day", [
    ("due Monday", date(2026, 11, 30)),
    ("due today", date(2026, 11, 27)),
    ("due this Friday", date(2026, 11, 27)),
    ("due next Friday", date(2026, 12, 4)),
])
def test_no_suffix_otherwise(text, day):
    it, line = _card(text)
    assert it["due_date"] == day.isoformat()
    assert "say \"today\"" not in line
