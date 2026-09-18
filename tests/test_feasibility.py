"""
Compass — Adversarial Feasibility & The Realist Test Suite.

Automated verification tests for all 10 requirements:
1. test_infeasible_when_demand_exceeds_capacity
2. test_feasible_plan_accepted_in_one_round
3. test_negotiation_capped_at_two_rounds
4. test_deterministic_fallback_when_models_unavailable
5. test_malformed_model_json_falls_back
6. test_arithmetic_is_never_taken_from_the_model
7. test_apply_triage_plan_is_confirm_gated
8. test_no_open_tasks_returns_empty_plan
9. test_feasibility_never_mutates_database
10. test_artifact_markdown_renders_all_buckets
"""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from backend.agent import MUTATING_TOOLS, READ_ONLY_TOOLS
from backend.agents.feasibility import (
    MAX_ROUNDS,
    FeasibilityVerdict,
    TaskLoad,
    TriagePlan,
    _arithmetic_verdict,
    _safe_json,
    assess_feasibility,
    run_feasibility_review,
)
from backend.skills import SKILL_REGISTRY


class MockDbPool:
    """Mock connection pool that monitors queries and enforces read-only tracking."""

    def __init__(self, tasks: Optional[List[Dict[str, Any]]] = None):
        self.tasks = tasks or []
        self.mutations: List[str] = []

    def acquire(self):
        pool_ref = self

        class ConnContext:
            async def __aenter__(self):
                class Conn:
                    async def fetch(self, query: str, *args, **kwargs):
                        return pool_ref.tasks

                    async def fetchrow(self, query: str, *args, **kwargs):
                        return pool_ref.tasks[0] if pool_ref.tasks else None

                    async def execute(self, query: str, *args, **kwargs):
                        pool_ref.mutations.append(query)
                        return "UPDATE 1"

                    def transaction(self):
                        class TxContext:
                            async def __aenter__(self_tx):
                                return self_tx

                            async def __aexit__(self_tx, exc_type, exc, tb):
                                return None

                        return TxContext()

                return Conn()

            async def __aexit__(self, exc_type, exc, tb):
                return None

        return ConnContext()


# ---------------------------------------------------------------------------
# 1. Infeasible when demand exceeds capacity
# ---------------------------------------------------------------------------
def test_infeasible_when_demand_exceeds_capacity():
    """Verify _arithmetic_verdict flags INFEASIBLE when demand exceeds effective capacity * 1.15."""
    # 40h demand against 16h nominal capacity (effective = 12.8h, threshold = 14.72h)
    verdict = _arithmetic_verdict(demand=40.0, capacity=16.0)
    assert verdict.verdict == "INFEASIBLE"
    assert verdict.demand_hours == 40.0
    assert verdict.capacity_hours == 16.0
    assert verdict.overcommit_hours == 27.2  # 40 - 12.8
    assert verdict.must_cut_hours == 27.2
    assert verdict.utilisation_pct == 312.5
    assert not verdict.accepts


# ---------------------------------------------------------------------------
# 2. Feasible plan accepted in one round
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_feasible_plan_accepted_in_one_round(monkeypatch):
    """Verify that when workload fits inside effective capacity, plan is accepted on Round 1."""
    mock_tasks = [
        {"id": 101, "title": "Quick bugfix", "domain": "code", "priority": "high", "due_date": "2026-10-01"}
    ]
    pool = MockDbPool(mock_tasks)

    monkeypatch.setattr(
        "backend.agents.feasibility._fetch_open_tasks",
        AsyncMock(return_value=mock_tasks),
    )

    planner_out = {
        "loads": [
            {"task_id": 101, "title": "Quick bugfix", "domain": "code", "priority": "high",
             "due_date": "2026-10-01", "estimated_hours": 2.0, "rationale": "minor fix"}
        ],
        "ordering_rationale": "Single task",
        "claimed_total_hours": 2.0,
    }
    realist_out = {
        "verdict": "FEASIBLE",
        "reasoning": "Fits well within capacity.",
        "challenged_estimates": [],
    }

    async def mock_call(model, system, user, max_tokens=1400):
        if "PLANNER" in system:
            return planner_out
        return realist_out

    monkeypatch.setattr("backend.agents.feasibility._call_model", mock_call)

    plan = await assess_feasibility(pool, days=5, hours_per_day=4.0)
    assert plan.rounds_used == 1
    assert plan.verdict.verdict == "FEASIBLE"
    assert len(plan.keep) == 1
    assert len(plan.defer) == 0
    assert len(plan.drop) == 0
    assert plan.keep[0].task_id == 101


# ---------------------------------------------------------------------------
# 3. Negotiation capped at two rounds
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_negotiation_capped_at_two_rounds(monkeypatch):
    """Verify that Planner ↔ Realist negotiation is hard-capped at MAX_ROUNDS (2)."""
    mock_tasks = [
        {"id": 201, "title": "Build full backend", "domain": "code", "priority": "urgent", "due_date": "2026-10-01"},
        {"id": 202, "title": "Design UI system", "domain": "hackathon", "priority": "high", "due_date": "2026-10-02"},
        {"id": 203, "title": "Write 20 tests", "domain": "code", "priority": "medium", "due_date": "2026-10-03"},
    ]
    pool = MockDbPool(mock_tasks)

    monkeypatch.setattr(
        "backend.agents.feasibility._fetch_open_tasks",
        AsyncMock(return_value=mock_tasks),
    )

    proposal_out = {
        "loads": [
            {"task_id": 201, "title": "Build full backend", "domain": "code", "priority": "urgent",
             "due_date": "2026-10-01", "estimated_hours": 20.0, "rationale": "large"},
            {"task_id": 202, "title": "Design UI system", "domain": "hackathon", "priority": "high",
             "due_date": "2026-10-02", "estimated_hours": 15.0, "rationale": "large"},
            {"task_id": 203, "title": "Write 20 tests", "domain": "code", "priority": "medium",
             "due_date": "2026-10-03", "estimated_hours": 10.0, "rationale": "medium"},
        ],
        "ordering_rationale": "Attempt all",
        "claimed_total_hours": 45.0,
    }

    replan_out = {
        "keep": [
            {"task_id": 201, "title": "Build full backend", "domain": "code", "priority": "urgent",
             "due_date": "2026-10-01", "estimated_hours": 10.0, "rationale": "scaled scope"}
        ],
        "defer": [
            {"task_id": 202, "title": "Design UI system", "domain": "hackathon", "priority": "high",
             "due_date": "2026-10-02", "estimated_hours": 15.0, "rationale": "deferred to round 2"}
        ],
        "drop": [
            {"task_id": 203, "title": "Write 20 tests", "domain": "code", "priority": "medium",
             "due_date": "2026-10-03", "estimated_hours": 10.0, "rationale": "dropped"}
        ],
        "narrative": "Cut back to fit in available capacity.",
    }

    async def mock_call(model, system, user, max_tokens=1400):
        if "PLANNER_REPLAN_SYSTEM" in system or "Your plan was rejected" in user:
            return replan_out
        if "PLANNER" in system:
            return proposal_out
        return {"verdict": "INFEASIBLE", "reasoning": "Excessive workload."}

    monkeypatch.setattr("backend.agents.feasibility._call_model", mock_call)

    plan = await assess_feasibility(pool, days=4, hours_per_day=4.0)
    assert plan.rounds_used <= MAX_ROUNDS
    assert plan.rounds_used == 2
    assert len(plan.keep) >= 1
    assert len(plan.defer) + len(plan.drop) >= 1


# ---------------------------------------------------------------------------
# 4. Deterministic fallback when models are unavailable
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_deterministic_fallback_when_models_unavailable(monkeypatch):
    """Verify pure-Python heuristic runs when model calls fail completely, returning degraded=True."""
    mock_tasks = [
        {"id": 301, "title": "Urgent bug", "priority": "urgent", "domain": "code", "due_date": "2026-10-01"},
        {"id": 302, "title": "High task", "priority": "high", "domain": "coursework", "due_date": "2026-10-05"},
        {"id": 303, "title": "Low task", "priority": "low", "domain": "general", "due_date": None},
    ]
    pool = MockDbPool(mock_tasks)

    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=mock_tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value=None))

    plan = await assess_feasibility(pool, days=2, hours_per_day=2.0)  # 4h nominal, 3.2h effective
    assert plan is not None
    assert plan.degraded is True
    assert isinstance(plan.verdict, FeasibilityVerdict)
    assert plan.verdict.capacity_hours == 4.0
    assert len(plan.keep) + len(plan.defer) + len(plan.drop) == 3


# ---------------------------------------------------------------------------
# 5. Malformed model JSON falls back cleanly
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_malformed_model_json_falls_back(monkeypatch):
    """Verify _safe_json parses cleanly and invalid model strings fall back without crashing."""
    assert _safe_json(None) is None
    assert _safe_json("") is None
    assert _safe_json("Not valid json text") is None
    assert _safe_json("{unquoted_key: 123}") is None
    assert _safe_json('```json\n{"loads": []}\n```') == {"loads": []}
    assert _safe_json('Here is your plan: {"keep": []} hope it helps') == {"keep": []}

    mock_tasks = [{"id": 401, "title": "Test task", "priority": "medium", "domain": "general"}]
    pool = MockDbPool(mock_tasks)

    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=mock_tasks))
    # Return invalid structure missing loads
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value={"garbage": True}))

    plan = await assess_feasibility(pool, days=3, hours_per_day=4.0)
    assert plan is not None
    assert plan.degraded is True  # Fell back to heuristic proposal
    assert len(plan.keep) == 1


# ---------------------------------------------------------------------------
# 6. Arithmetic is NEVER taken from the model
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_arithmetic_is_never_taken_from_the_model(monkeypatch):
    """Verify that Python's arithmetic computation overrides any false claims made by the model."""
    mock_tasks = [
        {"id": 501, "title": "Massive backend", "priority": "urgent", "domain": "code", "due_date": "2026-10-01"},
        {"id": 502, "title": "Massive frontend", "priority": "urgent", "domain": "code", "due_date": "2026-10-01"},
    ]
    pool = MockDbPool(mock_tasks)

    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=mock_tasks))

    # Planner proposes 50 hours of work (25h + 25h)
    planner_proposal = {
        "loads": [
            {"task_id": 501, "title": "Massive backend", "domain": "code", "priority": "urgent",
             "due_date": "2026-10-01", "estimated_hours": 25.0, "rationale": "huge"},
            {"task_id": 502, "title": "Massive frontend", "domain": "code", "priority": "urgent",
             "due_date": "2026-10-01", "estimated_hours": 25.0, "rationale": "huge"},
        ],
        "ordering_rationale": "Two large tasks",
        "claimed_total_hours": 50.0,
    }
    # Model hallucinated FEASIBLE despite 50h demand on 8h capacity
    hallucinating_realist = {
        "verdict": "FEASIBLE",
        "demand_hours": 2.0,
        "capacity_hours": 100.0,
        "reasoning": "Model erroneously claims it is feasible.",
    }

    async def mock_call(model, system, user, max_tokens=1400):
        if "PLANNER_REPLAN_SYSTEM" in system or "Your plan was rejected" in user:
            return None  # Trigger deterministic greedy cut on round 2
        if "PLANNER" in system:
            return planner_proposal
        return hallucinating_realist

    monkeypatch.setattr("backend.agents.feasibility._call_model", mock_call)

    # 2 days * 4h = 8h capacity, effective = 6.4h. 50h is completely INFEASIBLE.
    events = []
    async for ev in run_feasibility_review(pool, days=2, hours_per_day=4.0):
        events.append(ev)

    # Find the first verdict event
    verdict_events = [e for e in events if e["type"] == "verdict"]
    assert len(verdict_events) >= 1
    # Check that Python forced INFEASIBLE despite model's FEASIBLE string
    first_verdict = verdict_events[0]["metadata"]["verdict"]
    assert first_verdict["verdict"] == "INFEASIBLE"
    assert first_verdict["demand_hours"] == 50.0
    assert first_verdict["capacity_hours"] == 8.0


# ---------------------------------------------------------------------------
# 7. apply_triage_plan is confirm-gated
# ---------------------------------------------------------------------------
def test_apply_triage_plan_is_confirm_gated():
    """Verify apply_triage_plan requires confirmation and assess_feasibility is read-only."""
    assert "apply_triage_plan" in MUTATING_TOOLS
    assert "apply_triage_plan" not in READ_ONLY_TOOLS

    assert "assess_feasibility" in READ_ONLY_TOOLS
    assert "assess_feasibility" not in MUTATING_TOOLS

    assert "assess_feasibility" in SKILL_REGISTRY
    assert "apply_triage_plan" in SKILL_REGISTRY


# ---------------------------------------------------------------------------
# 8. No open tasks returns empty plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_open_tasks_returns_empty_plan(monkeypatch):
    """Verify that when there are zero open tasks, assess_feasibility returns an empty FEASIBLE plan."""
    pool = MockDbPool([])
    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=[]))

    plan = await assess_feasibility(pool, days=5, hours_per_day=4.0)
    assert plan.keep == []
    assert plan.defer == []
    assert plan.drop == []
    assert plan.verdict.demand_hours == 0.0
    assert plan.verdict.verdict == "FEASIBLE"
    assert "No open tasks" in plan.narrative


# ---------------------------------------------------------------------------
# 9. Feasibility never mutates database
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_feasibility_never_mutates_database(monkeypatch):
    """Verify assess_feasibility performs zero database mutations (INSERT, UPDATE, DELETE)."""
    mock_tasks = [
        {"id": 901, "title": "Non-mutating test", "priority": "high", "domain": "general"}
    ]
    pool = MockDbPool(mock_tasks)
    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=mock_tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value=None))

    await assess_feasibility(pool, days=3, hours_per_day=4.0)
    assert len(pool.mutations) == 0, f"Unexpected mutations occurred: {pool.mutations}"


# ---------------------------------------------------------------------------
# 10. Artifact markdown renders all buckets
# ---------------------------------------------------------------------------
def test_artifact_markdown_renders_all_buckets():
    """Verify TriagePlan.as_markdown() includes Keep, Defer, and Drop sections with formatting."""
    plan = TriagePlan(
        keep=[
            TaskLoad(task_id=1, title="Core Engine", domain="code", priority="urgent",
                     due_date="2026-10-01", estimated_hours=4.0, rationale="vital")
        ],
        defer=[
            TaskLoad(task_id=2, title="Docs Polish", domain="general", priority="medium",
                     due_date=None, estimated_hours=2.0, rationale="later")
        ],
        drop=[
            TaskLoad(task_id=3, title="Nice to have feature", domain="hackathon", priority="low",
                     due_date=None, estimated_hours=3.0, rationale="dropped")
        ],
        verdict=FeasibilityVerdict(
            verdict="FEASIBLE",
            demand_hours=4.0,
            capacity_hours=10.0,
            overcommit_hours=0.0,
            utilisation_pct=50.0,
        ),
        rounds_used=2,
        narrative="Balanced trade-off achieved.",
        degraded=False,
    )

    md = plan.as_markdown()
    assert "# Compass — Feasibility Triage" in md
    assert "**Verdict:** FEASIBLE" in md
    assert "## Keep (1)" in md
    assert "- **Core Engine** [code] · 4.0h — due 2026-10-01 — vital" in md
    assert "## Defer (1)" in md
    assert "- **Docs Polish** [general] · 2.0h — later" in md
    assert "## Drop (1)" in md
    assert "- **Nice to have feature** [hackathon] · 3.0h — dropped" in md
    assert "_Negotiation rounds: 2_" in md
