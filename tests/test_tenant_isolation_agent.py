"""
Regression tests (WS-A: T-001, T-002, T-027) for agent-tool tenant isolation.

Two distinct owners A and B. B must not read or change A's tasks through
``apply_triage_plan`` or ``assess_feasibility``, directly or through
``execute_confirmed_actions``, and guests must not run guest-banned tools on the confirmed path.

Needs the local test Postgres (same fixtures as tests/test_tenant_isolation_hardening.py).
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from backend.agent import execute_confirmed_actions
from backend.memory import structured
from backend.memory.db import get_pool
from backend.routers.auth import create_session
from backend.skills import SKILL_REGISTRY


def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}


def _user(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _make_task(client: AsyncClient, user_id: str, title: str = "A private task") -> int:
    res = await client.post("/api/tasks", json={"title": title, "domain": "hackathon"}, headers=_auth(user_id))
    assert res.status_code == 200, res.text
    return int(res.json()["id"])


async def _status(task_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM tasks WHERE id = $1", task_id)


def test_only_one_apply_triage_plan_handler_is_registered():
    """The duplicate in handlers/specialist.py (imported last) used to overwrite the scoped one."""
    from backend.skills.handlers import feasibility, specialist

    assert SKILL_REGISTRY["apply_triage_plan"] is feasibility.handle_apply_triage_plan
    assert SKILL_REGISTRY["assess_feasibility"] is feasibility.handle_assess_feasibility
    assert not hasattr(specialist, "handle_apply_triage_plan")
    assert not hasattr(specialist, "handle_assess_feasibility")


@pytest.mark.asyncio
async def test_apply_triage_plan_direct_cannot_touch_foreign_tasks(client: AsyncClient):
    a, b = _user("alice"), _user("bob")
    a_task = await _make_task(client, a)
    b_task = await _make_task(client, b, "B's own task")
    pool = await get_pool()

    res = await SKILL_REGISTRY["apply_triage_plan"](
        {"user_id": b, "drop_ids": [a_task, b_task], "defer_ids": []}, pool
    )

    assert await _status(a_task) == "open"
    assert await _status(b_task) == "done"
    assert res["data"]["skipped_ids"] == [a_task]
    assert [c["id"] for c in res["data"]["changed"]] == [b_task]


@pytest.mark.asyncio
async def test_apply_triage_plan_requires_user_id(client: AsyncClient):
    a = _user("alice")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    res = await SKILL_REGISTRY["apply_triage_plan"]({"drop_ids": [a_task]}, pool)

    assert res["success"] is False
    assert await _status(a_task) == "open"


@pytest.mark.asyncio
async def test_apply_triage_plan_via_confirmed_actions_cannot_touch_foreign_tasks(client: AsyncClient):
    a, b = _user("alice"), _user("bob")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    results = await execute_confirmed_actions(
        [{"tool": "apply_triage_plan", "args": {"drop_ids": [a_task], "user_id": a}}],
        pool,
        approved_by="user",
        user_id=b,
    )

    assert results and results[0]["status"] == "success"
    assert results[0]["result"]["data"]["changed"] == []
    assert await _status(a_task) == "open"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["apply_triage_plan", "delete_task", "commit_schedule", "ingest_url"])
async def test_guest_ban_is_enforced_on_confirmed_path(client: AsyncClient, tool: str):
    guest = f"guest_{uuid.uuid4().hex[:8]}"
    pool = await get_pool()

    results = await execute_confirmed_actions(
        [{"tool": tool, "args": {"drop_ids": [1], "task_id": 1}}],
        pool,
        approved_by="user",
        user_id=guest,
    )

    assert results[0]["status"] == "error"
    assert "Guest sessions are forbidden" in results[0]["message"]


@pytest.mark.asyncio
async def test_guest_ban_uses_explicit_is_guest_flag_for_uuid_guests(client: AsyncClient):
    guest_uuid = str(uuid.uuid4())  # no "guest_" prefix, so only the flag identifies it
    pool = await get_pool()

    results = await execute_confirmed_actions(
        [{"tool": "apply_triage_plan", "args": {"drop_ids": [1]}}],
        pool,
        approved_by="user",
        user_id=guest_uuid,
        is_guest=True,
    )

    assert results[0]["status"] == "error"
    assert "Guest sessions are forbidden" in results[0]["message"]


@pytest.mark.asyncio
async def test_assess_feasibility_requires_user_id_and_passes_owner(monkeypatch):
    from backend.skills.handlers import feasibility as feas_handlers

    spy = AsyncMock(side_effect=RuntimeError("stop after capture"))
    monkeypatch.setattr(feas_handlers, "_run_scoped_review", spy)
    handler = SKILL_REGISTRY["assess_feasibility"]

    missing = await handler({"days": 3}, object())
    assert missing["success"] is False
    spy.assert_not_called()

    await handler({"days": 3, "user_id": "owner-b", "include_demo": True}, object())
    assert spy.await_args.kwargs["user_id"] == "owner-b"
    assert spy.await_args.kwargs["include_demo"] is True


@pytest.mark.asyncio
async def test_feasibility_task_fetch_only_returns_the_callers_tasks(client: AsyncClient):
    from backend.agents.feasibility import _fetch_open_tasks

    a, b = _user("alice"), _user("bob")
    a_task = await _make_task(client, a, "A only")
    pool = await get_pool()

    b_tasks = await _fetch_open_tasks(pool, domain=None, user_id=b)
    assert a_task not in {t["id"] for t in b_tasks}
    assert await _fetch_open_tasks(pool, domain=None, user_id=None) == []


@pytest.mark.asyncio
async def test_list_tasks_refuses_null_owner_unless_all_tenants(client: AsyncClient):
    a = _user("alice")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    async with pool.acquire() as conn:
        assert await structured.list_tasks(conn, user_id=None, include_demo=False) == []
        everyone = await structured.list_tasks(conn, include_demo=False, all_tenants=True)
        assert a_task in {t["id"] for t in everyone}


@pytest.mark.asyncio
async def test_update_task_status_with_owner_does_not_touch_foreign_task(client: AsyncClient):
    a, b = _user("alice"), _user("bob")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    async with pool.acquire() as conn:
        assert await structured.update_task_status(conn, a_task, "done", owner_id=b) is None
    assert await _status(a_task) == "open"


# ---------------------------------------------------------------------------
# Round 2: handlers fail closed without a caller; confirm route passes is_guest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["update_task_status", "edit_task", "delete_task"])
async def test_task_mutation_handlers_require_user_id(client: AsyncClient, tool: str):
    a = _user("alice")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    for missing in ({}, {"user_id": ""}, {"user_id": None}):
        args = {"task_id": a_task, "status": "done", "title": "hijacked", **missing}
        res = await SKILL_REGISTRY[tool](args, pool)
        assert "user_id required" in res["response"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, title, deleted_at FROM tasks WHERE id = $1", a_task)
    assert row["status"] == "open"
    assert row["title"] == "A private task"
    assert row["deleted_at"] is None


@pytest.mark.asyncio
async def test_task_mutation_handlers_still_work_for_the_owner_and_admin(client: AsyncClient):
    a = _user("alice")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    own = await SKILL_REGISTRY["update_task_status"]({"task_id": a_task, "status": "done", "user_id": a}, pool)
    assert own["data"]["status"] == "done"

    admin = await SKILL_REGISTRY["update_task_status"]({"task_id": a_task, "status": "open", "user_id": "admin"}, pool)
    assert admin["data"]["status"] == "open"


@pytest.mark.asyncio
async def test_add_task_shift_existing_requires_user_id(client: AsyncClient):
    a = _user("alice")
    title = f"Shift target {uuid.uuid4().hex[:6]}"
    pool = await get_pool()
    created = await SKILL_REGISTRY["add_task"]({"title": title, "due_date": "2030-01-01", "user_id": a}, pool)
    task_id = created["data"]["id"]

    # No user_id: add_task is rejected up front (it must not create an ownerless task or shift anything).
    res = await SKILL_REGISTRY["add_task"](
        {"title": title, "due_date": "2030-02-02", "shift_existing": True}, pool
    )
    assert "user_id required" in res["response"]
    assert res["data"] == {"error": "user_id required"}
    async with pool.acquire() as conn:
        due = await conn.fetchval("SELECT due_date FROM tasks WHERE id = $1", task_id)
        orphans = await conn.fetchval(
            "SELECT count(*) FROM tasks WHERE title = $1 AND user_id IS NULL", title
        )
    assert str(due) == "2030-01-01"
    assert orphans == 0


@pytest.mark.asyncio
async def test_add_task_without_user_id_creates_no_orphan_row(client: AsyncClient):
    title = f"Orphan check {uuid.uuid4().hex[:6]}"
    pool = await get_pool()
    for args in ({"title": title}, {"title": title, "user_id": ""}, {"title": title, "user_id": None}):
        res = await SKILL_REGISTRY["add_task"](args, pool)
        assert res["data"] == {"error": "user_id required"}
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM tasks WHERE title = $1", title) == 0


@pytest.mark.asyncio
async def test_commit_schedule_requires_user_id(client: AsyncClient):
    a = _user("alice")
    a_task = await _make_task(client, a)
    pool = await get_pool()
    slot = {"start": "2099-01-01T10:00:00+00:00", "end": "2099-01-01T11:00:00+00:00"}

    res = await SKILL_REGISTRY["commit_schedule"]({"assignments": [{"task_id": a_task, **slot}]}, pool)

    assert res["data"]["status"] == "error"
    assert "user_id required" in res["response"]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT scheduled_start FROM tasks WHERE id = $1", a_task) is None


@pytest.mark.asyncio
async def test_confirmed_delete_task_without_caller_cannot_delete(client: AsyncClient):
    a = _user("alice")
    a_task = await _make_task(client, a)
    pool = await get_pool()

    results = await execute_confirmed_actions(
        [{"tool": "delete_task", "args": {"task_id": a_task}}], pool, approved_by="user"
    )

    assert "user_id required" in str(results[0])
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT deleted_at FROM tasks WHERE id = $1", a_task) is None


@pytest.mark.asyncio
async def test_confirm_route_refuses_banned_tool_for_a_real_guest(client: AsyncClient):
    """A real guest (bare-UUID id, signed token) confirming a guest-banned tool is refused and the task survives."""
    from backend.agent_pending import register_pending_action
    from backend.agent import save_agent_run

    mint = await client.post("/api/guest/session")
    assert mint.status_code == 200
    guest_id, guest_token = mint.json()["guest_id"], mint.json()["guest_token"]
    created = await client.post(
        "/api/tasks", json={"title": "Guest task", "domain": "hackathon"}, headers={"x-guest-token": guest_token}
    )
    assert created.status_code == 200, created.text
    task_id = int(created.json()["id"])
    pool = await get_pool()
    run_id = f"run_{uuid.uuid4().hex}"
    args = {"task_id": task_id}
    await save_agent_run(pool, run_id, "goal", "paused", [], [], [{"tool": "delete_task", "args": args}])
    await register_pending_action(pool, run_id, guest_id, "delete_task", args, 300.0)

    res = await client.post("/api/agent/confirm", json={"run_id": run_id}, headers={"x-guest-token": guest_token})

    assert res.status_code == 200, res.text
    result = res.json()["results"][0]
    assert result["status"] == "error"
    assert "Guest sessions are forbidden" in result["message"]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT deleted_at FROM tasks WHERE id = $1", task_id) is None


@pytest.mark.asyncio
async def test_summarize_across_domains_without_user_id_reads_no_chunks(client: AsyncClient):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO memory_chunks (domain, content, user_id, content_hash) VALUES ('code', 'secret-a', $1, $2)",
            _user("alice"),
            uuid.uuid4().hex,
        )
    res = await SKILL_REGISTRY["summarize_across_domains"]({}, pool)
    assert res["data"]["code_chunks_count"] == 0
    assert res["data"]["coursework_chunks_count"] == 0


# ---------------------------------------------------------------------------
# Round 3: projects are listed and fuzzy-matched per owner (no schema change)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_projects_are_owner_scoped_for_listing_and_fuzzy_match(client: AsyncClient):
    a, b = _user("alice"), _user("bob")
    proj_name = f"Alpha{uuid.uuid4().hex[:8]}"
    res = await client.post(
        "/api/tasks",
        json={"title": "Project task", "domain": "code", "project": proj_name},
        headers=_auth(a),
    )
    assert res.status_code == 200, res.text
    pool = await get_pool()

    async with pool.acquire() as conn:
        a_ids = {p["id"] for p in await structured.list_projects(conn, owner_id=a)}
        a_names = {p["name"] for p in await structured.list_projects(conn, owner_id=a)}
        assert proj_name in a_names

        # B cannot list A's project.
        assert proj_name not in {p["name"] for p in await structured.list_projects(conn, owner_id=b)}
        # No owner and no flag: nothing. The cross-tenant flag keeps the old behaviour.
        assert await structured.list_projects(conn) == []
        assert proj_name in {p["name"] for p in await structured.list_projects(conn, all_tenants=True)}

        # Fuzzy match ("<name> extended" contains A's project name): A reuses it, B and anonymous do not.
        fuzzy = f"{proj_name} extended"
        mine = await structured.get_or_create_project(conn, fuzzy, "code", owner_id=a)
        assert mine["id"] in a_ids
        theirs = await structured.get_or_create_project(conn, fuzzy, "code", owner_id=b)
        assert theirs["id"] not in a_ids
        anon = await structured.get_or_create_project(conn, f"{proj_name} anon", "code")
        assert anon["id"] not in a_ids
