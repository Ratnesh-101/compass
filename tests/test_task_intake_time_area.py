"""Time and area (domain) extraction for task intake, using only the pure parsers (no LLM, no DB)."""

from datetime import timedelta

import pytest

from backend.router_helpers import _current_today, _extract_task_creation_args
from backend.services.task_intake_llm import TaskDraft, _to_items

SENTENCE = (
    "Add these tasks: Buy groceries tomorrow (general) and "
    "DBMS assignment due Friday (coursework, high priority)"
)


def _time_of(args: dict) -> str | None:
    """Normalised HH:MM from due_date ('YYYY-MM-DD HH:MM') or the 12h time_str, else None."""
    due = args.get("due_date") or ""
    if " " in due:
        return due.split(" ", 1)[1][:5]
    ts = args.get("time_str")
    if not ts:
        return None
    clock, _, ampm = ts.partition(" ")
    hh, _, mm = clock.partition(":")
    h = int(hh) % 12 + (12 if ampm.upper() == "PM" else 0)
    return f"{h:02d}:{mm or '00'}"


def test_typo_message_gets_tomorrow_and_5pm():
    args = _extract_task_creation_args("rmind me submit dbms lab tmrw 5")
    tomorrow = (_current_today() + timedelta(days=1)).isoformat()
    assert str(args.get("due_date", "")).startswith(tomorrow), args
    assert _time_of(args) == "17:00", args


@pytest.mark.parametrize(
    "message,expected",
    [
        ("submit report tomorrow 9am", "09:00"),
        ("meeting friday at 14:30", "14:30"),
    ],
)
def test_explicit_times_are_kept(message, expected):
    args = _extract_task_creation_args(message)
    assert _time_of(args) == expected, args


@pytest.mark.parametrize(
    "message",
    ["buy 5 apples tomorrow", "read chapter 5"],
)
def test_bare_numbers_are_not_times(message):
    args = _extract_task_creation_args(message)
    assert _time_of(args) is None, args
    assert "time_str" not in args, args


def test_sentence_clauses_get_their_own_area_and_priority():
    body = SENTENCE.split(":", 1)[1].strip()
    first, second = (p.strip() for p in body.split(" and ", 1))
    a = _extract_task_creation_args(first)
    b = _extract_task_creation_args(second)
    assert a["domain"] == "general", a
    assert b["domain"] == "coursework", b
    assert b.get("priority") == "high", b


def test_sentence_drafts_keep_area_through_item_conversion():
    drafts = [
        TaskDraft(title="Buy groceries", domain="general", due_text="tomorrow"),
        TaskDraft(title="DBMS assignment", domain="coursework", priority="high", due_text="Friday"),
    ]
    items = _to_items(drafts, SENTENCE)
    assert [i.domain for i in items] == ["general", "coursework"], items
    assert items[1].priority == "high", items
