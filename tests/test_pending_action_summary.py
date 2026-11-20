"""The Planner approval card must name the task, not show "Task #2197"."""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

from backend.agent_pending import describe_task_action
from backend.memory.db import get_pool


@pytest.fixture(autouse=True)
def ensure_real_postgres():
    if not (os.environ.get("TEST_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()):
        pytest.skip("DATABASE_URL / TEST_DATABASE_URL not set.")


async def _insert(conn, user_id, title, due="2026-11-24"):
    return await conn.fetchval(
        "INSERT INTO tasks (title, domain, priority, status, user_id, due_date) "
        "VALUES ($1, 'coursework', 'medium', 'open', $2, $3) RETURNING id",
        title, user_id, date.fromisoformat(due),
    )


@pytest.mark.asyncio
async def test_summary_uses_the_real_task_name_for_edit_delete_and_status():
    pool = await get_pool()
    user = f"user-{uuid.uuid4().hex[:8]}"
    title = f"Computer Networks lab report {uuid.uuid4().hex[:4]}"
    async with pool.acquire() as conn:
        tid = await _insert(conn, user, title)
    try:
        moved = await describe_task_action(pool, user, "edit_task", {"task_id": tid, "due_date": "2026-12-01"})
        assert moved == f'Update task: "{title}" (due 2026-11-24 to 2026-12-01)'
        same_day = await describe_task_action(pool, user, "edit_task", {"task_id": tid, "due_date": "2026-11-24"})
        assert same_day == f'Update task: "{title}"'
        assert await describe_task_action(pool, user, "delete_task", {"task_id": tid}) == f'Permanently remove task "{title}"'
        assert await describe_task_action(pool, user, "update_task_status", {"task_id": tid, "status": "done"}) == f'Mark "{title}" as completed'
        assert await describe_task_action(pool, user, "update_task_status", {"task_id": tid, "status": "blocked"}) == f'Mark "{title}" as blocked'
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)


@pytest.mark.asyncio
async def test_summary_never_reveals_another_users_task_name():
    pool = await get_pool()
    owner = f"owner-{uuid.uuid4().hex[:8]}"
    other = f"other-{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        tid = await _insert(conn, owner, "Private thesis draft")
    try:
        assert await describe_task_action(pool, other, "edit_task", {"task_id": tid, "due_date": "2026-12-01"}) is None
        assert await describe_task_action(pool, None, "edit_task", {"task_id": tid}) is None
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE user_id = $1", owner)


@pytest.mark.asyncio
async def test_summary_falls_back_quietly_for_bad_input():
    pool = await get_pool()
    assert await describe_task_action(pool, "u", "edit_task", {"task_id": "not-a-number"}) is None
    assert await describe_task_action(pool, "u", "edit_task", {}) is None
    assert await describe_task_action(pool, "u", "edit_task", {"task_id": 999999999}) is None
    assert await describe_task_action(pool, "u", "add_task", {"task_id": 1}) is None
    assert await describe_task_action(None, "u", "edit_task", {"task_id": 1}) is None


def test_tour_sample_chat_gets_a_plain_title():
    from backend.memory.conversations import friendly_title

    assert friendly_title("Add these 8 tasks to my deadlines: | Task | Domain | Priority |") == "Load a sample week"
    assert friendly_title("   Add these 8 tasks to my deadlines: x") == "Load a sample week"
    assert friendly_title("Plan my week") == "Plan my week"
    assert friendly_title("") == ""
