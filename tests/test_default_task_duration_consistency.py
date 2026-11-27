"""One shared default length for a task without one: scheduler, agent plan and feasibility agree.

DB-free: task loading and model calls are patched.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from backend.agents.feasibility import TriagePlan, run_feasibility_review
from backend.agents.feasibility_format import format_feasibility_summary
from backend.services.scheduler import DEFAULT_TASK_MINUTES, sort_tasks_for_scheduling


class _DummyPool:
    """Never queried: _fetch_open_tasks is patched."""


def _task(tid: int, title: str, minutes: Any) -> Dict[str, Any]:
    return {"id": tid, "title": title, "priority": "medium", "domain": "general",
            "due_date": None, "status": "open", "duration_minutes": minutes}


def _patch(monkeypatch, tasks: List[Dict[str, Any]]) -> None:
    async def fake_model(model, system, user, max_tokens=1400):
        if "PLANNER" in system and "REJECTED" not in system:
            # The model guesses 2h / 0.5h per task; feasibility must ignore this.
            return {
                "loads": [
                    {"task_id": t["id"], "title": t["title"], "domain": "general", "priority": "medium",
                     "due_date": None, "estimated_hours": 2.0 if i % 2 == 0 else 0.5, "rationale": "guess"}
                    for i, t in enumerate(tasks)
                ],
                "ordering_rationale": "x",
                "claimed_total_hours": 99.0,
            }
        return None

    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", fake_model)


async def _plan(**kwargs: Any) -> TriagePlan:
    done = None
    async for ev in run_feasibility_review(_DummyPool(), **kwargs):
        assert ev["type"] != "error", ev
        if ev["type"] == "done":
            done = ev
    assert done is not None
    return TriagePlan.model_validate(done["metadata"]["triage_plan"])


def _summary(plan: TriagePlan) -> str:
    return format_feasibility_summary(plan, days=1, hours_per_day=2.0)


ASSUMPTION = "Tasks without a set length use estimated lengths:"


@pytest.mark.asyncio
async def test_unset_tasks_use_planner_estimates_and_are_listed(monkeypatch):
    names = ["Buy groceries", "DBMS assignment", "Call the bank"]
    _patch(monkeypatch, [_task(i + 1, n, None) for i, n in enumerate(names)])
    plan = await _plan(days=1, hours_per_day=2.0)
    assert plan.verdict.demand_hours == 4.5  # planner guesses 2h, 0.5h, 2h
    text = _summary(plan)
    assert text.count(ASSUMPTION) == 1, text
    assert f"{ASSUMPTION} Buy groceries (2h), DBMS assignment (0.5h), Call the bank (2h)." in text, text


@pytest.mark.asyncio
async def test_zero_duration_is_treated_as_unset(monkeypatch):
    _patch(monkeypatch, [_task(1, "Zero", 0)])
    plan = await _plan(days=1, hours_per_day=2.0)
    assert plan.verdict.demand_hours == 2.0
    assert f"{ASSUMPTION} Zero (2h)." in _summary(plan)


@pytest.mark.asyncio
async def test_set_length_counted_exactly_and_not_mentioned(monkeypatch):
    _patch(monkeypatch, [_task(1, "Call the bank", 30), _task(2, "Buy groceries", None)])
    plan = await _plan(days=1, hours_per_day=2.0)
    hours = {t.title: t.estimated_hours for t in plan.keep + plan.defer + plan.drop}
    assert hours == {"Call the bank": 0.5, "Buy groceries": 0.5}
    text = _summary(plan)
    assert f"{ASSUMPTION} Buy groceries (0.5h)." in text, text
    assert "Call the bank (" not in text.split(ASSUMPTION)[1]


@pytest.mark.asyncio
async def test_no_assumption_sentence_when_all_have_length(monkeypatch):
    _patch(monkeypatch, [_task(1, "A", 30), _task(2, "B", 90)])
    plan = await _plan(days=1, hours_per_day=2.0)
    assert plan.verdict.demand_hours == 2.0
    assert "without a set length" not in _summary(plan)


@pytest.mark.asyncio
async def test_assumption_lists_at_most_six_then_more(monkeypatch):
    _patch(monkeypatch, [_task(i, f"T{i}", None) for i in range(1, 9)])
    plan = await _plan(days=5, hours_per_day=8.0)
    text = _summary(plan)
    assert "T6 (0.5h)" in text and "T7" not in text.split(ASSUMPTION)[1]
    assert "and 2 more." in text, text

def test_scheduler_default_equals_constant():
    assert DEFAULT_TASK_MINUTES == 60
    # Scheduler orders by duration, using the constant for a task without one.
    tasks = [
        {"id": 1, "title": "unset", "priority": "medium", "duration_minutes": None},
        {"id": 2, "title": "shorter", "priority": "medium", "duration_minutes": DEFAULT_TASK_MINUTES - 1},
        {"id": 3, "title": "longer", "priority": "medium", "duration_minutes": DEFAULT_TASK_MINUTES + 1},
    ]
    order = [t["title"] for t in sort_tasks_for_scheduling(tasks)]
    assert order == ["shorter", "unset", "longer"]
