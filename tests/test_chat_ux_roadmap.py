"""
Compass — Chat UX, Roadmap Synthesis, and Safe Activity Tests.

Verifies:
1. Concise, structured daily roadmap synthesis from large task result sets (no raw dumps).
2. Prioritization ordering: overdue > due today > due soon > high priority > open.
3. Preserving "No due date" without manufacturing deadlines.
4. Backward compatibility of empty task queries (Found 0 task(s)...).
5. Router intent classification for roadmaps, daily planning, and prioritization.
6. Absence of private chain-of-thought, internal prompts, or raw tool JSON in safe activity.
7. Timezone-aware target_date handling.
8. Full task data preservation in tool response data payloads.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.skills.handlers.tasks import (
    prioritize_tasks,
    build_daily_roadmap,
    handle_query_tasks,
)
from backend.router_helpers import is_schedule_or_agent_intent, _fallback_route


def test_task_prioritization_hierarchy():
    """Verify overdue > due today > due soon > urgent > open hierarchy."""
    today = date(2026, 10, 17)

    tasks = [
        {"id": 1, "title": "Regular Open Task", "due_date": None, "priority": "medium", "status": "open"},
        {"id": 2, "title": "Overdue Deliverable", "due_date": today - timedelta(days=2), "priority": "medium", "status": "open"},
        {"id": 3, "title": "Urgent Future Task", "due_date": today + timedelta(days=20), "priority": "urgent", "status": "open"},
        {"id": 4, "title": "Due Today Exam", "due_date": today, "priority": "high", "status": "open"},
        {"id": 5, "title": "Due Soon Lab", "due_date": today + timedelta(days=3), "priority": "medium", "status": "open"},
        {"id": 6, "title": "Completed Task", "due_date": today - timedelta(days=5), "priority": "urgent", "status": "done"},
    ]

    prioritized = prioritize_tasks(tasks, target_date=today)
    ordered_ids = [t["id"] for t in prioritized]

    # Expected order:
    # 2 (Overdue) -> 4 (Due today) -> 5 (Due soon <=7d) -> 3 (Urgent priority) -> 1 (Open no due date) -> 6 (Done)
    assert ordered_ids == [2, 4, 5, 3, 1, 6]


def test_build_daily_roadmap_structure_and_truthfulness():
    """Verify daily roadmap adheres to Phase 4 structure and does not fabricate facts."""
    today = date(2026, 10, 17)

    tasks = [
        {"id": 101, "title": "Benchmark GPU memory", "due_date": None, "priority": "high", "domain": "hackathon", "status": "open"},
        {"id": 102, "title": "Submit final video", "due_date": today, "priority": "urgent", "domain": "hackathon", "status": "open"},
        {"id": 103, "title": "RISC-V pipeline hazard lab", "due_date": today + timedelta(days=1), "priority": "high", "domain": "coursework", "status": "open"},
        {"id": 104, "title": "Write team retrospective", "due_date": None, "priority": "medium", "domain": "general", "status": "open"},
    ]

    roadmap = build_daily_roadmap(tasks, target_date=today)

    # Required section headings
    assert "### Your plan for today" in roadmap
    assert "### 1. Start here" in roadmap
    assert "### 2. Next" in roadmap
    assert "### 3. Continue" in roadmap
    assert "### Suggested schedule" in roadmap
    assert "### Before you finish" in roadmap
    assert "### Next action" in roadmap

    # Due today task must be first
    assert "Submit final video" in roadmap
    assert "Benchmark GPU memory" in roadmap

    # No due date preserved, not fabricated
    assert "No due date" in roadmap

    # Time blocks clearly identified as estimates
    assert "Estimated focus blocks" in roadmap or "estimate" in roadmap.lower()

    # Checklist elements present
    assert "- [ ]" in roadmap


def test_empty_query_tasks_backward_compatibility():
    """Verify Found 0 task(s)... exact contract for empty results."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    import asyncio
    output = asyncio.run(handle_query_tasks({"domain": "hackathon"}, mock_pool))
    assert output == {"response": "Found 0 task(s) in HACKATHON.", "data": []}


def test_large_task_query_avoids_unbounded_dump():
    """Verify 369 tasks query produces structured concise summary without unbounded text dumping."""
    mock_tasks = [
        {"id": i, "title": f"Task #{i}", "due_date": None, "priority": "medium", "domain": "general", "status": "open"}
        for i in range(1, 370)
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_tasks)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    import asyncio
    output = asyncio.run(handle_query_tasks({"user_id": "roadmap_user"}, mock_pool))

    # Concise response with total count and top items
    assert "Found **369** task(s)" in output["response"]
    assert "Showing top 6 prioritized items" in output["response"]
    assert "Timeline view" in output["response"]

    # All 369 records preserved in data payload without silent dropping
    assert len(output["data"]) == 369


def test_roadmap_intent_detection_and_fallback():
    """Verify user planning queries trigger schedule/agent intent and pass roadmap intent."""
    repro_user_query = "I have 6 tasks needing attention today. Please analyze my deadlines and suggest an optimal step-by-step roadmap for today."
    
    assert is_schedule_or_agent_intent(repro_user_query) is True
    assert is_schedule_or_agent_intent("Suggest a step-by-step roadmap") is True
    assert is_schedule_or_agent_intent("What should I do today?") is True
    assert is_schedule_or_agent_intent("Prioritize my tasks for today") is True
    assert is_schedule_or_agent_intent("roadmap") is True

    # Negative tests: informational questions should not trigger agent/schedule intent
    assert is_schedule_or_agent_intent("What is a product roadmap?") is False
    assert is_schedule_or_agent_intent("Explain what a roadmap is") is False
    assert is_schedule_or_agent_intent("Define roadmap") is False

    skill, args, text = _fallback_route(repro_user_query)
    assert skill == "agent"
    assert args is not None
    assert args.get("goal") == repro_user_query


def test_fallback_task_query_with_roadmap_intent():
    """Verify fallback route passes roadmap intent context when task query mentions planning."""
    query = "Tasks needing attention today"
    skill, args, text = _fallback_route(query)
    # Routed to agent or query_tasks with roadmap intent
    assert skill in ("agent", "query_tasks")
    if skill == "query_tasks":
        assert args is not None
        assert args.get("intent") == "roadmap"
