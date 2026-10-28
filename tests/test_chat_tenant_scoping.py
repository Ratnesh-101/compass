"""Chat tenant-scoping and confirmation-atomicity regression tests."""

from __future__ import annotations

import os
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from backend.memory import conversations
from backend.memory.chat_pending import (
    create_chat_pending_action,
    get_active_chat_pending_action,
)
from backend.memory.db import get_pool
from backend.orchestrator import handle_message


@pytest.fixture(autouse=True)
def ensure_real_postgres():
    test_db = os.environ.get("TEST_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not test_db:
        pytest.skip("DATABASE_URL / TEST_DATABASE_URL not set.")


async def _insert_task(conn, user_id, title, due="2030-01-01"):
    return await conn.fetchval(
        "INSERT INTO tasks (title, domain, priority, status, user_id, due_date) "
        "VALUES ($1, 'general', 'medium', 'open', $2, $3) RETURNING id",
        title, user_id, date.fromisoformat(due),
    )


async def _cleanup(conn, owners):
    await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = ANY($1::text[])", list(owners))
    await conn.execute("DELETE FROM tasks WHERE user_id = ANY($1::text[])", list(owners))
    await conn.execute(
        "DELETE FROM conversations WHERE user_id = ANY($1::text[]) OR guest_id = ANY($1::text[])", list(owners)
    )


@pytest.mark.asyncio
async def test_guest_add_task_does_not_see_or_shift_other_users_tasks():
    pool = await get_pool()
    owner = f"owner-{uuid.uuid4().hex[:8]}"
    guest = f"guest-{uuid.uuid4().hex[:8]}"
    title = f"Secret Report {uuid.uuid4().hex[:6]}"
    async with pool.acquire() as conn:
        victim_id = await _insert_task(conn, owner, title, "2030-01-01")
    try:
        res = await handle_message(
            message="add task",
            guest_id=guest,
            pre_routed_skill="add_task",
            pre_routed_args={"title": title, "due_date": "2030-01-01"},
            persist=False,
        )
        assert (res.get("data") or {}).get("error") != "duplicate_exact_deadline"
        assert "already exists" not in res["response"]

        res2 = await handle_message(
            message="add task",
            guest_id=guest,
            pre_routed_skill="add_task",
            pre_routed_args={"title": title, "due_date": "2031-02-02", "shift_existing": True},
            persist=False,
        )
        assert res2["success"] is True
        async with pool.acquire() as conn:
            victim = await conn.fetchrow("SELECT due_date FROM tasks WHERE id = $1", victim_id)
            assert str(victim["due_date"]) == "2030-01-01"
            guest_rows = await conn.fetch(
                "SELECT due_date FROM tasks WHERE title = $1 AND user_id = $2", title, guest
            )
            assert [str(r["due_date"]) for r in guest_rows] == ["2031-02-02"], "only the guest's own task is shifted"
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [owner, guest])


@pytest.mark.asyncio
async def test_guest_add_task_conversation_is_owned_by_guest():
    pool = await get_pool()
    guest = f"guest-{uuid.uuid4().hex[:8]}"
    title = f"Owned Conv Task {uuid.uuid4().hex[:6]}"
    try:
        res = await handle_message(
            message="add task",
            guest_id=guest,
            pre_routed_skill="add_task",
            pre_routed_args={"title": title, "due_date": "2030-03-03"},
            persist=True,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, guest_id FROM conversations WHERE id = $1::uuid", res["conversation_id"]
            )
        assert row is not None and row["guest_id"] == guest
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [guest])


@pytest.mark.asyncio
async def test_mutating_gate_conversation_is_owned():
    pool = await get_pool()
    guest = f"guest-{uuid.uuid4().hex[:8]}"
    try:
        res = await handle_message(
            message="edit it",
            guest_id=guest,
            pre_routed_skill="edit_task",
            pre_routed_args={},
            persist=True,
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id, guest_id FROM conversations WHERE id = $1::uuid", res["conversation_id"]
            )
        assert row is not None and row["guest_id"] == guest
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [guest])


@pytest.mark.asyncio
async def test_cross_conversation_memory_requires_an_identity():
    pool = await get_pool()
    user = f"mem-{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        cid = await conversations.get_or_create_conversation(conn, None, user_id=user)
        await conversations.add_message(conn, cid, role="user", content="private memory text")
    try:
        async with pool.acquire() as conn:
            assert await conversations.get_cross_conversation_memory(conn) == []
            mine = await conversations.get_cross_conversation_memory(conn, user_id=user)
            assert any(m["content"] == "private memory text" for m in mine)
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [user])


@pytest.mark.asyncio
async def test_chat_delete_task_without_database_does_not_crash():
    with patch("backend.orchestrator.get_pool", AsyncMock(return_value=None)):
        res = await handle_message(
            message="delete my task",
            user_id="u_nopool",
            pre_routed_skill="chat_delete_task",
            pre_routed_args={"query": "x"},
            persist=False,
        )
    assert res["skill_used"] == "chat_delete_task"
    assert "database" in res["response"].lower()
    assert res["data"] is None


@pytest.mark.asyncio
async def test_confirm_loser_of_race_deletes_nothing_and_reports_no_pending():
    """If another request claims the action first, this confirm must not delete anything."""
    pool = await get_pool()
    user = f"race-{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        task_id = await _insert_task(conn, user, "Race Task")
        pending = await create_chat_pending_action(
            conn, action="delete_task", task_ids=[task_id],
            task_titles=[{"id": task_id, "title": "Race Task"}], count=1,
            owner_identity=user, conversation_id="conv-race",
        )

    async def get_then_lose_race(conn, owner, conv):
        action = await get_active_chat_pending_action(conn, owner, conv)
        await conn.execute("UPDATE chat_pending_actions SET status='executed' WHERE id=$1", pending["id"])
        return action

    try:
        with patch("backend.memory.chat_pending.get_active_chat_pending_action", get_then_lose_race):
            res = await handle_message(conversation_id="conv-race", message="Confirm", user_id=user)
        assert "no pending actions" in res["response"].lower()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is None
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [user])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply", ["1", "first one", "the first one", "delete the first one", "complete the first one"]
)
async def test_clear_schedule_rejects_single_task_replies(reply):
    pool = await get_pool()
    user = f"clr-{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        task_id = await _insert_task(conn, user, "Clear Me")
        await create_chat_pending_action(
            conn, action="clear_schedule", task_ids=[task_id],
            task_titles=[{"id": task_id, "title": "Clear Me"}], count=1,
            owner_identity=user, conversation_id="conv-clr",
        )
    try:
        res = await handle_message(
            conversation_id="conv-clr", message=reply, user_id=user,
            pre_routed_skill="pending_action_confirm", pre_routed_args={},
        )
        assert "isn't a confirmation" in res["response"]
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT deleted_at FROM tasks WHERE id = $1", task_id)
        assert row["deleted_at"] is None
    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [user])


def test_chat_pending_debug_format_uses_percent_s():
    import inspect

    from backend.memory import chat_pending

    assert "%e" not in inspect.getsource(chat_pending)
