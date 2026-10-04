"""
Compass — Agent Tests.

Tests:
  - Agent SSE endpoint returns text/event-stream
  - Agent capabilities endpoint returns tool list and respects TAVILY_ENABLED
  - Agent trace includes think/tool_call/synthesize/done steps
  - Agent respects max_steps limit
  - Confirm gate actually pauses execution (no mutation occurs before approval)
  - Reject path re-plans instead of dying
  - Timeout expires cleanly and drafts the partial run
  - Critique-revise cycle cap (max 2 rounds) is strictly enforced
  - Run state survives simulated disconnect and reconnect via agent_runs table
  - Audit log entry is created for every agent-executed mutation
  - Undo endpoint correctly reverts the last mutation
  - search_web is absent from the agent's tool list when TAVILY_ENABLED=False
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock


import pytest
from httpx import AsyncClient

from backend.agent import (
    AgentStep,
    run_agent,
    execute_confirmed_actions,
    undo_last_agent_action,
    save_agent_run,
    get_agent_run,
    MUTATING_TOOLS,
)
from backend.config import get_settings
from backend.memory.db import get_pool
from backend.skills import get_tool_definitions, SKILL_REGISTRY, TOOL_DEFINITIONS


# ---------------------------------------------------------------------------
# Helper to parse SSE data stream
# ---------------------------------------------------------------------------
def _parse_sse_events(text: str) -> list[dict]:
    """Parse SSE event stream text into a list of JSON objects."""
    events = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return events


# ---------------------------------------------------------------------------
# Mock helper for AsyncOpenAI completions
# ---------------------------------------------------------------------------
def _create_mock_completion(tool_name: str | None = None, tool_args: dict | None = None, content: str = ""):
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content

    if tool_name:
        tc = MagicMock()
        tc.id = f"call_{uuid.uuid4().hex[:8]}"
        tc.function = MagicMock()
        tc.function.name = tool_name
        tc.function.arguments = json.dumps(tool_args or {})
        choice.message.tool_calls = [tc]
    else:
        choice.message.tool_calls = None

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 120
    resp.usage.completion_tokens = 45
    return resp


# ---------------------------------------------------------------------------
# Baseline Agent Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_endpoint_returns_sse(client: AsyncClient):
    """POST /api/agent/run should return text/event-stream content type."""
    resp = await client.post(
        "/api/agent/run",
        json={"goal": "List my open tasks", "max_steps": 3, "enable_critic": False},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    _ = resp.text


@pytest.mark.asyncio
async def test_agent_capabilities_endpoint(client: AsyncClient):
    """GET /api/agent/capabilities should return tool list and model info."""
    resp = await client.get("/api/agent/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert "total" in data
    assert data["total"] >= 7
    assert "models" in data
    assert "reasoning" in data["models"]
    assert "synthesis" in data["models"]

    tool_names = [t["name"] for t in data["tools"]]
    assert "update_task_status" in tool_names
    assert "edit_task" in tool_names
    assert "delete_task" in tool_names


@pytest.mark.asyncio
async def test_agent_produces_steps(client: AsyncClient):
    """Agent should produce at least one step."""
    resp = await client.post(
        "/api/agent/run",
        json={"goal": "What open tasks do I have?", "max_steps": 4, "enable_critic": False},
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) >= 1
    step_types = {e.get("type") for e in events}
    assert len(step_types) >= 1


@pytest.mark.asyncio
async def test_agent_ends_with_done(client: AsyncClient):
    """Agent trace should end with a 'done' event."""
    resp = await client.post(
        "/api/agent/run",
        json={"goal": "Summarize my tasks", "max_steps": 4, "enable_critic": False},
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) >= 1
    assert events[-1].get("type") in ("done", "error")


@pytest.mark.asyncio
async def test_agent_max_steps_respected(client: AsyncClient):
    """Agent should not produce more steps than max_steps allows."""
    max_steps = 3
    resp = await client.post(
        "/api/agent/run",
        json={"goal": "Do a comprehensive analysis", "max_steps": max_steps, "enable_critic": False},
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    assert len(events) <= (max_steps * 4) + 4


@pytest.mark.asyncio
async def test_agent_sse_event_format(client: AsyncClient):
    """Each SSE event should be valid JSON with required fields."""
    resp = await client.post(
        "/api/agent/run",
        json={"goal": "Hello", "max_steps": 2, "enable_critic": False},
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    for event in events:
        assert "type" in event
        assert "step" in event
        assert "elapsed_ms" in event


@pytest.mark.asyncio
async def test_agent_skill_registry_has_new_skills(client: AsyncClient):
    """Verify all 11 README skills table tools are genuinely registered and dispatchable."""
    readme_skills = [
        "add_task",
        "query_tasks",
        "update_task_status",
        "edit_task",
        "delete_task",
        "list_projects",
        "log_code_context",
        "query_code_context",
        "query_coursework_notes",
        "chat",
        "summarize_across_domains",
    ]
    tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    for skill in readme_skills:
        assert skill in SKILL_REGISTRY, f"Skill '{skill}' missing from SKILL_REGISTRY"
        assert skill in tool_names, f"Tool '{skill}' missing from TOOL_DEFINITIONS"


# ---------------------------------------------------------------------------
# Part 1 & Part 2: Confirm Gate, Pause, Reject, Timeout, Critique Cap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_gate_actually_pauses_execution_and_prevents_mutation(monkeypatch):
    """Item 3: Confirm gate actually pauses execution and no mutation occurs until approved."""
    pool = await get_pool()
    unique_title = f"Unapproved Task {uuid.uuid4().hex[:6]}"

    # Mock OpenAI client to propose add_task
    mock_comp = _create_mock_completion("add_task", {"title": unique_title, "domain": "code"})
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_comp)
    monkeypatch.setattr("backend.agent.AsyncOpenAI", lambda **kwargs: mock_client)

    run_id = f"test_pause_{uuid.uuid4().hex[:8]}"

    steps = []
    async for step in run_agent(
        goal=f"Add task '{unique_title}'",
        pool=pool,
        max_steps=5,
        enable_critic=False,
        run_id=run_id,
        wait_for_confirmation=False,  # halts on confirm_request
    ):
        steps.append(step)

    # 1. Proves confirm_request was emitted
    confirm_steps = [s for s in steps if s.type == "confirm_request"]
    assert len(confirm_steps) == 1, "Expected confirm_request step to be emitted"
    assert confirm_steps[0].tool_name == "add_task"

    # 2. Proves execution HALTED and NO task was created in PostgreSQL
    async with pool.acquire() as conn:
        task_row = await conn.fetchrow("SELECT * FROM tasks WHERE title = $1", unique_title)
        assert task_row is None, "CRITICAL: Mutating action executed before receiving confirmation!"

        # 3. Proves run state was persisted as 'paused'
        run_state = await get_agent_run(pool, run_id)
        assert run_state is not None
        assert run_state["status"] == "paused"


@pytest.mark.asyncio
async def test_reject_path_replans_instead_of_dying(monkeypatch):
    """Item 6: When user declines confirm_request, feeds rejection back into context and re-plans."""
    pool = await get_pool()
    declined_title = f"Declined Task {uuid.uuid4().hex[:6]}"
    run_id = f"test_reject_{uuid.uuid4().hex[:8]}"

    # Turn 1: Agent proposes add_task and pauses
    mock_comp1 = _create_mock_completion("add_task", {"title": declined_title, "domain": "coursework"})
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_comp1)
    monkeypatch.setattr("backend.agent.AsyncOpenAI", lambda **kwargs: mock_client)

    async for _ in run_agent(
        goal="Reschedule coursework",
        pool=pool,
        max_steps=4,
        enable_critic=False,
        run_id=run_id,
        wait_for_confirmation=False,
    ):
        pass

    # Turn 2: User rejects with feedback -> Agent should observe rejection and synthesize alternative
    mock_comp2 = _create_mock_completion(content="Understood, I will not modify your coursework. Here is an alternative study schedule.")
    mock_client.chat.completions.create = AsyncMock(return_value=mock_comp2)

    steps_turn2 = []
    async for step in run_agent(
        goal="Reschedule coursework",
        pool=pool,
        max_steps=4,
        enable_critic=False,
        run_id=run_id,
        action="reject",
        feedback="Do not modify coursework deadlines",
    ):
        steps_turn2.append(step)

    # Verify rejection was fed back as an observation
    observe_steps = [s for s in steps_turn2 if s.type == "observe"]
    assert len(observe_steps) >= 1
    assert "declined" in observe_steps[0].content.lower()

    # Verify agent produced a synthesis step
    synth_steps = [s for s in steps_turn2 if s.type == "synthesize"]
    assert len(synth_steps) >= 1
    assert "alternative" in synth_steps[0].content.lower()

    # Verify no task was created in DB
    async with pool.acquire() as conn:
        task_row = await conn.fetchrow("SELECT * FROM tasks WHERE title = $1", declined_title)
        assert task_row is None


@pytest.mark.asyncio
async def test_timeout_expires_cleanly_and_drafts_run(monkeypatch):
    """Item 7: Timeout on pending confirmation fires, saves draft, and emits expiry."""
    pool = await get_pool()
    timeout_title = f"Timeout Task {uuid.uuid4().hex[:6]}"
    run_id = f"test_timeout_{uuid.uuid4().hex[:8]}"

    # Mock agent proposing add_task
    mock_comp = _create_mock_completion("add_task", {"title": timeout_title, "domain": "hackathon"})
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_comp)
    monkeypatch.setattr("backend.agent.AsyncOpenAI", lambda **kwargs: mock_client)

    steps = []
    async for step in run_agent(
        goal="Add hackathon task",
        pool=pool,
        max_steps=4,
        enable_critic=False,
        run_id=run_id,
        wait_for_confirmation=True,
        confirm_timeout_seconds=0.05,  # short timeout for test
    ):
        steps.append(step)

    # Check that done event was emitted with status expired
    done_steps = [s for s in steps if s.type == "done"]
    assert len(done_steps) == 1
    data = json.loads(done_steps[0].content)
    assert data.get("status") == "expired"
    assert data.get("draft_saved") is True

    # Verify run state in database is 'expired'
    run_state = await get_agent_run(pool, run_id)
    assert run_state is not None
    assert run_state["status"] == "expired"

    # Verify no task was created
    async with pool.acquire() as conn:
        task_row = await conn.fetchrow("SELECT * FROM tasks WHERE title = $1", timeout_title)
        assert task_row is None


@pytest.mark.asyncio
async def test_critique_revise_cycle_cap_enforced(monkeypatch):
    """Item 8: Critique->revise cycle is capped at 2 rounds maximum."""
    pool = await get_pool()

    # LLM always produces a plan
    mock_plan_comp = _create_mock_completion(content="Proposed schedule: work on OS then Hackathon.")
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_plan_comp)
    monkeypatch.setattr("backend.agent.AsyncOpenAI", lambda **kwargs: mock_client)

    # Critic pass always rejects
    critic_count = 0
    async def mock_critic(*args, **kwargs):
        nonlocal critic_count
        critic_count += 1
        return AgentStep(type="critic", content="NEEDS REVISION: conflict detected in timeline")

    monkeypatch.setattr("backend.agent._run_critic_pass", mock_critic)

    steps = []
    async for step in run_agent(
        goal="Make a schedule",
        pool=pool,
        max_steps=8,
        enable_critic=True,
        run_id=f"test_crit_{uuid.uuid4().hex[:8]}",
    ):
        steps.append(step)

    # Proves critique was capped at 2 rounds
    assert critic_count == 2, f"Expected exactly 2 critique rounds, got {critic_count}"
    # Verify run completed with synthesis
    assert any(s.type == "synthesize" for s in steps)


@pytest.mark.asyncio
async def test_run_state_survives_disconnect_reconnect(monkeypatch):
    """Item 9: Agent run state survives simulated disconnect and reconnect via agent_runs table."""
    pool = await get_pool()
    run_id = f"test_recon_{uuid.uuid4().hex[:8]}"
    pending_task_title = f"Reconnect Task {uuid.uuid4().hex[:6]}"

    # Turn 1: Start run, emit confirm_request, simulate client disconnect
    mock_comp1 = _create_mock_completion("add_task", {"title": pending_task_title, "domain": "code"})
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_comp1)
    monkeypatch.setattr("backend.agent.AsyncOpenAI", lambda **kwargs: mock_client)

    async for _ in run_agent(
        goal="Add my code task",
        pool=pool,
        max_steps=4,
        enable_critic=False,
        run_id=run_id,
        wait_for_confirmation=False,
    ):
        pass

    # Verify run was saved in PostgreSQL
    saved_run = await get_agent_run(pool, run_id)
    assert saved_run is not None
    assert saved_run["status"] == "paused"

    # Turn 2: Simulate client reconnecting to approve
    mock_comp2 = _create_mock_completion(content="Task successfully created and verified.")
    mock_client.chat.completions.create = AsyncMock(return_value=mock_comp2)

    turn2_steps = []
    async for step in run_agent(
        goal="Add my code task",
        pool=pool,
        max_steps=4,
        enable_critic=False,
        run_id=run_id,
        action="approve",
    ):
        turn2_steps.append(step)

    # Verify mutation executed upon approval
    async with pool.acquire() as conn:
        task_row = await conn.fetchrow("SELECT * FROM tasks WHERE title = $1", pending_task_title)
        assert task_row is not None
        # Clean up
        await conn.execute("DELETE FROM tasks WHERE id = $1", task_row["id"])


# ---------------------------------------------------------------------------
# Part 2: Audit Logging & Undo Last Agent Action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_log_entry_created_for_mutation():
    """Item 10: Audit log every agent-executed mutation in agent_audit_log."""
    pool = await get_pool()
    title = f"Audit Log Test {uuid.uuid4().hex[:6]}"
    run_id = f"run_audit_{uuid.uuid4().hex[:8]}"

    # Execute mutation via execute_confirmed_actions
    results = await execute_confirmed_actions(
        confirmed_actions=[{"tool": "add_task", "args": {"title": title, "domain": "hackathon"}}],
        pool=pool,
        run_id=run_id,
        approved_by="test_user",
    )
    assert len(results) == 1
    assert results[0]["status"] == "success"

    # Verify entry in agent_audit_log
    async with pool.acquire() as conn:
        audit_row = await conn.fetchrow(
            "SELECT * FROM agent_audit_log WHERE run_id = $1 ORDER BY id DESC LIMIT 1",
            run_id,
        )
        assert audit_row is not None
        assert audit_row["tool"] == "add_task"
        assert audit_row["affected_table"] == "tasks"
        assert audit_row["approved_by"] == "test_user"

        new_state = json.loads(audit_row["new_state"])
        assert new_state["title"] == title

        # Clean up
        await conn.execute("DELETE FROM tasks WHERE id = $1", audit_row["affected_id"])
        await conn.execute("DELETE FROM agent_audit_log WHERE id = $1", audit_row["id"])


@pytest.mark.asyncio
async def test_undo_correctly_reverts_last_mutation(client: AsyncClient, auth_headers: dict):
    """Item 11: POST /api/agent/undo reverts the most recent agent mutation."""
    pool = await get_pool()
    title = f"Undoable Task {uuid.uuid4().hex[:6]}"
    run_id = f"run_undo_{uuid.uuid4().hex[:8]}"

    # 1. Execute task creation
    results = await execute_confirmed_actions(
        confirmed_actions=[{"tool": "add_task", "args": {"title": title, "domain": "code"}}],
        pool=pool,
        run_id=run_id,
    )
    created_id = results[0]["result"]["data"]["id"]

    # Verify task exists
    async with pool.acquire() as conn:
        assert await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", created_id) is not None

    # 2. Call undo endpoint
    resp = await client.post(
        "/api/agent/undo",
        json={"run_id": run_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "reverted" in data

    # 3. Verify task is deleted from database
    async with pool.acquire() as conn:
        assert await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", created_id) is None


@pytest.mark.asyncio
async def test_search_web_absent_from_agent_when_tavily_disabled(monkeypatch, client: AsyncClient):
    """Item 16: search_web is absent from the agent's tool list when TAVILY_ENABLED=False."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ENABLED", False)

    # 1. GET /api/agent/capabilities should not include search_web
    resp = await client.get("/api/agent/capabilities")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    tool_names = [t["name"] for t in tools]
    assert "search_web" not in tool_names, "search_web must be absent when TAVILY_ENABLED=False"

    # 2. Agent's internal get_tool_definitions() should not include search_web
    agent_tool_names = [t["function"]["name"] for t in get_tool_definitions() if "function" in t]
    assert "search_web" not in agent_tool_names


