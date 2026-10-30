import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.agent_types import _PENDING_CONFIRMATION_EVENTS


@pytest.mark.asyncio
async def test_cross_user_agent_run_active_confirmation_hijack():
    # User A starts a run that waits for confirmation
    user_a_id = "user_victim_a"
    user_b_id = "user_attacker_b"
    run_id = "run_victim_active_123"

    evt = asyncio.Event()
    outcome = {"owner": user_a_id}
    _PENDING_CONFIRMATION_EVENTS[run_id] = (evt, outcome)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # User B attempts to approve User A's active run
            resp = await client.post(
                "/api/agent/run",
                json={"run_id": run_id, "action": "approve", "goal": "sensitive action"},
                headers={"x-user-id": user_b_id},
            )
            assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
            assert not evt.is_set()
    finally:
        _PENDING_CONFIRMATION_EVENTS.pop(run_id, None)


@pytest.mark.asyncio
async def test_cross_user_agent_run_db_resume_hijack():
    # Attempting to resume User A's run as User B
    user_a_id = "user_victim_a"
    user_b_id = "user_attacker_b"
    run_id = "run_victim_stored_456"

    from backend.memory.db import get_pool
    from backend.agent import save_agent_run
    pool = await get_pool()
    if pool:
        await save_agent_run(
            pool,
            run_id=run_id,
            goal="sensitive action",
            status="paused",
            accumulated_steps=[],
            messages=[],
            pending_actions=[{"tool": "delete_task", "args": {"task_id": 1}}],
            user_id=user_a_id,
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/agent/run",
                json={"run_id": run_id, "action": "approve", "goal": "sensitive action"},
                headers={"x-user-id": user_b_id},
            )
            assert resp.status_code in (403, 404), f"Expected 403 or 404, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_cross_user_agent_get_run_isolated():
    user_a_id = "user_victim_a"
    user_b_id = "user_attacker_b"
    run_id = "run_victim_inspect_789"

    from backend.memory.db import get_pool
    from backend.agent import save_agent_run
    pool = await get_pool()
    if pool:
        await save_agent_run(
            pool,
            run_id=run_id,
            goal="private workflow",
            status="completed",
            accumulated_steps=[],
            messages=[],
            pending_actions=[],
            user_id=user_a_id,
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # User B attempts to inspect User A's run
            resp = await client.get(
                f"/api/agent/runs/{run_id}",
                headers={"x-user-id": user_b_id},
            )
            assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

            # User A can inspect own run
            resp_owner = await client.get(
                f"/api/agent/runs/{run_id}",
                headers={"x-user-id": user_a_id},
            )
            assert resp_owner.status_code == 200, f"Expected 200, got {resp_owner.status_code}: {resp_owner.text}"
