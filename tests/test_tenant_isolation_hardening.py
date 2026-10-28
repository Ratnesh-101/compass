"""
Regression tests for cross-tenant access on calendar, dependency, verify, confirm and undo endpoints.

Each test fails against the pre-fix code, where these routes accepted anonymous callers or acted on
any task id regardless of who owned it.
"""

import uuid

import pytest
from httpx import AsyncClient

from backend.agent import execute_confirmed_actions, save_agent_run
from backend.agent_pending import register_pending_action
from backend.agent_persistence import record_audit_log
from backend.memory.db import get_pool
from backend.routers.auth import create_session


def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}


def _user(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _make_task(client: AsyncClient, user_id: str, title: str = "Private task") -> int:
    res = await client.post("/api/tasks", json={"title": title, "domain": "hackathon"}, headers=_auth(user_id))
    assert res.status_code == 200, res.text
    return int(res.json()["id"])


async def _task_row(task_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT scheduled_start, deleted_at, status FROM tasks WHERE id = $1", task_id
        )


SLOT = {"scheduled_start": "2031-03-01T09:00:00Z", "scheduled_end": "2031-03-01T10:00:00Z"}


# ---------------------------------------------------------------------------
# Anonymous callers are rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/calendar/availability", None),
        ("GET", "/api/schedule/conflicts", None),
        ("POST", "/api/schedule/propose", {}),
        ("POST", "/api/schedule/commit", {"assignments": []}),
        ("POST", "/api/schedule/reactive-check", {}),
        ("GET", "/api/calendar/preferences", None),
        ("PUT", "/api/calendar/preferences", {"buffer_minutes": 5}),
        ("GET", "/api/tasks/1/dependencies", None),
        ("POST", "/api/tasks/1/dependencies", {"depends_on_task_id": 2}),
        ("DELETE", "/api/tasks/1/dependencies/2", None),
        ("POST", "/api/tasks/1/verify", None),
    ],
)
async def test_anonymous_requests_are_rejected(client: AsyncClient, method, path, body):
    res = await client.request(method, path, json=body)
    assert res.status_code == 401, f"{method} {path} -> {res.status_code} {res.text[:200]}"


# ---------------------------------------------------------------------------
# Calendar / schedule
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_commit_schedule_cannot_touch_another_users_task(client: AsyncClient):
    owner, intruder = _user("alice"), _user("mallory")
    task_id = await _make_task(client, owner)

    res = await client.post(
        "/api/schedule/commit",
        json={"assignments": [{"task_id": task_id, **SLOT}]},
        headers=_auth(intruder),
    )
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["committed_count"] == 0
    assert data["rejected_task_ids"] == [task_id]
    assert (await _task_row(task_id))["scheduled_start"] is None


@pytest.mark.asyncio
async def test_commit_schedule_still_works_for_the_owner(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner)

    res = await client.post(
        "/api/schedule/commit",
        json={"assignments": [{"task_id": task_id, **SLOT}]},
        headers=_auth(owner),
    )
    assert res.status_code == 200
    assert res.json()["data"]["committed_count"] == 1
    assert (await _task_row(task_id))["scheduled_start"] is not None


@pytest.mark.asyncio
async def test_availability_and_conflicts_hide_other_users_tasks(client: AsyncClient):
    owner, other = _user("alice"), _user("bob")
    title = f"Secret launch plan {uuid.uuid4().hex[:6]}"
    task_id = await _make_task(client, owner, title)
    commit = await client.post(
        "/api/schedule/commit",
        json={"assignments": [{"task_id": task_id, **SLOT}]},
        headers=_auth(owner),
    )
    assert commit.json()["data"]["committed_count"] == 1

    window = "start_date=2031-02-27&end_date=2031-03-03"
    mine = await client.get(f"/api/calendar/availability?{window}", headers=_auth(owner))
    assert title in mine.text

    for path in ("/api/calendar/availability", "/api/schedule/conflicts"):
        theirs = await client.get(f"{path}?{window}", headers=_auth(other))
        assert theirs.status_code == 200
        assert title not in theirs.text


@pytest.mark.asyncio
async def test_propose_schedule_does_not_return_other_users_tasks(client: AsyncClient):
    owner, other = _user("alice"), _user("bob")
    title = f"Confidential roadmap {uuid.uuid4().hex[:6]}"
    task_id = await _make_task(client, owner, title)

    res = await client.post("/api/schedule/propose", json={"task_ids": [task_id]}, headers=_auth(other))
    assert res.status_code == 200
    assert title not in res.text


@pytest.mark.asyncio
async def test_calendar_preferences_are_per_user(client: AsyncClient):
    first, second = _user("alice"), _user("bob")
    put = await client.put("/api/calendar/preferences", json={"buffer_minutes": 47}, headers=_auth(first))
    assert put.status_code == 200

    mine = await client.get("/api/calendar/preferences", headers=_auth(first))
    theirs = await client.get("/api/calendar/preferences", headers=_auth(second))
    assert mine.json()["buffer_minutes"] == 47
    assert theirs.json()["buffer_minutes"] != 47


@pytest.mark.asyncio
async def test_reactive_check_only_reports_the_callers_tasks(client: AsyncClient):
    owner, other = _user("alice"), _user("bob")
    title = f"Slipped report {uuid.uuid4().hex[:6]}"
    task_id = await _make_task(client, owner, title)
    await client.post(
        "/api/schedule/commit",
        json={"assignments": [{"task_id": task_id, **SLOT}]},
        headers=_auth(owner),
    )

    res = await client.post(
        "/api/schedule/reactive-check",
        json={"current_time": "2031-06-01T00:00:00Z"},
        headers=_auth(other),
    )
    assert res.status_code == 200
    assert title not in res.text


# ---------------------------------------------------------------------------
# Dependencies and verify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dependency_endpoints_reject_foreign_tasks(client: AsyncClient):
    owner, intruder = _user("alice"), _user("mallory")
    parent = await _make_task(client, owner, "Parent")
    child = await _make_task(client, owner, "Child")
    mine = await _make_task(client, intruder, "Mine")

    ok = await client.post(f"/api/tasks/{child}/dependencies", json={"depends_on_task_id": parent}, headers=_auth(owner))
    assert ok.status_code == 200

    assert (await client.get(f"/api/tasks/{child}/dependencies", headers=_auth(intruder))).status_code == 404
    link_own_to_foreign = await client.post(
        f"/api/tasks/{mine}/dependencies", json={"depends_on_task_id": parent}, headers=_auth(intruder)
    )
    assert link_own_to_foreign.status_code == 404
    link_foreign = await client.post(
        f"/api/tasks/{child}/dependencies", json={"depends_on_task_id": mine}, headers=_auth(intruder)
    )
    assert link_foreign.status_code == 404
    delete = await client.delete(f"/api/tasks/{child}/dependencies/{parent}", headers=_auth(intruder))
    assert delete.status_code == 404

    still = await client.get(f"/api/tasks/{child}/dependencies", headers=_auth(owner))
    assert still.status_code == 200 and len(still.json()) == 1


@pytest.mark.asyncio
async def test_verify_task_rejects_foreign_task(client: AsyncClient):
    owner, intruder = _user("alice"), _user("mallory")
    task_id = await _make_task(client, owner, "Verify me")
    res = await client.post(f"/api/tasks/{task_id}/verify", headers=_auth(intruder))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# /agent/confirm
# ---------------------------------------------------------------------------

async def _stage_delete(owner: str, task_id: int, timeout_seconds: float = 300.0) -> str:
    pool = await get_pool()
    run_id = f"run_{uuid.uuid4().hex}"
    args = {"task_id": task_id}
    await save_agent_run(pool, run_id, "goal", "paused", [], [], [{"tool": "delete_task", "args": args}])
    await register_pending_action(pool, run_id, owner, "delete_task", args, timeout_seconds)
    return run_id


@pytest.mark.asyncio
async def test_confirm_rejects_a_run_owned_by_someone_else(client: AsyncClient):
    owner, intruder = _user("alice"), _user("mallory")
    task_id = await _make_task(client, owner)
    run_id = await _stage_delete(owner, task_id)

    res = await client.post("/api/agent/confirm", json={"run_id": run_id}, headers=_auth(intruder))
    assert res.status_code == 403
    assert (await _task_row(task_id))["deleted_at"] is None


@pytest.mark.asyncio
async def test_confirm_rejects_tampered_arguments(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner)
    other_task = await _make_task(client, owner, "Do not touch")
    run_id = await _stage_delete(owner, task_id)

    res = await client.post(
        "/api/agent/confirm",
        json={"run_id": run_id, "actions": [{"tool": "delete_task", "args": {"task_id": other_task}}]},
        headers=_auth(owner),
    )
    assert res.status_code == 400
    assert (await _task_row(other_task))["deleted_at"] is None
    assert (await _task_row(task_id))["deleted_at"] is None


@pytest.mark.asyncio
async def test_confirm_rejects_expired_proposals(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner)
    run_id = await _stage_delete(owner, task_id, timeout_seconds=0)

    res = await client.post("/api/agent/confirm", json={"run_id": run_id}, headers=_auth(owner))
    assert res.status_code == 410
    assert (await _task_row(task_id))["deleted_at"] is None


@pytest.mark.asyncio
async def test_confirm_executes_stored_action_once(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner)
    run_id = await _stage_delete(owner, task_id)

    first = await client.post(
        "/api/agent/confirm",
        json={"run_id": run_id, "actions": [{"tool": "delete_task", "args": {"task_id": task_id}}]},
        headers=_auth(owner),
    )
    assert first.status_code == 200, first.text
    assert (await _task_row(task_id))["deleted_at"] is not None

    pool = await get_pool()
    async with pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM pending_actions WHERE run_id = $1", run_id)
    assert status == "executed"

    replay = await client.post("/api/agent/confirm", json={"run_id": run_id}, headers=_auth(owner))
    assert replay.status_code in (400, 409)


@pytest.mark.asyncio
async def test_confirm_requires_a_run_id(client: AsyncClient):
    res = await client.post(
        "/api/agent/confirm",
        json={"run_id": "", "actions": [{"tool": "delete_task", "args": {"task_id": 1}}]},
        headers=_auth(_user("mallory")),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_confirmed_actions_ignore_client_supplied_owner(client: AsyncClient):
    owner, intruder = _user("alice"), _user("mallory")
    task_id = await _make_task(client, owner)
    pool = await get_pool()

    results = await execute_confirmed_actions(
        [{"tool": "delete_task", "args": {"task_id": task_id, "user_id": owner}}],
        pool,
        approved_by="user",
        user_id=intruder,
    )
    assert results
    assert (await _task_row(task_id))["deleted_at"] is None


# ---------------------------------------------------------------------------
# /agent/undo
# ---------------------------------------------------------------------------

async def _audit_add_task(owner: str, task_id: int) -> int:
    pool = await get_pool()
    return await record_audit_log(
        pool,
        tool="add_task",
        args={"title": "t", "user_id": owner},
        run_id=f"run_{uuid.uuid4().hex}",
        affected_id=task_id,
        previous_state=None,
        approved_by="user",
    )


@pytest.mark.asyncio
async def test_empty_undo_only_reverts_the_callers_own_action(client: AsyncClient):
    victim, attacker = _user("alice"), _user("mallory")
    task_id = await _make_task(client, victim)
    audit_id = await _audit_add_task(victim, task_id)

    res = await client.post("/api/agent/undo", json={}, headers=_auth(attacker))
    assert res.status_code == 200
    assert res.json()["status"] == "error"
    assert (await _task_row(task_id)) is not None

    pool = await get_pool()
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT is_reverted FROM agent_audit_log WHERE id = $1", audit_id) is False


@pytest.mark.asyncio
async def test_undo_by_foreign_audit_id_is_forbidden(client: AsyncClient):
    victim, attacker = _user("alice"), _user("mallory")
    task_id = await _make_task(client, victim)
    audit_id = await _audit_add_task(victim, task_id)

    res = await client.post("/api/agent/undo", json={"audit_log_id": audit_id}, headers=_auth(attacker))
    assert res.status_code == 403
    assert (await _task_row(task_id)) is not None


@pytest.mark.asyncio
async def test_owner_can_undo_their_own_action(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner)
    await _audit_add_task(owner, task_id)

    res = await client.post("/api/agent/undo", json={}, headers=_auth(owner))
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert (await _task_row(task_id)) is None


@pytest.mark.asyncio
async def test_undoing_a_delete_restores_the_soft_deleted_task(client: AsyncClient):
    owner = _user("alice")
    task_id = await _make_task(client, owner, "Come back")
    pool = await get_pool()

    results = await execute_confirmed_actions(
        [{"tool": "delete_task", "args": {"task_id": task_id}}], pool, approved_by="user", user_id=owner
    )
    assert results[0].get("status") != "error"
    assert (await _task_row(task_id))["deleted_at"] is not None

    res = await client.post("/api/agent/undo", json={}, headers=_auth(owner))
    assert res.json()["status"] == "ok", res.text
    row = await _task_row(task_id)
    assert row is not None and row["deleted_at"] is None
