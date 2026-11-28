"""Chat prompt context (dates, open tasks, capabilities) and current-facts web routing."""
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from backend.router_helpers import is_current_facts_question
from backend.services.chat_stream import (
    CAPABILITIES_PROMPT,
    build_calendar_line,
    build_chat_system_prompt,
    build_date_header,
    build_open_tasks_context,
    check_weekday_date_pairs,
    correct_weekday_date_pairs,
)
from backend.services.chat_stream_extras import (
    CURRENT_FACTS_OFFLINE_PREFIX,
    run_web_fallback,
    should_search_web,
)

TODAY = date(2026, 11, 28)  # a Saturday
NOW = datetime(2026, 11, 28, 4, 0, tzinfo=timezone.utc)  # 09:30 in Asia/Kolkata


def test_prompt_starts_with_today_line_and_calendar():
    prompt = build_chat_system_prompt("BASE", NOW, "Asia/Kolkata")
    assert prompt.startswith(
        "Today is Saturday 28 November 2026, the user's time zone is Asia/Kolkata; current local time 09:30."
    )
    assert "Sat 28 Nov, Sun 29 Nov, Mon 30 Nov" in prompt
    assert "Fri 4 Dec" in prompt and "Fri 11 Dec" in prompt
    assert "never in UTC" in prompt and "never compute weekdays yourself" in prompt


def test_calendar_has_fourteen_days():
    assert len(build_calendar_line(TODAY).split(", ")) == 14


def test_invalid_timezone_falls_back_to_kolkata():
    assert "Asia/Kolkata" in build_date_header(NOW, "Not/AZone")
    assert "Asia/Kolkata" in build_date_header(NOW, None)


def test_weekday_check_flags_wrong_and_accepts_right():
    assert check_weekday_date_pairs("See you Friday, Nov 29.", TODAY, "Asia/Kolkata") == ["Friday, Nov 29"]
    assert check_weekday_date_pairs("See you Friday, Dec 4.", TODAY, "Asia/Kolkata") == []
    assert check_weekday_date_pairs("Friday 29 Nov", TODAY) == ["Friday 29 Nov"]
    assert check_weekday_date_pairs("Friday (Nov 29)", TODAY) == ["Friday (Nov 29)"]
    assert check_weekday_date_pairs("Sun 29 Nov and Fri 4 Dec", TODAY) == []


def test_corrector_rewrites_weekday_in_place():
    out = correct_weekday_date_pairs("Due Friday, Nov 29 and Friday, Dec 4; also Fri 29 Nov.", TODAY)
    assert out == "Due Sunday, Nov 29 and Friday, Dec 4; also Sun 29 Nov."


def test_done_tasks_absent_from_task_context():
    rows = [
        {"title": "Open one", "domain": "x", "due_date": None, "status": "pending", "priority": "high"},
        {"title": "Finished one", "domain": "x", "due_date": None, "status": "done", "priority": "low"},
        {"title": "Completed one", "domain": "x", "due_date": None, "status": "completed", "priority": "low"},
    ]
    ctx = build_open_tasks_context(rows)
    assert "Open one" in ctx and "status: pending" in ctx
    assert "Finished one" not in ctx and "Completed one" not in ctx


def test_prompt_contains_cannot_do_text():
    prompt = build_chat_system_prompt("BASE", NOW, "Asia/Kolkata")
    assert "CANNOT DO" in prompt and "CAN DO" in prompt
    assert "I can't do that in Compass. What I can do instead:" in prompt
    assert "book travel" in CAPABILITIES_PROMPT
    assert "Confirm all done" in prompt
    assert "never treat done tasks as pending" in prompt.lower()


@pytest.mark.parametrize("msg", [
    "what is the latest stable version of Python?",
    "who won the match today",
    "current price of bitcoin",
])
def test_current_facts_true(msg):
    assert is_current_facts_question(msg)


@pytest.mark.parametrize("msg", [
    "what is due this week",
    "plan my week",
    "what should I do first today",
    "show my tasks for today",
    "hello there",
])
def test_current_facts_false(msg):
    assert not is_current_facts_question(msg)


def test_should_search_web_requires_tavily():
    with patch("backend.services.tavily.tavily_available", return_value=True):
        assert should_search_web("what is the latest stable version of Python?")
        assert not should_search_web("what is due this week")
    with patch("backend.services.tavily.tavily_available", return_value=False):
        assert not should_search_web("what is the latest stable version of Python?")


@pytest.mark.asyncio
async def test_web_fallback_cites_sources_and_checked_line():
    res = {"success": True, "response": "Python 3.14 is current.",
           "data": {"citations": [{"title": "Python", "url": "https://python.org/downloads"}]}}

    async def fake_search(args, pool):
        return res

    with patch("backend.services.tavily.tavily_available", return_value=True), \
         patch("backend.skills.handlers.web.handle_search_web", fake_search):
        out = await run_web_fallback("what is the latest version of Python", None)
    assert "[Python](https://python.org/downloads)" in out["response"]
    assert "Checked online on " in out["response"]


@pytest.mark.asyncio
async def test_web_fallback_none_when_tavily_unavailable():
    with patch("backend.services.tavily.tavily_available", return_value=False):
        assert await run_web_fallback("what is the latest version of Python", None) is None
    assert CURRENT_FACTS_OFFLINE_PREFIX == "I can't check online right now, so this may be out of date:"
