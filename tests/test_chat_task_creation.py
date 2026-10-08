import pytest
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock
from backend.router import (
    is_explicit_task_creation,
    _extract_task_creation_args,
    _parse_natural_date,
    route_message,
)
from backend.persona import format_tool_response


def test_is_explicit_task_creation():
    """Verify various phrasing variations are recognized as task/deadline creations."""
    assert is_explicit_task_creation("add a deadline on 10th of October 23:59 with the name complete python programming")
    assert is_explicit_task_creation("add a deadline on 10th October at 23:59 named Complete Python Programming")
    assert is_explicit_task_creation("create a task for tomorrow")
    assert is_explicit_task_creation("remind me to finish Python by October 10")
    assert is_explicit_task_creation("set a deadline for CS101 assignment due on Friday")
    assert is_explicit_task_creation("schedule a task named Review PR due tomorrow at 5pm")
    assert is_explicit_task_creation("new deadline: submit final demo video")
    
    # Conversational or general queries should NOT trigger explicit creation
    assert not is_explicit_task_creation("what are my deadlines?")
    assert not is_explicit_task_creation("hello compass")
    assert not is_explicit_task_creation("how do i prepare for a hackathon?")


def test_parse_natural_date_relative():
    """Verify relative date parsing: today, tomorrow, in N days, next Monday."""
    today = date(2026, 10, 7)  # Wednesday
    
    # Tomorrow
    d1, t24_1, t12_1 = _parse_natural_date("create a task for tomorrow", today=today)
    assert d1 == date(2026, 10, 8)
    
    # In 3 days
    d2, t24_2, t12_2 = _parse_natural_date("task in 3 days", today=today)
    assert d2 == date(2026, 10, 10)
    
    # Next Monday (days_ahead = (0 - 2) % 7 = 5 -> 2026-10-12)
    d3, t24_3, t12_3 = _parse_natural_date("due next monday", today=today)
    assert d3 == date(2026, 10, 12)


def test_parse_natural_date_explicit_and_time():
    """Verify explicit month/day parsing and time extraction."""
    today = date(2026, 10, 7)
    
    # 10th of October 23:59
    d1, t24_1, t12_1 = _parse_natural_date("10th of October 23:59", today=today)
    assert d1 == date(2026, 10, 10)
    assert t24_1 == "23:59"
    assert "11:59" in t12_1
    
    # October 10 at 5pm
    d2, t24_2, t12_2 = _parse_natural_date("October 10 at 5pm", today=today)
    assert d2 == date(2026, 10, 10)
    assert t24_2 == "17:00"
    assert t12_2 == "5 PM"


def test_parse_natural_date_never_past_year():
    """Verify that parsing dates without year or with stale years never returns a past year."""
    today = date(2026, 10, 7)
    
    # October 1st (already passed in 2026) -> should roll forward to 2027
    d1, _, _ = _parse_natural_date("October 1st", today=today)
    assert d1.year == 2027
    assert d1.month == 10
    assert d1.day == 1
    
    # Stale year (2024-10-31) -> clamped/forwarded to current or upcoming year
    d2, _, _ = _parse_natural_date("2024-10-31", today=today)
    assert d2.year >= 2026


def test_extract_task_creation_args_complete():
    """Test full extraction across representative user inputs."""
    # 1. Screenshot command
    args1 = _extract_task_creation_args("add a deadline on 10th of October 23:59 with the name complete python programming")
    assert args1["title"].lower() == "complete python programming"
    assert "2026-10-10" in args1["due_date"]
    assert "23:59" in args1["due_date"]
    assert args1["time_str"] == "11:59 PM" or "11:59" in args1["time_str"]
    
    # 2. Named parameter syntax
    args2 = _extract_task_creation_args("add a deadline on 10th October at 23:59 named Complete Python Programming")
    assert args2["title"] == "Complete Python Programming"
    assert "2026-10-10" in args2["due_date"]
    
    # 3. Remind me to ...
    args3 = _extract_task_creation_args("remind me to finish Python by October 10")
    assert "finish python" in args3["title"].lower()
    assert "2026-10-10" in args3["due_date"]
    
    # 4. Domain inference: coursework
    args4 = _extract_task_creation_args("add a task: study for algorithms exam due 2026-10-15 domain coursework")
    assert "study for algorithms exam" in args4["title"].lower()
    assert args4["domain"] == "coursework"
    assert "2026-10-15" in args4["due_date"]


@pytest.mark.asyncio
async def test_route_message_task_creation_flow():
    """Verify route_message routes natural-language task creation commands to add_task."""
    # Test screenshot command
    skill, args, text = await route_message("add a deadline on 10th of October 23:59 with the name complete python programming")
    assert skill == "add_task"
    assert args["title"].lower() == "complete python programming"
    assert "2026-10-10" in args["due_date"]
    assert text == ""


@pytest.mark.asyncio
async def test_route_message_missing_title_prompts_user():
    """Verify that when a user requests a task with no title, Compass asks for a title instead of generic fallback."""
    skill, args, text = await route_message("create a task for tomorrow")
    assert skill is None
    assert args is None
    assert "What would you like to name this task?" in text


def test_format_tool_response_add_task():
    """Verify clean confirmation message formatting for add_task."""
    resp = format_tool_response("add_task", {
        "title": "Complete Python Programming",
        "due_date": "2026-10-10",
        "domain": "code",
        "time_str": "11:59 PM"
    })
    assert "Done! Added task 'Complete Python Programming'" in resp
    assert "Due 2026-10-10 at 11:59 PM" in resp
    assert "(code)" in resp
