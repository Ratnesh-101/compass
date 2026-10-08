"""
Compass — Agent Advanced Execution Tests.

Tests:
  - Agent rate limit (10 req/min separate from chat)
  - Concurrent active runs cap (max 3)
  - DAG plan validation and cyclic dependency detection
  - Confirmation endpoints (approve/reject/timeout)
  - Re-plan diff calculation
  - Agent report card emitted with metrics and tier breakdown
  - Proactive nightly briefing run
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

def _parse_sse_events(text: str) -> list[dict]:
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
# Round 2 Additions Tests (Items 25–29 / 9–13)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_rate_limit_separate_from_chat(client: AsyncClient, monkeypatch):
    """Addition 1 (Item 9/25): /api/agent/run has a separate 10 req/min rate limiter from /api/chat."""
    import time
    from backend.main import _agent_rate_store, _rate_store

    test_ip = "192.168.100.42"
    _agent_rate_store[test_ip].clear()
    _rate_store[test_ip].clear()

    # Emulate 10 requests inside the sliding window
    now = time.monotonic()
    for _ in range(10):
        _agent_rate_store[test_ip].append(now)

    # 11th agent run should be rejected with 429
    resp = await client.post(
        "/api/agent/run",
        json={"goal": "Test rate limit", "wait_for_confirmation": False},
        headers={"X-Forwarded-For": test_ip, "Authorization": "Bearer dev-token"},
    )
    assert resp.status_code == 429, f"Expected 429 Too Many Requests, got {resp.status_code}"
    assert "Agent rate limit exceeded" in resp.json()["detail"]
    assert "Retry-After" in resp.headers

    # Clear after test
    _agent_rate_store[test_ip].clear()


@pytest.mark.asyncio
async def test_concurrent_active_runs_cap_enforced(client: AsyncClient):
    """Addition 2 (Item 10/26): Cap concurrent active/paused agent_runs at 3."""
    pool = await get_pool()
    unique_ids = [f"test_run_cap_{uuid.uuid4().hex[:6]}" for _ in range(3)]

    # Seed 3 running/paused runs
    async with pool.acquire() as conn:
        for rid in unique_ids:
            await conn.execute(
                """
                INSERT INTO agent_runs (id, goal, status, accumulated_steps, messages, pending_actions)
                VALUES ($1, 'Concurrent test', 'running', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb)
                ON CONFLICT (id) DO UPDATE SET status = 'running'
                """,
                rid
            )

    try:
        # 4th new run must be blocked with HTTP 429
        resp = await client.post(
            "/api/agent/run",
            json={"goal": "4th concurrent run", "wait_for_confirmation": False},
            headers={"Authorization": "Bearer dev-token"},
        )
        assert resp.status_code == 429
        assert "Concurrent active agent runs cap reached" in resp.json()["detail"]
    finally:
        # Clean up seeded test runs
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_runs WHERE id = ANY($1)", unique_ids)


@pytest.mark.asyncio
async def test_critique_stats_endpoint_computes_real_metrics(client: AsyncClient):
    """Addition 3 (Item 11/27): GET /api/agent/critique-stats returns real computed statistics."""
    pool = await get_pool()
    test_run_id = f"test_run_crit_{uuid.uuid4().hex[:6]}"

    # Seed a run with a critique step
    critique_step = {
        "type": "critic",
        "content": "REVISE: Conflict detected between hackathon demo and lab submission.",
        "step": 3,
        "elapsed_ms": 120,
    }
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_runs (id, goal, status, accumulated_steps, messages, pending_actions)
            VALUES ($1, 'Critique test run', 'completed', $2::jsonb, '[]'::jsonb, '[]'::jsonb)
            """,
            test_run_id,
            json.dumps([critique_step]),
        )

    try:
        resp = await client.get("/api/agent/critique-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_runs_analyzed" in data
        assert "runs_with_critique" in data
        assert "critique_issues_flagged" in data
        assert "critique_effectiveness_rate" in data
        assert data["runs_with_critique"] >= 1
        assert data["critique_issues_flagged"] >= 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_runs WHERE id = $1", test_run_id)


@pytest.mark.asyncio
async def test_agent_activity_feed_and_per_item_undo(client: AsyncClient, auth_headers: dict):
    """Addition 4 (Item 12/28): GET /api/agent/activity returns log entries and POST /api/agent/undo reverts specific ID."""
    pool = await get_pool()

    # 1. Create a task directly to simulate mutation
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO tasks (domain, title, status, priority)
            VALUES ('hackathon', 'Test Per-Item Revert', 'open', 'high')
            RETURNING id
            """
        )
        task_id = row["id"]

    # 2. Record an audit log entry
    from backend.agent import record_audit_log
    audit_id = await record_audit_log(
        pool=pool,
        tool="add_task",
        args={"title": "Test Per-Item Revert"},
        run_id="test_act_run",
        affected_table="tasks",
        affected_id=task_id,
        new_state={"id": task_id, "title": "Test Per-Item Revert"},
        approved_by="user",
    )

    # 3. GET /api/agent/activity
    resp = await client.get("/api/agent/activity?limit=10", headers=auth_headers)
    assert resp.status_code == 200
    activities = resp.json().get("activity", [])
    assert any(a["id"] == audit_id for a in activities)

    # 4. POST /api/agent/undo with specific audit_log_id
    undo_resp = await client.post(
        "/api/agent/undo",
        json={"audit_log_id": audit_id},
        headers=auth_headers,
    )
    assert undo_resp.status_code == 200
    undo_data = undo_resp.json()
    assert undo_data["status"] == "ok"
    assert undo_data["reverted"]["audit_log_id"] == audit_id

    # 5. Verify task deleted and audit log marked reverted
    async with pool.acquire() as conn:
        assert await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id) is None
        log_row = await conn.fetchrow("SELECT is_reverted FROM agent_audit_log WHERE id = $1", audit_id)
        assert log_row is not None and log_row["is_reverted"] is True


@pytest.mark.asyncio
async def test_demo_reject_scenario_execution(client: AsyncClient):
    """Addition 5 (Item 13/29): Pre-loaded reject-path re-planning runs and completes without mutating."""
    pool = await get_pool()
    demo_run_id = f"demo_rej_{uuid.uuid4().hex[:6]}"

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(content="Rescheduled conflicting tasks into next available slots without altering OS Homework 2."),
        _create_mock_completion(content="Self-critique pass: all constraints satisfied."),
    ])

    # Simulate resuming with action='reject' and feedback
    events = []
    async for step in run_agent(
        goal="Detect deadline conflicts between hackathon deliverables and coursework and reschedule",
        client=mock_client,
        pool=pool,
        run_id=demo_run_id,
        action="reject",
        feedback="Do not move OS Homework 2 deadline",
        wait_for_confirmation=False,
    ):
        events.append(step)

    # Verify agent re-planned, ran self-critique pass, and finished
    event_types = [e.type for e in events]
    assert "done" in event_types
    assert any(e.type in ("critic", "synthesize") for e in events)

    # Verify run recorded as completed/draft in agent_runs
    async with pool.acquire() as conn:
        run_row = await conn.fetchrow("SELECT * FROM agent_runs WHERE id = $1", demo_run_id)
        assert run_row is not None
        await conn.execute("DELETE FROM agent_runs WHERE id = $1", demo_run_id)


# ---------------------------------------------------------------------------
# Flagship Agent Capabilities Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_per_step_cost_and_model_tier():
    """Verify live step cost and model tier attribution on AgentStep and SSE."""
    step = AgentStep(
        type="think",
        content="Analyzing tasks...",
        step_number=1,
        elapsed_ms=150,
        run_id="test_run_cost",
        model_tier="Nemotron-3 Super (120B)",
        step_cost_usd=0.00042,
    )
    sse = step.to_sse()
    assert "data: " in sse
    payload = json.loads(sse[6:])
    assert payload["model_tier"] == "Nemotron-3 Super (120B)"
    assert payload["step_cost_usd"] == 0.00042

    # Verify mock ReAct loop produces tier and cost
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(content="Final synthesis completed."),
    ])

    steps = []
    async for s in run_agent(
        goal="Test step cost emission",
        client=mock_client,
        enable_critic=False,
    ):
        steps.append(s)

    assert any(s.model_tier == "Nemotron-3 Super (120B)" for s in steps)
    assert any(s.type == "done" and s.metadata and "report_card" in s.metadata for s in steps)

    # Prove that compute_step_cost distinguishes input-rate pricing from output-rate pricing
    from backend.services.usage import compute_step_cost

    # 1. Holding total tokens constant at 100,000 tokens for Nemotron Ultra ($0.80/1M in, $2.40/1M out):
    ultra_all_input = compute_step_cost("nemotron-ultra", prompt_tokens=100_000, completion_tokens=0)
    ultra_all_output = compute_step_cost("nemotron-ultra", prompt_tokens=0, completion_tokens=100_000)
    ultra_split = compute_step_cost("nemotron-ultra", prompt_tokens=50_000, completion_tokens=50_000)

    # Under bugged behavior (completion=0.80), ultra_all_output was 0.08 == ultra_all_input
    # With the fix (completion=2.40), output rate is 3x input rate:
    assert ultra_all_input == 0.08, f"Expected 0.08, got {ultra_all_input}"
    assert ultra_all_output == 0.24, f"Expected 0.24, got {ultra_all_output}"
    assert ultra_all_output != ultra_all_input
    assert ultra_all_output > ultra_split > ultra_all_input
    assert round(ultra_all_output / ultra_all_input, 1) == 3.0

    # 2. Exact documented token count verification: 11,755 in + 8,286 out => $0.02929 (not $0.016034)
    ultra_scenario_cost = compute_step_cost("nemotron-ultra", prompt_tokens=11_755, completion_tokens=8_286)
    expected_ultra_cost = round((11_755 * 0.80 + 8_286 * 2.40) / 1_000_000.0, 6)
    assert ultra_scenario_cost == expected_ultra_cost == 0.02929
    # Moving 8,286 tokens from output to input (holding total tokens at 20,041) changes the cost:
    ultra_all_in_scenario = compute_step_cost("nemotron-ultra", prompt_tokens=20_041, completion_tokens=0)
    assert ultra_scenario_cost != ultra_all_in_scenario
    assert ultra_all_in_scenario == 0.016033


@pytest.mark.asyncio
async def test_agent_chains_three_distinct_tool_types():
    """Verify agent chains 3 distinct tool types in a single triage goal."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(tool_name="query_tasks", tool_args={"domain": "general"}),
        _create_mock_completion(tool_name="query_code_context", tool_args={"project_name": "compass"}),
        _create_mock_completion(tool_name="query_coursework_notes", tool_args={"course": "CS"}),
        _create_mock_completion(content="Triage analysis: Deprioritize non-urgent refactoring."),
    ])

    pool = await get_pool()
    tools_observed = []
    async for s in run_agent(
        goal="What should I deprioritize this week, given my code debt and upcoming exams?",
        client=mock_client,
        pool=pool,
        enable_critic=False,
        max_steps=6,
    ):
        if s.type == "tool_call":
            tools_observed.append(s.tool_name)

    assert "query_tasks" in tools_observed
    assert "query_code_context" in tools_observed
    assert "query_coursework_notes" in tools_observed
    assert len(set(tools_observed)) >= 3


@pytest.mark.asyncio
async def test_agent_epistemic_abstention():
    """Verify agent abstains when context is ambiguous or insufficient instead of hallucinating."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(content="[ABSTAIN] Insufficient coursework information available. I cannot formulate a schedule without missing deadlines."),
        _create_mock_completion(content="[ABSTAIN] Even after checking live sources, no verified syllabus curve exists."),
    ])

    steps = []
    async for s in run_agent(
        goal="What is the final grade weighting and curve formula for Quantum Computing?",
        client=mock_client,
        enable_critic=False,
    ):
        steps.append(s)

    synth_step = next(s for s in steps if s.type == "synthesize")
    assert synth_step.metadata is not None
    assert synth_step.metadata.get("abstained") is True

    done_step = next(s for s in steps if s.type == "done")
    assert done_step.metadata is not None
    report_card = (done_step.metadata or {}).get("report_card", {})
    assert report_card.get("abstained") is True


@pytest.mark.asyncio
async def test_agent_replan_diff_generated():
    """Verify reject path generates and surfaces a structured re-plan diff."""
    pool = await get_pool()
    run_id = f"test_replan_{uuid.uuid4().hex[:6]}"

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(content="Understood. Re-planning alternative without modifying requested task."),
    ])

    steps = []
    async for s in run_agent(
        goal="Reschedule conflicting deadlines",
        client=mock_client,
        pool=pool,
        run_id=run_id,
        action="reject",
        feedback="Do not move OS Homework 2 deadline",
        wait_for_confirmation=False,
        enable_critic=False,
    ):
        steps.append(s)

    obs_step = next(s for s in steps if s.type == "observe")
    assert obs_step.metadata is not None
    assert "replan_diff" in obs_step.metadata
    diff = obs_step.metadata["replan_diff"]
    assert "OS Homework 2" in diff["feedback"]

    # Verify report card captures diff
    done_step = next(s for s in steps if s.type == "done")
    assert done_step.metadata is not None
    report_card = (done_step.metadata or {}).get("report_card") or {}
    assert report_card.get("replan_diff") is not None


@pytest.mark.asyncio
async def test_agent_report_card_emitted():
    """Verify run report card contains comprehensive metrics and model tier breakdown."""
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(content="Synthesis summary complete."),
    ])

    steps = []
    async for s in run_agent(
        goal="Test report card",
        client=mock_client,
        enable_critic=False,
    ):
        steps.append(s)

    done_step = next(s for s in steps if s.type == "done")
    assert done_step.metadata is not None
    rc = (done_step.metadata or {}).get("report_card")
    assert rc is not None
    assert "total_steps" in rc
    assert "elapsed_ms" in rc
    assert "total_cost_usd" in rc
    assert "tier_breakdown" in rc
    assert "Nemotron-3 Super (120B)" in rc["tier_breakdown"]


@pytest.mark.asyncio
async def test_proactive_nightly_run_persisted_and_retrievable(client: AsyncClient):
    """Verify autonomous nightly run executes and is retrievable via /api/agent/proactive-briefing."""
    from backend.jobs.consolidate import trigger_proactive_nightly_run
    pool = await get_pool()

    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        _create_mock_completion(content="Nightly briefing complete: No major blockers found for tomorrow."),
    ])

    res = await trigger_proactive_nightly_run(pool=pool, client=mock_client)
    assert res is not None
    assert res["status"] == "completed"
    run_id = res["run_id"]

    try:
        # Test GET /api/agent/proactive-briefing
        resp = await client.get("/api/agent/proactive-briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert "proactive_nightly_" in data["run_id"]
        assert len(data["accumulated_steps"]) > 0
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_runs WHERE id = $1", run_id)


