"""Tests for the delete task disambiguation prompt builder."""

from __future__ import annotations

import os

import pytest

from backend.memory.db import get_pool
from backend.orchestrator import handle_message

USER = "test_user_delete_prompt"
CONV = "conv-delete-prompt"


@pytest.fixture(autouse=True)
def ensure_real_postgres():
    test_db = os.environ.get("TEST_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not test_db:
        pytest.skip("DATABASE_URL / TEST_DATABASE_URL not set; skipping delete prompt tests.")


async def _seed(titles: list[str], user: str = USER):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = $1", user)
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)
        ids = []
        for title in titles:
            ids.append(
                await conn.fetchval(
                    "INSERT INTO tasks (title, domain, user_id) VALUES ($1, 'general', $2) RETURNING id",
                    title,
                    user,
                )
            )
    return pool, ids


async def _cleanup(pool, user: str = USER):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = $1", user)
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)


@pytest.mark.parametrize(
    "count, expected",
    [
        (0, "Which one? Reply with 1, 2 or 3, or 'Cancel'."),
        (1, "Reply with 1, or 'Cancel'."),
        (2, "Which one? Reply with 1 or 2, or 'Cancel'."),
        (3, "Which one? Reply with 1, 2 or 3, or 'Cancel'."),
        (5, "Which one? Reply with 1, 2 or 3, or 'Cancel'."),
    ],
)
def test_disambiguation_prompt_counts(count: int, expected: str):
    from backend.orchestrator import _disambiguation_prompt

    assert _disambiguation_prompt(count) == expected


@pytest.mark.asyncio
async def test_e2e_delete_disambiguation_prompt_two_candidates():
    pool, _ = await _seed(["Review Lab 1", "Review Lab 2"])
    try:
        # Trigger delete disambiguation with 2 matching tasks
        res1 = await handle_message(
            conversation_id=CONV,
            message="delete my deadline",
            user_id=USER,
        )
        assert res1["skill_used"] == "chat_delete_task"
        pending = res1.get("data", {}).get("pending_action", {})
        assert pending.get("action") == "delete_task_disambiguation"
        assert len(pending.get("task_ids", [])) == 2

        # User replies with "3", which does not select either candidate
        res2 = await handle_message(
            conversation_id=CONV,
            message="3",
            user_id=USER,
        )
        assert res2["success"] is False
        assert res2["response"] == "Which one? Reply with 1 or 2, or 'Cancel'."
    finally:
        await _cleanup(pool)
