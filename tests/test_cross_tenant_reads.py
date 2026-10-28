"""
Regression tests for cross-tenant reads: agent run history, run detail, the memory overview,
the proactive briefing and the specialist agents.

Each test fails against the pre-fix code, where these endpoints returned every tenant's data.
"""

import json
import uuid

import pytest
from httpx import AsyncClient

from backend.agent import save_agent_run
from backend.agents.specialist import SpecialistDispatcher, SpecialistRequest
from backend.memory.db import get_pool
from backend.routers.auth import create_session


def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}


def _user(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _make_run(owner: str, goal: str) -> str:
    pool = await get_pool()
    run_id = f"run_{uuid.uuid4().hex}"
    await save_agent_run(pool, run_id, goal, "completed", [], [], [], user_id=owner)
    return run_id


@pytest.mark.asyncio
async def test_run_history_requires_identity(client: AsyncClient):
    assert (await client.get("/api/agent/runs")).status_code == 401
    assert (await client.get("/api/agent/runs/some_run")).status_code == 401


@pytest.mark.asyncio
async def test_run_history_only_lists_the_callers_runs(client: AsyncClient):
    owner, other = _user("alice"), _user("bob")
    goal = f"Private plan {uuid.uuid4().hex[:8]}"
    run_id = await _make_run(owner, goal)

    mine = await client.get("/api/agent/runs?limit=100", headers=_auth(owner))
    theirs = await client.get("/api/agent/runs?limit=100", headers=_auth(other))
    assert run_id in [r["id"] for r in mine.json()["runs"]]
    assert goal not in theirs.text


@pytest.mark.asyncio
async def test_run_detail_is_owner_only(client: AsyncClient, auth_headers: dict):
    owner, other = _user("alice"), _user("bob")
    run_id = await _make_run(owner, "Detail goal")

    assert (await client.get(f"/api/agent/runs/{run_id}", headers=_auth(owner))).status_code == 200
    assert (await client.get(f"/api/agent/runs/{run_id}", headers=_auth(other))).status_code == 404
    assert (await client.get(f"/api/agent/runs/{run_id}", headers=auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_run_owner_is_fixed_by_the_first_save(client: AsyncClient):
    owner, intruder = _user("alice"), _user("mallory")
    run_id = await _make_run(owner, "Original owner")
    pool = await get_pool()
    await save_agent_run(pool, run_id, "Original owner", "completed", [], [], [], user_id=intruder)

    assert (await client.get(f"/api/agent/runs/{run_id}", headers=_auth(intruder))).status_code == 404
    assert (await client.get(f"/api/agent/runs/{run_id}", headers=_auth(owner))).status_code == 200


@pytest.mark.asyncio
async def test_memory_overview_is_scoped_to_the_caller(client: AsyncClient):
    owner, other = _user("alice"), _user("bob")
    goal = f"Overview goal {uuid.uuid4().hex[:8]}"
    await _make_run(owner, goal)
    task = await client.post("/api/tasks", json={"title": "Mine only", "domain": "hackathon"}, headers=_auth(owner))
    assert task.status_code == 200

    mine = await client.get("/api/memory/overview", headers=_auth(owner))
    theirs = await client.get("/api/memory/overview", headers=_auth(other))
    assert goal in mine.text and mine.json()["total_tasks"] >= 1
    assert goal not in theirs.text
    assert theirs.json()["total_tasks"] == 0


@pytest.mark.asyncio
async def test_proactive_briefing_is_admin_only(client: AsyncClient, auth_headers: dict):
    pool = await get_pool()
    run_id = f"proactive_nightly_{uuid.uuid4().hex[:8]}"
    await save_agent_run(pool, run_id, "Nightly Proactive Consolidation", "completed", [], [], [])

    anonymous = await client.get("/api/agent/proactive-briefing")
    user = await client.get("/api/agent/proactive-briefing", headers=_auth(_user("alice")))
    admin = await client.get("/api/agent/proactive-briefing", headers=auth_headers)
    assert anonymous.json()["found"] is False
    assert user.json()["found"] is False
    assert admin.json()["found"] is True


@pytest.mark.asyncio
async def test_specialist_agents_only_see_the_callers_tasks(client: AsyncClient, monkeypatch):
    async def offline(args, pool):
        return {"response": "", "data": {}}

    # No outbound web search or embedding calls in tests.
    monkeypatch.setattr("backend.skills.handle_search_web", offline)
    monkeypatch.setattr("backend.skills.handle_query_code_context", offline)
    owner, other = _user("alice"), _user("bob")
    title = f"Confidential deliverable {uuid.uuid4().hex[:8]}"
    res = await client.post("/api/tasks", json={"title": title, "domain": "hackathon"}, headers=_auth(owner))
    assert res.status_code == 200

    pool = await get_pool()
    for capability in ("calendar", "research", "memory"):
        seen_by_owner = await SpecialistDispatcher.dispatch(
            SpecialistRequest(capability=capability, user_goal="what is due", user_id=owner), pool=pool
        )
        seen_by_other = await SpecialistDispatcher.dispatch(
            SpecialistRequest(capability=capability, user_goal="what is due", user_id=other), pool=pool
        )
        assert title not in json.dumps(seen_by_other.model_dump(), default=str), capability
        if capability == "calendar":
            assert title in json.dumps(seen_by_owner.model_dump(), default=str)
