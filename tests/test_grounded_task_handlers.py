"""
Compass — Regression Tests for Grounded Task Handlers and Honest Conflict Detection.

Covers the 10 data-grounding requirements:
1. Single matching task produces a response containing its actual title.
2. Multiple matching tasks produce a readable, grounded summary.
3. Actual deadline is reflected correctly.
4. Conflicting deadlines are explicitly identified without arbitrary resolution.
5. Different tasks with different deadlines are not incorrectly described as a conflict.
6. Empty results produce a truthful no-results response.
7. Missing optional fields do not cause crashes or invented details.
8. Large result sets are summarized concisely without dumping the workspace.
9. Tool execution failures are reported as failures, not successful retrievals.
10. Existing task mutations and confirmation gates remain intact.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.skills.handlers.tasks import (
    handle_query_coursework_tasks,
    handle_get_hackathon_deadlines,
    handle_query_tasks,
    detect_deadline_discrepancies,
    format_conflict_discrepancy,
)


def _create_mock_pool(mock_tasks):
    """Helper to create an async mock pool returning mock_tasks."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=mock_tasks)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_pool


def _create_failing_pool(error_message="Database connection terminated"):
    """Helper to create an async mock pool that raises an error."""
    mock_pool = MagicMock()
    mock_pool.acquire.side_effect = Exception(error_message)
    return mock_pool


# ---------------------------------------------------------------------------
# Requirement 1: Single matching task contains actual title
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_task_contains_actual_title():
    fixtures = [
        {
            "id": 41,
            "title": "Logisim ALU Arithmetic Core Lab",
            "domain": "coursework",
            "due_date": "2026-10-20",
            "status": "open",
            "priority": "high",
        }
    ]
    pool = _create_mock_pool(fixtures)
    res = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    assert "Logisim ALU Arithmetic Core Lab" in res["response"]
    assert "RISC-V reports and Logisim labs" not in res["response"]
    assert res["data"]["count"] == 1
    assert res["data"]["tasks"][0]["title"] == "Logisim ALU Arithmetic Core Lab"


# ---------------------------------------------------------------------------
# Requirement 2: Multiple matching tasks produce useful, readable summary
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multiple_tasks_produce_grounded_summary():
    fixtures = [
        {
            "id": 101,
            "title": "CS 61C RISC-V Pipeline Emulation",
            "domain": "coursework",
            "due_date": "2026-10-22",
            "status": "open",
            "priority": "high",
        },
        {
            "id": 102,
            "title": "CS 189 Ridge Regression Assignment",
            "domain": "coursework",
            "due_date": "2026-10-28",
            "status": "open",
            "priority": "medium",
        },
    ]
    pool = _create_mock_pool(fixtures)
    res = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    assert "CS 61C RISC-V Pipeline Emulation" in res["response"]
    assert "CS 189 Ridge Regression Assignment" in res["response"]
    assert "Found **2** task(s)" in res["response"]
    assert res["data"]["count"] == 2


# ---------------------------------------------------------------------------
# Requirement 3: Actual deadline is reflected correctly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_actual_deadline_reflected_correctly():
    fixtures = [
        {
            "id": 103,
            "title": "Nebius Token Factory Demo Submission",
            "domain": "hackathon",
            "due_date": "2026-11-04",
            "status": "open",
            "priority": "urgent",
        }
    ]
    pool = _create_mock_pool(fixtures)
    res = await handle_get_hackathon_deadlines({"user_id": "grounded_user"}, pool)

    assert "Nebius Token Factory Demo Submission" in res["response"]
    assert "2026-11-04" in res["response"]
    assert "No due date" not in res["response"]
    assert "Nebius Token Factory benchmark." not in res["response"]


# ---------------------------------------------------------------------------
# Requirement 4: Conflicting deadlines explicitly identified without arbitrary resolution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conflicting_deadlines_from_memory_context():
    mem_context = (
        "Course Syllabus: CS 61C Homework due at 5:00 PM.\n"
        "Task Tracker: CS 61C Homework recorded due at 11:59 PM."
    )
    pool = _create_mock_pool([])
    res = await handle_query_coursework_tasks(
        {"course": "CS 61C", "memory_context": mem_context},
        pool,
    )

    resp = res["response"]
    assert "5:00" in resp
    assert "11:59" in resp
    assert "Course Syllabus" in resp
    assert "Task Tracker" in resp
    assert "disagree" in resp.lower() or "contradictory" in resp.lower()
    # Does not arbitrarily pick one authoritative deadline
    assert "authoritative" in resp.lower()


@pytest.mark.asyncio
async def test_conflicting_deadlines_from_task_records():
    fixtures = [
        {"id": 1, "title": "CS 61C Homework", "domain": "coursework", "due_date": "2026-10-20", "status": "open"},
        {"id": 2, "title": "CS 61C Homework", "domain": "coursework", "due_date": "2026-10-25", "status": "open"},
    ]
    pool = _create_mock_pool(fixtures)
    res = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    resp = res["response"]
    assert "2026-10-20" in resp
    assert "2026-10-25" in resp
    assert "conflicting" in resp.lower() or "contradictory" in resp.lower()


# ---------------------------------------------------------------------------
# Requirement 5: Distinct tasks with different deadlines are kept separate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_distinct_tasks_not_misidentified_as_conflicts():
    fixtures = [
        {"id": 1, "title": "CS 61C Lab 1", "domain": "coursework", "due_date": "2026-10-20", "status": "open"},
        {"id": 2, "title": "CS 61C Lab 2", "domain": "coursework", "due_date": "2026-10-27", "status": "open"},
    ]
    pool = _create_mock_pool(fixtures)
    res = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    resp = res["response"]
    assert "Conflicting Deadline Information Detected" not in resp
    assert "CS 61C Lab 1" in resp
    assert "CS 61C Lab 2" in resp


# ---------------------------------------------------------------------------
# Requirement 6: Empty results produce truthful no-results response
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_results_truthful_response():
    pool = _create_mock_pool([])
    res_cw = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)
    assert "Found 0 matching coursework task(s)" in res_cw["response"]
    assert res_cw["data"]["tasks"] == []
    assert res_cw["data"]["count"] == 0

    res_hack = await handle_get_hackathon_deadlines({"user_id": "grounded_user"}, pool)
    assert "Found 0 active hackathon deliverable(s)" in res_hack["response"]
    assert res_hack["data"]["tasks"] == []
    assert res_hack["data"]["count"] == 0


# ---------------------------------------------------------------------------
# Requirement 7: Missing optional fields do not crash or invent details
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_missing_optional_fields_no_crash():
    fixtures = [{"id": 999, "title": "Minimal Bare Task"}]
    pool = _create_mock_pool(fixtures)
    res = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    assert "Minimal Bare Task" in res["response"]
    assert "No due date" in res["response"]
    assert "open" in res["response"]


# ---------------------------------------------------------------------------
# Requirement 8: Large result sets bounded without dumping workspace
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_large_result_sets_bounded():
    fixtures = [
        {"id": i, "title": f"Assignment Batch Item {i}", "domain": "coursework", "due_date": "2026-11-01", "status": "open", "priority": "medium"}
        for i in range(1, 45)
    ]
    pool = _create_mock_pool(fixtures)
    res = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    resp = res["response"]
    assert "Found **44** task(s)" in resp
    assert "Showing top 6 prioritized items out of 44" in resp
    assert "Assignment Batch Item 1" in resp
    assert "Assignment Batch Item 43" not in resp  # Not dumped in prose
    # Full payload preserved in data for caller agents
    assert len(res["data"]["tasks"]) == 44


# ---------------------------------------------------------------------------
# Requirement 9: Tool failures are reported honestly as failures
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_failure_reported_truthfully():
    pool = _create_failing_pool("connection refused at port 5432")
    res_cw = await handle_query_coursework_tasks({"user_id": "grounded_user"}, pool)

    assert res_cw["success"] is False
    assert "Failed to retrieve coursework tasks" in res_cw["response"]
    assert "connection refused at port 5432" in res_cw["response"]
    assert res_cw["error"] == "database_error"
    assert res_cw["data"]["tasks"] == []

    res_hack = await handle_get_hackathon_deadlines({"user_id": "grounded_user"}, pool)
    assert res_hack["success"] is False
    assert "Failed to retrieve hackathon deadlines" in res_hack["response"]
    assert res_hack["error"] == "database_error"

    # Verify sensitive DSN string is redacted
    dsn_pool = _create_failing_pool("connection to server at 'postgres://admin:secret123@db:5432/prod' failed")
    res_dsn = await handle_query_tasks({}, dsn_pool)
    assert res_dsn["success"] is False
    assert "postgres://" not in res_dsn["response"]
    assert "secret123" not in res_dsn["response"]
    assert "Database connection failed" in res_dsn["response"]


# ---------------------------------------------------------------------------
# Requirement 10: Task mutations and confirmation gates remain intact
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_task_mutation_and_confirmation_gates():
    from backend.skills.handlers.tasks import handle_update_task_status, handle_delete_task
    from backend.skills import MUTATING_TOOLS

    # Verify mutating tools registry
    assert "delete_task" in MUTATING_TOOLS
    assert "update_task_status" in MUTATING_TOOLS
    assert "edit_task" in MUTATING_TOOLS

    # Missing task_id check
    pool = _create_mock_pool([])
    res_up = await handle_update_task_status({"user_id": "grounded_user"}, pool)
    assert res_up["response"] == "Missing task_id."

    res_del = await handle_delete_task({"user_id": "grounded_user"}, pool)
    assert res_del["response"] == "Missing task_id."


# ---------------------------------------------------------------------------
# Phase 1: Deadline Discrepancy Parsing Regressions
# ---------------------------------------------------------------------------
def test_orchestrator_task_summary_parsing_no_false_conflict():
    memory_context = (
        "- Review RISC-V pipeline hazards lecture (coursework) | Due: 2026-09-03 | 60m | medium\n"
        "- Embeddings truncation and Matryoshka dimension verification (code) | Due: 2026-09-04 | 45m | high\n"
        "- Prepare team sync notes (general) | Due: 2026-09-05 | 15m | low"
    )
    conflict = detect_deadline_discrepancies(memory_context=memory_context)
    assert conflict is None


def test_genuine_conflict_same_deliverable():
    memory_context = (
        "Course Syllabus: CS 61C Homework due at 5:00 PM.\n"
        "Task Tracker: CS 61C Homework recorded due at 11:59 PM."
    )
    conflict = detect_deadline_discrepancies(memory_context=memory_context)
    assert conflict is not None
    assert "cs 61c homework" in conflict["task_name"].lower()
    vals = [cv["value"] for cv in conflict["conflicting_values"]]
    assert "5:00 PM" in vals
    assert "11:59 PM" in vals


def test_orchestrator_format_genuine_conflict():
    memory_context = (
        "- CS 61C Project Submission (coursework) | Due: 2026-09-03 | 60m | urgent\n"
        "- CS 61C Project Submission (coursework) | Due: 2026-09-06 | 60m | urgent"
    )
    conflict = detect_deadline_discrepancies(memory_context=memory_context)
    assert conflict is not None
    assert "CS 61C Project Submission" in conflict["task_name"]
    vals = [cv["value"] for cv in conflict["conflicting_values"]]
    assert "2026-09-03" in vals
    assert "2026-09-06" in vals


def test_missing_or_malformed_due_dates_graceful():
    memory_context = (
        "- Task Alpha (general) | Due: Unscheduled | 30m | low\n"
        "- Task Beta (general) | Due: null | 30m | low\n"
        "- Task Gamma (general) | Due: none | 30m | low\n"
        "Course Notes: Some random note without any valid due dates."
    )
    conflict = detect_deadline_discrepancies(memory_context=memory_context)
    assert conflict is None


def test_empty_and_none_inputs_safe():
    assert detect_deadline_discrepancies(None, None, None) is None
    assert detect_deadline_discrepancies([], "", "") is None


# ---------------------------------------------------------------------------
# Phase 2: Evaluator Text Normalization Regressions
# ---------------------------------------------------------------------------
def test_evaluator_unicode_normalization_first_in():
    from eval.deterministic import eval_contains_substring

    # Unicode non-breaking hyphen (\u2011) and regular hyphen
    assert eval_contains_substring("**FIFO (First\u2011In, First\u2011Out)**", "First In")
    assert eval_contains_substring("**FIFO (First-In, First-Out)**", "First In")
    assert eval_contains_substring("First In First Out", "First-In")


def test_evaluator_unicode_normalization_risc_v():
    from eval.deterministic import eval_contains_substring

    assert eval_contains_substring("**RISC\u2011V vs. x86: A Side\u2011by\u2011Side Comparison**", "RISC-V")
    assert eval_contains_substring("RISC-V architecture", "RISC-V")


def test_evaluator_non_breaking_spaces():
    from eval.deterministic import eval_contains_substring

    assert eval_contains_substring("Due:\u00a02026-10-17\u202fat\u00a05:00\u00a0PM", "5:00 PM")
    assert eval_contains_substring("CS\u202f61C RISC\u2011V Report", "CS 61C")


def test_evaluator_unrelated_or_missing_phrase_fails():
    from eval.deterministic import eval_contains_substring

    assert not eval_contains_substring("RISC stands for Reduced Instruction Set Computer", "MIPS Architecture")
    assert not eval_contains_substring("FIFO cache policy", "LRU cache")
    assert not eval_contains_substring("", "Something")


# ---------------------------------------------------------------------------
# Phase 3: Conversational Recall Regressions (D4)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conversational_recall_d4_empty_database():
    """Edge Case 1: Recent history says 'Friday at 5 PM', user asks when demo is due."""
    history = [
        {"role": "user", "content": "I have a hackathon demo video deadline on Friday at 5 PM."},
        {"role": "assistant", "content": "Got it! I noted your Hackathon demo video deadline for Friday at 5 PM."},
    ]
    pool = _create_mock_pool([])  # 0 tasks in DB
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "When is that demo video due again?",
        "history": history,
        "memory_context": "- Review RISC-V pipeline hazards lecture (coursework) | Due: 2026-09-03 | 60m | medium",
    }, pool)

    assert "Friday" in res["response"]
    assert "5" in res["response"]
    assert "Conflicting Deadline" not in res["response"]
    assert "60m" not in res["response"]
    assert "conversation" in res["response"].lower() or "earlier" in res["response"].lower()


@pytest.mark.asyncio
async def test_conversational_recall_calendar_date_and_time():
    """Edge Case 2: History contains a specific, unambiguous calendar date and time."""
    history = [
        {"role": "user", "content": "The final project proposal is due October 24 at 3 PM."},
        {"role": "assistant", "content": "Noted! Project proposal deadline is October 24 at 3 PM."},
    ]
    pool = _create_mock_pool([])
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "When is the project proposal due?",
        "history": history,
    }, pool)

    assert "October 24 at 3 PM" in res["response"]
    assert "database task" in res["response"]


@pytest.mark.asyncio
async def test_conversational_recall_preserves_wording_without_this_friday():
    """Edge Case 3: History is older; 'this Friday' could be misleading. Preserves exact wording."""
    history = [
        {"role": "user", "content": "The demo video is due Friday at 5 PM."},
    ]
    pool = _create_mock_pool([])
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "When is that demo video due again?",
        "history": history,
    }, pool)

    assert "Friday at 5 PM" in res["response"]
    assert "this Friday" not in res["response"]


@pytest.mark.asyncio
async def test_conversational_recall_multiple_plausible_deadlines_clarification():
    """Edge Case 4: History contains multiple plausible demo deadlines. Asks a clarifying question."""
    history = [
        {"role": "user", "content": "We discussed submitting the demo video on Friday at 5 PM or Sunday at 12 PM."},
    ]
    pool = _create_mock_pool([])
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "When is that demo video due again?",
        "history": history,
    }, pool)

    assert "multiple" in res["response"].lower()
    assert "Friday at 5 PM" in res["response"]
    assert "Sunday at 12 PM" in res["response"]
    assert "clarify" in res["response"].lower() or "which" in res["response"].lower()


@pytest.mark.asyncio
async def test_conversational_recall_db_conflict_explains_discrepancy():
    """Edge Case 5: Database contains a different deadline from conversationally reported deadline."""
    history = [
        {"role": "user", "content": "The hackathon demo video deadline is Friday at 5 PM."},
    ]
    db_tasks = [
        {"id": 99, "title": "Hackathon demo video", "domain": "hackathon", "due_date": "2026-10-25", "status": "open", "priority": "urgent"}
    ]
    pool = _create_mock_pool(db_tasks)
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "When is the demo video due?",
        "history": history,
    }, pool)

    assert "Discrepancy Detected" in res["response"]
    assert "Friday at 5 PM" in res["response"]
    assert "2026-10-25" in res["response"]


# ---------------------------------------------------------------------------
# Phase 4: Planning & Routing Regressions (B1 & B2)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_daily_roadmap_b1_headings_and_prioritization():
    tasks = [
        {"id": 1, "title": "Submit final video demo", "domain": "hackathon", "due_date": "2026-10-17", "priority": "urgent", "status": "open"},
        {"id": 2, "title": "Benchmark GPU memory bandwidth", "domain": "hackathon", "due_date": None, "priority": "high", "status": "open"},
        {"id": 3, "title": "RISC-V pipeline hazard lab report", "domain": "coursework", "due_date": "2026-10-18", "priority": "high", "status": "open"},
        {"id": 4, "title": "Review CS 61C lecture slides", "domain": "coursework", "due_date": None, "priority": "medium", "status": "open"},
        {"id": 5, "title": "Refactor token router client", "domain": "code", "due_date": None, "priority": "medium", "status": "open"},
        {"id": 6, "title": "Update team README documentation", "domain": "general", "due_date": None, "priority": "low", "status": "open"},
    ]
    pool = _create_mock_pool(tasks)
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "I have 6 tasks needing attention today. Please analyze my deadlines and suggest an optimal step-by-step roadmap for today.",
        "intent": "roadmap",
    }, pool)

    assert "### Your plan for today" in res["response"]
    assert "### 1. Start here" in res["response"]
    assert "Submit final video demo" in res["response"]
    assert "No due date" in res["response"]


@pytest.mark.asyncio
async def test_immediate_prioritization_overdue_b2():
    tasks = [
        {"id": 11, "title": "Submit project proposal", "domain": "coursework", "due_date": "2026-10-14", "priority": "high", "status": "open"},
        {"id": 12, "title": "Study for midterm exam", "domain": "coursework", "due_date": "2026-10-25", "priority": "urgent", "status": "open"},
    ]
    pool = _create_mock_pool(tasks)
    res = await handle_query_tasks({
        "user_id": "grounded_user",
        "user_message": "What should I work on first right now?",
    }, pool)

    assert "Submit project proposal" in res["response"]
    assert "1. Start here" in res["response"]
    assert "overdue" in res["response"].lower()
