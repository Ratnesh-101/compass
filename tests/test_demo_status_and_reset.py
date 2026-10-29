"""
Compass — Judge Persona reset must clear demo memories too, and /api/demo/status
must report whether demo tasks are still held by the caller.
"""

import uuid

import pytest

from backend.memory.db import get_pool
from backend.routers.tasks_verification import (
    DEMO_MEMORY_SOURCE,
    clear_demo_memories,
    demo_status_endpoint,
)

ZERO_EMBEDDING = [0.0] * 768


class _FakeRequest:
    """Minimal stand-in; identity is injected through request.state.identity."""

    def __init__(self, identity):
        self.state = type("S", (), {"identity": identity})()
        self.headers = {}
        self.cookies = {}


async def _insert_memory(conn, user_id, content, source):
    return await conn.fetchval(
        """
        INSERT INTO memory_chunks (domain, content, embedding, source, tags, user_id)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
        """,
        "general", content, ZERO_EMBEDDING, source, ["t"], user_id,
    )


@pytest.mark.asyncio
async def test_clear_demo_memories_only_removes_persona_rows_for_that_user():
    pool = await get_pool()
    assert pool is not None, "Database pool must be available"
    tenant_a = f"guest_mem_a_{uuid.uuid4().hex[:10]}"
    tenant_b = f"guest_mem_b_{uuid.uuid4().hex[:10]}"

    async with pool.acquire() as conn:
        try:
            persona_a = await _insert_memory(conn, tenant_a, f"persona a {uuid.uuid4().hex}", DEMO_MEMORY_SOURCE)
            real_a = await _insert_memory(conn, tenant_a, f"real a {uuid.uuid4().hex}", "chat")
            persona_b = await _insert_memory(conn, tenant_b, f"persona b {uuid.uuid4().hex}", DEMO_MEMORY_SOURCE)

            deleted = await clear_demo_memories(conn, tenant_a)
            assert deleted == 1

            remaining = {r["id"] for r in await conn.fetch(
                "SELECT id FROM memory_chunks WHERE user_id = ANY($1::text[])", [tenant_a, tenant_b]
            )}
            assert persona_a not in remaining
            assert real_a in remaining, "A user's own memories must survive a demo reset"
            assert persona_b in remaining, "Another tenant's persona memories must be untouched"

            assert await clear_demo_memories(conn, "") == 0
            assert await clear_demo_memories(conn, tenant_a) == 0, "Second reset is a no-op"
        finally:
            await conn.execute("DELETE FROM memory_chunks WHERE user_id = ANY($1::text[])", [tenant_a, tenant_b])


@pytest.mark.asyncio
async def test_demo_status_reports_only_callers_live_persona_tasks():
    from backend.dependencies import Identity

    pool = await get_pool()
    assert pool is not None, "Database pool must be available"
    tenant_a = f"guest_status_a_{uuid.uuid4().hex[:10]}"
    tenant_b = f"guest_status_b_{uuid.uuid4().hex[:10]}"
    ident_a = Identity(id=tenant_a, is_guest=True, guest_id=tenant_a)

    async with pool.acquire() as conn:
        try:
            before = await demo_status_endpoint(_FakeRequest(ident_a))
            assert before == {"active": False, "task_count": 0}

            await conn.execute(
                "INSERT INTO tasks (title, domain, user_id, trusted_event_url) VALUES ($1,$2,$3,$4)",
                "Real task", "code", tenant_a, "https://example.org/demo-day",
            )
            await conn.execute(
                "INSERT INTO tasks (title, domain, user_id, trusted_event_url) VALUES ($1,$2,$3,$4)",
                "Persona task", "code", tenant_b, "compass://demo-persona/x",
            )
            assert await demo_status_endpoint(_FakeRequest(ident_a)) == {"active": False, "task_count": 0}

            await conn.execute(
                "INSERT INTO tasks (title, domain, user_id, trusted_event_url) VALUES ($1,$2,$3,$4)",
                "Persona task A", "code", tenant_a, "compass://demo-persona/a1",
            )
            await conn.execute(
                "INSERT INTO tasks (title, domain, user_id, trusted_event_url, deleted_at) VALUES ($1,$2,$3,$4, now())",
                "Deleted persona task A", "code", tenant_a, "compass://demo-persona/a2",
            )
            assert await demo_status_endpoint(_FakeRequest(ident_a)) == {"active": True, "task_count": 1}
        finally:
            await conn.execute("DELETE FROM tasks WHERE user_id = ANY($1::text[])", [tenant_a, tenant_b])


def test_no_identity_means_inactive():
    import asyncio

    assert asyncio.run(demo_status_endpoint(_FakeRequest(None))) == {"active": False, "task_count": 0}
