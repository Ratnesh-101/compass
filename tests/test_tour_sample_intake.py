"""The dashboard "60-second tour" pastes a sample week; the deterministic parser must read it with no model call.

The message below is the same literal that frontend/tests/tourSample.test.mjs pins for 17 Nov 2026.
"""

from datetime import date, datetime, timezone

from backend.services.task_intake_parse import MAX_ITEMS, parse_task_list
from backend.services.task_intent import is_intake_intent
from backend.services.task_time import resolve_due

SAMPLE_WEEK = "\n".join([
    "Add these 8 tasks to my deadlines:",
    "| Task | Domain | Priority | Duration | Due |",
    "| --- | --- | --- | --- | --- |",
    "| Operating Systems assignment | coursework | high | 4h | 2026-11-19 |",
    "| Computer Networks lab report | coursework | medium | 3h | 2026-11-21 |",
    "| Database Systems midterm revision | coursework | high | 5h | 2026-11-23 |",
    "| Hackathon project proposal | hackathon | high | 3h | 2026-11-20 |",
    "| Hackathon demo video | hackathon | medium | 4h | 2026-11-24 |",
    "| Hackathon final submission | hackathon | urgent | 3h | 2026-11-26 |",
    "| Fix login bug in portfolio site | code | medium | 2h | 2026-11-18 |",
    "| Write unit tests for the API | code | low | 2h | 2026-11-22 |",
])


def test_tour_sample_week_is_parsed_without_a_model_call():
    parsed = parse_task_list(SAMPLE_WEEK)
    assert parsed is not None
    assert len(parsed.items) == 8 <= MAX_ITEMS
    assert parsed.skipped == () and parsed.truncated is False
    assert is_intake_intent(SAMPLE_WEEK)
    domains = [i.domain for i in parsed.items]
    assert [domains.count(d) for d in ("coursework", "hackathon", "code")] == [3, 3, 2]
    assert [i.priority for i in parsed.items] == ["high", "medium", "high", "high", "medium", "urgent", "medium", "low"]
    assert sum(i.duration_minutes for i in parsed.items) == 26 * 60
    assert all(i.due_text.startswith("2026-11-") for i in parsed.items)


def test_tour_sample_due_dates_resolve_to_the_calendar_day():
    parsed = parse_task_list(SAMPLE_WEEK)
    now = datetime(2026, 11, 17, 4, 0, tzinfo=timezone.utc)
    days = sorted(resolve_due(i.due_text, "Asia/Kolkata", now_utc=now).due_date for i in parsed.items)
    assert days[0] == date(2026, 11, 18) and days[-1] == date(2026, 11, 26)
    assert all(resolve_due(i.due_text, "Asia/Kolkata", now_utc=now).unparsed_text is None for i in parsed.items)
