"""
Compass — Proactive Cognitive Conflict Detection Tests.

Verifies:
1. Deterministic effort estimation from duration_minutes, textual cues, and heuristic fallbacks.
2. Cross-domain collision detection (e.g. Hackathon sprint vs Coursework lab/exam).
3. Deterministic capacity arithmetic (demand vs capacity, overcommit hours & percentage).
4. Actionable arbitration proposals (rescheduling conflicting tasks to protect focus).
5. Clean pass when within capacity and no cross-domain clashes.
"""

from datetime import date, datetime, timezone
import pytest

from backend.services.scheduler import (
    estimate_task_effort_hours,
    check_proactive_cognitive_conflicts,
)


def test_estimate_task_effort_hours():
    """Verify effort extraction from duration_minutes, text hints, and heuristics."""
    # 1. Direct duration_minutes
    t1 = {"title": "Quick review", "duration_minutes": 90}
    assert estimate_task_effort_hours(t1) == 1.5

    # 2. Textual hour hints in title
    t2 = {"title": "36-hour Hackathon Sprint", "domain": "hackathon"}
    assert estimate_task_effort_hours(t2) == 36.0

    t3 = {"title": "OS Lab Report (8 hrs)", "domain": "coursework"}
    assert estimate_task_effort_hours(t3) == 8.0

    t4 = {"title": "Standup meeting (45 mins)", "domain": "general"}
    assert estimate_task_effort_hours(t4) == 0.75

    # 3. Fallback heuristic
    t5 = {"title": "Bug fix", "priority": "urgent", "domain": "hackathon"}
    # urgent = 4.0 * 1.25 = 5.0
    assert estimate_task_effort_hours(t5) == 5.0

    t6 = {"title": "Reading", "priority": "low", "domain": "general"}
    # low = 1.0 * 0.8 = 0.8
    assert estimate_task_effort_hours(t6) == 0.8


def test_cross_domain_weekend_collision_and_overcommit():
    """Verify detection when a 36-hour hackathon sprint collides with an 8-hour coursework lab."""
    # Sunday Oct 4, 2026
    target_sunday = "2026-10-04"

    proposed_hackathon_sprint = {
        "title": "36-hour Hackathon Sprint",
        "domain": "hackathon",
        "due_date": target_sunday,
        "priority": "urgent",
    }

    existing_tasks = [
        {
            "id": 101,
            "title": "CS 61C Lab 4: RISC-V Pipeline",
            "domain": "coursework",
            "due_date": target_sunday,
            "priority": "urgent",
            "duration_minutes": 480,  # 8 hours
            "status": "open",
        },
        {
            "id": 102,
            "title": "Unrelated future task",
            "domain": "code",
            "due_date": "2026-10-20",
            "status": "open",
        },
    ]

    conflict = check_proactive_cognitive_conflicts(
        proposed_task=proposed_hackathon_sprint,
        existing_tasks=existing_tasks,
        weekend_capacity_hours=16.0,  # 32h for the 2-day weekend
    )

    assert conflict is not None
    assert conflict["has_conflict"] is True
    assert conflict["is_weekend"] is True
    assert conflict["conflict_type"] == "cross_domain_capacity_overload"

    # Demand: 36h (sprint) + 8h (coursework) = 44h
    assert conflict["total_demand_hours"] == 44.0
    assert conflict["capacity_limit_hours"] == 32.0
    assert conflict["overcommit_hours"] == 12.0
    assert conflict["overcommit_pct"] == 138

    # Conflicting task details
    assert len(conflict["conflicting_cross_domain_tasks"]) == 1
    assert conflict["conflicting_cross_domain_tasks"][0]["title"] == "CS 61C Lab 4: RISC-V Pipeline"
    assert conflict["conflicting_cross_domain_tasks"][0]["domain"] == "coursework"

    # Verifiable human-readable arbitration advice
    alert_msg = conflict["alert_message"]
    assert "⚡ Cognitive Conflict Alert:" in alert_msg
    assert "Cross-Domain Collision:" in alert_msg
    assert "CS 61C Lab 4" in alert_msg
    assert "Capacity Math:" in alert_msg
    assert "44.0h against 32h" in alert_msg
    assert "138% load" in alert_msg
    assert "Suggested Arbitration:" in alert_msg
    assert "Propose shifting 'CS 61C Lab 4: RISC-V Pipeline'" in alert_msg


def test_weekday_capacity_overload():
    """Verify weekday capacity checking against 8-hour daily limit."""
    target_weekday = "2026-10-06"  # Tuesday

    proposed_task = {
        "title": "Deep Architecture Refactor (6 hrs)",
        "domain": "code",
        "due_date": target_weekday,
        "priority": "high",
    }

    existing_tasks = [
        {
            "id": 201,
            "title": "Distributed Systems Milestone (4 hrs)",
            "domain": "coursework",
            "due_date": target_weekday,
            "priority": "high",
            "status": "open",
        }
    ]

    conflict = check_proactive_cognitive_conflicts(
        proposed_task=proposed_task,
        existing_tasks=existing_tasks,
        daily_capacity_hours=8.0,
    )

    assert conflict is not None
    assert conflict["has_conflict"] is True
    assert conflict["is_weekend"] is False
    # 6h + 4h = 10h vs 8h limit
    assert conflict["total_demand_hours"] == 10.0
    assert conflict["capacity_limit_hours"] == 8.0
    assert conflict["overcommit_hours"] == 2.0
    assert conflict["overcommit_pct"] == 125


def test_clean_pass_no_conflict():
    """Verify that light tasks within capacity produce no conflict."""
    target_date = "2026-10-08"

    proposed_task = {
        "title": "Review pull request (30 mins)",
        "domain": "code",
        "due_date": target_date,
        "priority": "low",
    }

    existing_tasks = [
        {
            "id": 301,
            "title": "Light reading (1 hr)",
            "domain": "general",
            "due_date": target_date,
            "priority": "low",
            "status": "open",
        }
    ]

    conflict = check_proactive_cognitive_conflicts(
        proposed_task=proposed_task,
        existing_tasks=existing_tasks,
    )

    assert conflict is None


@pytest.mark.asyncio
async def test_handle_add_task_proactive_conflict_response():
    """Verify handle_add_task returns cognitive conflict warning and structured metadata."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from backend.skills.handlers.tasks import handle_add_task

    mock_conn = AsyncMock()
    # Mock list_tasks returning active coursework lab
    with patch("backend.memory.structured.list_tasks", new=AsyncMock(return_value=[
        {
            "id": 101,
            "title": "CS 61C Lab 4: RISC-V Pipeline",
            "domain": "coursework",
            "due_date": date(2026, 10, 4),
            "priority": "urgent",
            "duration_minutes": 480,
            "status": "open",
            "notes": None,
        }
    ])):
        with patch("backend.memory.structured.create_task", new=AsyncMock(return_value={
            "id": 202,
            "title": "36-hour Hackathon Sprint",
            "domain": "hackathon",
            "due_date": date(2026, 10, 4),
            "status": "open",
            "priority": "urgent",
            "notes": None,
        })):
            mock_pool = MagicMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

            res = await handle_add_task(
                {
                    "title": "36-hour Hackathon Sprint",
                    "domain": "hackathon",
                    "due_date": "2026-10-04",
                    "priority": "urgent",
                },
                pool=mock_pool,
            )

            assert "Added task #202" in res["response"]
            assert "Cognitive Conflict Alert" in res["response"]
            assert "Cross-Domain Collision" in res["response"]
            assert "CS 61C Lab 4" in res["response"]
            assert "cognitive_conflict" in res["data"]
            assert res["data"]["cognitive_conflict"]["has_conflict"] is True
            assert res["data"]["cognitive_conflict"]["total_demand_hours"] == 44.0

