"""Regression tests for chat task/skill handler fixes."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.skills.handlers import context, parked, tasks


def _pool(conn=None):
    conn = conn or AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, conn


@pytest.mark.asyncio
async def test_log_code_context_forwards_user_id():
    pool, _ = _pool()
    with patch("backend.memory.vector.store_chunk", new=AsyncMock(return_value={})) as store:
        await context.handle_log_code_context({"content": "x", "user_id": "u1"}, pool)
    assert store.await_args.kwargs.get("user_id") == "u1"


@pytest.mark.asyncio
async def test_log_code_snippet_forwards_user_id():
    pool, _ = _pool()
    with patch("backend.memory.vector.store_chunk", new=AsyncMock(return_value={})) as store:
        await context.handle_log_code_snippet({"content": "x", "user_id": "u1"}, pool)
    assert store.await_args.kwargs.get("user_id") == "u1"


@pytest.mark.asyncio
async def test_add_task_shift_existing_scopes_owner():
    pool, conn = _pool()
    existing = [{"id": 5, "title": "Essay", "status": "open", "due_date": "2030-01-01", "notes": None}]
    with patch("backend.memory.structured.list_tasks", new=AsyncMock(return_value=existing)), \
         patch("backend.memory.structured.update_task", new=AsyncMock(return_value={"id": 5})) as upd:
        await tasks.handle_add_task(
            {"title": "Essay", "due_date": "2030-02-02", "shift_existing": True, "user_id": "u1"}, pool
        )
    assert upd.await_args.kwargs.get("owner_id") == "u1"


@pytest.mark.asyncio
async def test_resolve_parked_reports_not_found():
    pool, _ = _pool()
    with patch.object(parked, "resolve_parked_thought", new=AsyncMock(return_value=False)):
        res = await parked.handle_resolve_parked({"thought_id": 99, "user_id": "u1"}, pool)
    assert "resolved" not in res["response"].lower() or "couldn't" in res["response"].lower()
    assert res["data"]["status"] == "not_found"
    assert res["response"] != "Marked that parked thought as resolved."


@pytest.mark.asyncio
async def test_edit_task_none_due_date_clears_deadline():
    pool, _ = _pool()
    with patch("backend.memory.structured.update_task", new=AsyncMock(return_value={"id": 1})) as upd:
        res = await tasks.handle_edit_task({"task_id": 1, "due_date": None, "user_id": "u1"}, pool)
    assert "Invalid date" not in res["response"]
    assert upd.await_args.kwargs["due_date"] is None


@pytest.mark.asyncio
async def test_update_task_status_none_defaults_open():
    pool, _ = _pool()
    with patch("backend.memory.structured.update_task", new=AsyncMock(return_value={"id": 1})) as upd:
        await tasks.handle_update_task_status({"task_id": 1, "status": None}, pool)
    assert upd.await_args.kwargs["status"] == "open"


def test_roadmap_total_count_excludes_done_tasks():
    items = [
        {"id": 1, "title": "A", "status": "open", "priority": "high", "due_date": None},
        {"id": 2, "title": "B", "status": "done", "priority": "high", "due_date": None},
        {"id": 3, "title": "C", "status": "done", "priority": "low", "due_date": None},
    ]
    out = tasks.build_daily_roadmap(items, target_date=date(2030, 1, 1), tone="brief")
    assert "**1** active task" in out
