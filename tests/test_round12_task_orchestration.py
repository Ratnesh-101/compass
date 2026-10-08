"""
Round 12 Task Creation Orchestration & Parser Verification.

Tests run through the REAL orchestrator against the database:
1. "add a deadline on 10th of October 23:59 with the name complete python programming"
   - Echoes only user-supplied fields (title, date, time, timezone).
   - Does not invent priority or category.
   - Undo deletes the created task.
2. "remind me to email prof tomorrow at 4pm"
   - Extracts title and tomorrow at 4pm.
3. "add task: x"
   - Creates task with title 'x'.
4. Message with a date but no title ("add a deadline on 10th of October 23:59")
   - Prompts for title; does not create a task.
5. Non-task sentences containing the word "deadline":
   - "When is the Nebius x NVIDIA hackathon submission deadline?"
   - "The deadline for homework is next week"
   - Must NOT create a task.
6. Duplicate title + due date:
   - Alerts user to existing deadline; prevents duplicate insertion.
"""

import pytest
from datetime import date, timedelta
from backend.orchestrator import handle_message
from backend.memory.db import get_pool
from backend.memory import structured


@pytest.fixture(autouse=True)
async def cleanup_test_data():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id LIKE 'test_user_round12_%'")
        await conn.execute("DELETE FROM agent_audit_log WHERE approved_by LIKE 'test_user_round12_%'")
    yield
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id LIKE 'test_user_round12_%'")
        await conn.execute("DELETE FROM agent_audit_log WHERE approved_by LIKE 'test_user_round12_%'")


@pytest.mark.asyncio
async def test_scenario_1_exact_echo_no_invented_priority_and_undo():
    test_user = "test_user_round12_s1"
    msg = "add a deadline on 10th of October 23:59 with the name complete python programming"

    res = await handle_message(
        message=msg,
        user_id=test_user,
        persist=False,
    )

    assert res["skill_used"] == "add_task"
    assert res["success"] is True
    data = res["data"]
    assert "complete python programming" in data["title"].lower()
    assert str(data["due_date"]) == "2026-10-10"

    # Confirmation must echo only what the user said (title, date, time); do NOT invent priority/category
    reply = res["response"]
    assert "complete python programming" in reply.lower()
    assert "2026-10-10" in reply
    assert "23:59" in reply
    assert "UTC" in reply or "time" in reply
    assert "(Type 'undo' to revert)" in reply

    # Must NOT invent priority or category in confirmation text
    assert "high priority" not in reply.lower()
    assert "urgent priority" not in reply.lower()
    assert "hackathon task" not in reply.lower()
    assert "coursework task" not in reply.lower()

    # Verify task exists in DB
    pool = await get_pool()
    task_id = data["id"]
    async with pool.acquire() as conn:
        db_task = await structured.get_task(conn, task_id)
        assert db_task is not None

    # Test UNDO: User says "undo"
    undo_res = await handle_message(
        message="undo",
        user_id=test_user,
        persist=False,
    )
    assert undo_res["skill_used"] == "undo"
    assert undo_res["success"] is True
    assert "undid" in undo_res["response"].lower()

    # Verify task was removed from DB by undo
    async with pool.acquire() as conn:
        deleted_task = await structured.get_task(conn, task_id)
        assert deleted_task is None


@pytest.mark.asyncio
async def test_scenario_2_remind_me_tomorrow_at_4pm():
    test_user = "test_user_round12_s2"
    msg = "remind me to email prof tomorrow at 4pm"

    res = await handle_message(
        message=msg,
        user_id=test_user,
        persist=False,
    )

    assert res["skill_used"] == "add_task"
    assert res["success"] is True
    data = res["data"]
    assert "email prof" in data["title"].lower()

    tomorrow = date.today() + timedelta(days=1)
    assert str(data["due_date"]) == tomorrow.isoformat()

    reply = res["response"]
    assert "email prof" in reply.lower()
    assert tomorrow.isoformat() in reply

    # Clean up
    pool = await get_pool()
    async with pool.acquire() as conn:
        await structured.delete_task(conn, data["id"])


@pytest.mark.asyncio
async def test_scenario_3_add_task_x():
    test_user = "test_user_round12_s3"
    msg = "add task: x"

    res = await handle_message(
        message=msg,
        user_id=test_user,
        persist=False,
    )

    assert res["skill_used"] == "add_task"
    assert res["success"] is True
    data = res["data"]
    assert data["title"].lower() == "x"

    # Clean up
    pool = await get_pool()
    async with pool.acquire() as conn:
        await structured.delete_task(conn, data["id"])


@pytest.mark.asyncio
async def test_scenario_4_date_without_title_prompts_user():
    test_user = "test_user_round12_s4"
    msg = "add a deadline on 10th of October 23:59"

    res = await handle_message(
        message=msg,
        user_id=test_user,
        persist=False,
    )

    # Must ask for title and NOT create a task
    assert res.get("skill_used") != "add_task"
    assert "what would you like to name this task" in res["response"].lower()

    # Verify no tasks were created
    pool = await get_pool()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, user_id=test_user)
        user_tasks = [t for t in tasks if t.get("user_id") == test_user]
        assert len(user_tasks) == 0


@pytest.mark.asyncio
async def test_scenario_5_non_task_sentences_with_deadline_do_not_create_task():
    test_user = "test_user_round12_s5"
    non_task_messages = [
        "When is the Nebius x NVIDIA hackathon submission deadline?",
        "The deadline for homework is next week",
        "What is the submission deadline?",
        "Do I have a deadline coming up?",
    ]

    for msg in non_task_messages:
        res = await handle_message(
            message=msg,
            user_id=test_user,
            persist=False,
        )
        # Must NOT execute add_task
        assert res.get("skill_used") != "add_task", f"Erroneously dispatched add_task for query: '{msg}'"

    # Verify 0 tasks created
    pool = await get_pool()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, user_id=test_user)
        user_tasks = [t for t in tasks if t.get("user_id") == test_user]
        assert len(user_tasks) == 0


@pytest.mark.asyncio
async def test_scenario_6_duplicate_title_and_due_date_prevention():
    test_user = "test_user_round12_s6"
    msg = "add a deadline on 10th of October 23:59 with the name complete python programming"

    # Call 1: Success
    res1 = await handle_message(message=msg, user_id=test_user, persist=False)
    assert res1["skill_used"] == "add_task"
    assert res1["success"] is True
    created_id = res1["data"]["id"]

    # Call 2: Identical task
    res2 = await handle_message(message=msg, user_id=test_user, persist=False)
    assert res2["success"] is False
    assert "already exists in your schedule" in res2["response"]

    # Verify only 1 task in DB
    pool = await get_pool()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, user_id=test_user)
        assert len(tasks) == 1
        await structured.delete_task(conn, created_id)
