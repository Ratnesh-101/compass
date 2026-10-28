"""
Regression tests for the in-chat "undo" skill and for tone / mode pass-through on the stream path.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from backend import orchestrator
from backend.agent_persistence import record_audit_log
from backend.memory.db import get_pool
from backend.routers.auth import create_session


def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}


def _user(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _make_task(client: AsyncClient, user_id: str, title: str) -> int:
    res = await client.post("/api/tasks", json={"title": title, "domain": "hackathon"}, headers=_auth(user_id))
    assert res.status_code == 200, res.text
    return int(res.json()["id"])


async def _title(task_id: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT title FROM tasks WHERE id = $1", task_id)


async def _stage_edit(owner: str, task_id: int, old_title: str) -> int:
    """Simulate a confirmed agent edit: the audit row stores the owner in args.user_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET title = $2 WHERE id = $1", task_id, "Edited title")
    return await record_audit_log(
        pool,
        tool="edit_task",
        args={"task_id": task_id, "title": "Edited title", "user_id": owner},
        run_id=f"run_{uuid.uuid4().hex}",
        affected_id=task_id,
        previous_state={"title": old_title, "priority": "medium", "status": "open", "notes": None, "due_date": None},
        approved_by="user",
    )


async def _chat_undo(user_id: str) -> dict:
    return await orchestrator.handle_message(
        message="undo", user_id=user_id, persist=False, pre_routed_skill="undo"
    )


@pytest.mark.asyncio
async def test_chat_undo_restores_an_agent_edit_and_says_so(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner, "Original title")
    audit_id = await _stage_edit(owner, task_id, "Original title")

    result = await _chat_undo(owner)

    assert result["success"] is True
    assert "Removed task" not in result["response"]
    assert "Restored task" in result["response"]
    assert await _title(task_id) == "Original title"
    pool = await get_pool()
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT is_reverted FROM agent_audit_log WHERE id = $1", audit_id) is True


@pytest.mark.asyncio
async def test_chat_undo_never_touches_another_users_action(client: AsyncClient):
    owner, other = _user("alice"), _user("bob")
    task_id = await _make_task(client, owner, "Original title")
    await _stage_edit(owner, task_id, "Original title")

    result = await _chat_undo(other)

    assert result["success"] is False
    assert await _title(task_id) == "Edited title"


@pytest.mark.asyncio
async def test_stream_fast_path_passes_tone_and_mode_to_the_orchestrator(client: AsyncClient, monkeypatch):
    handle = AsyncMock(return_value={"response": "ok", "skill_used": "chat_delete_task", "data": {}})
    monkeypatch.setattr("backend.orchestrator.handle_message", handle)

    from backend.dependencies import generate_guest_token

    _, guest_token = generate_guest_token()
    async with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "delete all my tasks", "tone": "brief", "mode": "research"},
        headers={"x-guest-token": guest_token},
        timeout=10.0,
    ) as resp:
        assert resp.status_code == 200
        events = [json.loads(line[6:]) async for line in resp.aiter_lines()
                  if line.startswith("data: ") and line[6:].strip() != "[DONE]"]

    assert any(e.get("type") == "done" for e in events), events
    kwargs = handle.await_args.kwargs
    assert kwargs["tone"] == "brief"
    assert kwargs["conv_mode"] == "research"
