"""The model may not overwrite an existing deadline on its own.

Live bug: "remind me to submit my lab report by next Wednesday" came back as "Shifted existing deadline
'Computer Networks lab report' ...", because the model passed shift_existing=true for a task whose name
matched an existing one. Only the user's own words ("move it", "reschedule") may do that.
"""

from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

from backend.memory.db import get_pool
from backend.orchestrator import handle_message
from backend.services.task_intent import user_asked_to_shift
from backend.skills.handlers.tasks import handle_add_task

NO_SHIFT = [
    "remind me to submit my lab report by next Wednesday",
    "add task",
    "submit the lab report by friday",
    "what is due this week",
    "I need to turn in my report by Wednesday",
    "add a reminder to set up the demo by friday",
    "update my resume by friday",
    "move the demo to the cloud by friday",
]
SHIFT = [
    "move my lab report deadline to Friday",
    "please reschedule the lab report to next week",
    "push it back to Monday",
    "can you change the due date to the 25th",
    "set the deadline to Friday",
    "postpone the exam prep",
    "shift my essay deadline",
    "move the lab report to Friday",
    "move it to next week",
    "move the lab report to 2031-02-02",
]


@pytest.mark.parametrize("message", NO_SHIFT)
def test_ordinary_requests_do_not_count_as_a_move(message):
    assert user_asked_to_shift(message) is False


@pytest.mark.parametrize("message", SHIFT)
def test_explicit_move_requests_count(message):
    assert user_asked_to_shift(message) is True


def test_empty_message_is_not_a_move():
    assert user_asked_to_shift("") is False
    assert user_asked_to_shift(None) is False


@pytest.fixture
def real_postgres():
    if not (os.environ.get("TEST_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()):
        pytest.skip("DATABASE_URL / TEST_DATABASE_URL not set.")


async def _insert_task(conn, user_id, title, due):
    return await conn.fetchval(
        "INSERT INTO tasks (title, domain, priority, status, user_id, due_date) "
        "VALUES ($1, 'general', 'medium', 'open', $2, $3) RETURNING id",
        title, user_id, date.fromisoformat(due),
    )


async def _due(conn, task_id):
    return str(await conn.fetchval("SELECT due_date FROM tasks WHERE id = $1", task_id))


async def _cleanup(conn, owner):
    await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = $1", owner)
    await conn.execute("DELETE FROM tasks WHERE user_id = $1", owner)
    await conn.execute("DELETE FROM conversations WHERE user_id = $1 OR guest_id = $1", owner)


@pytest.mark.asyncio
async def test_chat_add_does_not_shift_an_existing_task_unless_asked(real_postgres, monkeypatch):
    monkeypatch.setattr("backend.orchestrator.SINGLE_TASK_PREVIEW", False)
    pool = await get_pool()
    guest = f"guest-{uuid.uuid4().hex[:8]}"
    title = f"Lab Report {uuid.uuid4().hex[:6]}"
    async with pool.acquire() as conn:
        existing = await _insert_task(conn, guest, title, "2030-01-01")
    try:
        res = await handle_message(
            message="remind me to submit my lab report by next Wednesday",
            guest_id=guest,
            pre_routed_skill="add_task",
            pre_routed_args={"title": title, "due_date": "2031-02-02", "shift_existing": True},
            persist=False,
        )
        async with pool.acquire() as conn:
            assert await _due(conn, existing) == "2030-01-01", "the existing deadline must not move"
        assert "Shifted existing deadline" not in res["response"]
        assert "shift your existing deadline" in res["response"] or "already exists" in res["response"]

        res2 = await handle_message(
            message="move my lab report deadline to 2031-02-02",
            guest_id=guest,
            pre_routed_skill="add_task",
            pre_routed_args={"title": title, "due_date": "2031-02-02", "shift_existing": True},
            persist=False,
        )
        assert res2["success"] is True
        async with pool.acquire() as conn:
            assert await _due(conn, existing) == "2031-02-02"
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, guest)


@pytest.mark.asyncio
async def test_skill_handler_gates_the_flag_when_a_user_message_is_attached(real_postgres):
    pool = await get_pool()
    user = f"user-{uuid.uuid4().hex[:8]}"
    title = f"Essay {uuid.uuid4().hex[:6]}"
    async with pool.acquire() as conn:
        existing = await _insert_task(conn, user, title, "2030-01-01")
    try:
        base = {"title": title, "due_date": "2031-02-02", "shift_existing": True, "user_id": user}
        res = await handle_add_task({**base, "user_message": "remind me to hand in the essay by friday"}, pool)
        assert "Shifted existing deadline" not in res["response"]
        async with pool.acquire() as conn:
            assert await _due(conn, existing) == "2030-01-01"

        res2 = await handle_add_task({**base, "user_message": "reschedule the essay to 2031-02-02"}, pool)
        assert "Shifted existing deadline" in res2["response"]
        async with pool.acquire() as conn:
            assert await _due(conn, existing) == "2031-02-02"
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user)
