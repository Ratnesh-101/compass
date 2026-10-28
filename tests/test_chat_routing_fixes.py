"""Natural-phrase routing and date/title extraction fixes."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.router_helpers import (
    PERSONAL_SCOPE_TRIGGERS,
    PUBLIC_EVENT_INDICATORS,
    _extract_task_creation_args,
    is_explicit_task_creation,
    parse_natural_due_date,
)


@pytest.mark.parametrize(
    "message",
    ["Don't get upset about the task", "We should address the deadline together", "track my tasks", "track all my deadlines"],
)
def test_substring_verbs_and_track_queries_are_not_task_creation(message):
    assert is_explicit_task_creation(message) is False


@pytest.mark.parametrize(
    "message",
    ["add a deadline for math homework", "set a reminder to call mom", "create a task called essay", "track a deadline for the hackathon"],
)
def test_real_creation_commands_still_work(message):
    assert is_explicit_task_creation(message) is True


@pytest.mark.parametrize(
    "message, title",
    [
        ("Remind me to turn in my homework by Friday", "turn in my homework"),
        ("remind me to check in with Bob tomorrow", "check in with Bob"),
        ("remind me to hand in the report on Monday", "hand in the report"),
        ("remind me to call mom in 3 days", "call mom"),
    ],
)
def test_phrasal_in_is_kept_in_the_title(message, title):
    assert _extract_task_creation_args(message)["title"].lower() == title.lower()


def test_leading_for_is_not_left_in_the_title():
    args = _extract_task_creation_args("Add a deadline tomorrow for Math Homework")
    assert args["title"].lower() == "math homework"


def test_day_after_tomorrow_is_two_days_out(monkeypatch):
    import backend.router_helpers as rh

    monkeypatch.setattr(rh, "_current_today", lambda: date(2026, 10, 28))
    iso, cleaned = parse_natural_due_date("submit report day after tomorrow")
    assert iso == (date(2026, 10, 28) + timedelta(days=2)).isoformat()
    assert "day after" not in cleaned.lower() and "tomorrow" not in cleaned.lower()
    iso, _ = parse_natural_due_date("submit report tomorrow")
    assert iso == (date(2026, 10, 28) + timedelta(days=1)).isoformat()


@pytest.mark.parametrize("message", ["When is the chemistry homework due?", "when is the exam"])
def test_coursework_questions_are_personal_not_public(message):
    msg_l = message.lower()
    assert any(i in msg_l for i in PUBLIC_EVENT_INDICATORS)
    assert any(p in msg_l for p in PERSONAL_SCOPE_TRIGGERS)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["When is the chemistry homework due?", "when is the exam"])
async def test_coursework_questions_do_not_go_to_web_search(message):
    from backend.router import route_message

    skill, _args, _text = await route_message(message)
    assert skill != "search_web"


@pytest.mark.asyncio
async def test_public_event_questions_still_go_to_web_search():
    from backend.router import route_message

    skill, _args, _text = await route_message("When is the Nebius hackathon deadline?")
    assert skill == "search_web"
