"""
Regression tests from the general app audit.

Each test fails against the pre-fix code.
"""

import uuid

import pytest

from backend.agents.specialist import SpecialistDispatcher, SpecialistRequest
from backend.memory.db import get_pool


def _user(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


@pytest.mark.asyncio
async def test_specialist_created_task_belongs_to_the_caller(monkeypatch):
    """A task the specialist creates must be owned by the requester, not stored with user_id NULL."""

    async def offline(args, pool):
        return {"response": "", "data": {}}

    # No outbound web search or embedding calls in tests.
    monkeypatch.setattr("backend.skills.handle_search_web", offline)
    monkeypatch.setattr("backend.skills.handle_query_code_context", offline)

    owner = _user("alice")
    token = uuid.uuid4().hex[:12]
    pool = await get_pool()
    await SpecialistDispatcher.dispatch(
        SpecialistRequest(capability="memory", user_goal=f"add task zz{token}", user_id=owner), pool=pool
    )

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM tasks WHERE title ILIKE $1", f"%zz{token}%")
    assert rows, "the specialist should have created the requested task"
    assert all(r["user_id"] == owner for r in rows)
