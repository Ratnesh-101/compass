"""
Compass — Feasibility: honest answer when there are no open tasks, stated workload,
and router parsing of days / hours.  DB-free: task loading and models are patched.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from backend.agents.feasibility import run_feasibility_review
from backend.router_helpers import _fallback_route
from backend.skills.handlers.feasibility import handle_assess_feasibility


class _DummyPool:
    """Never used for queries because _fetch_open_tasks is patched."""


async def _final_done(**kwargs: Any) -> Dict[str, Any]:
    done = None
    async for ev in run_feasibility_review(_DummyPool(), **kwargs):
        if ev["type"] == "done":
            done = ev
        assert ev["type"] != "error", ev
    assert done is not None
    return done


def _patch_tasks(monkeypatch, tasks: List[Dict[str, Any]]) -> None:
    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value=None))


_ONE_TASK = [{"id": 1, "title": "Write report", "priority": "high", "domain": "coursework",
              "due_date": "2026-12-01"}]


# ---------------------------------------------------------------------------
# (a) empty task list
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_tasks_narrative_is_honest(monkeypatch):
    _patch_tasks(monkeypatch, [])
    done = await _final_done(days=5, hours_per_day=4.0)
    plan = done["metadata"]["triage_plan"]
    narrative = plan["narrative"]
    assert "You have no open tasks in Compass yet" in narrative
    assert "20" in narrative  # 4 h/day x 5 days
    assert "add" in narrative.lower()
    assert plan["verdict"]["demand_hours"] == 0.0
    assert plan["verdict"]["capacity_hours"] == 20.0
    assert plan["verdict"]["verdict"] != "FEASIBLE" or "no open tasks" in narrative.lower()


@pytest.mark.asyncio
async def test_empty_tasks_summary_starts_with_nothing_to_assess(monkeypatch):
    _patch_tasks(monkeypatch, [])
    res = await handle_assess_feasibility({"user_id": "u1", "days": 5, "hours_per_day": 4}, _DummyPool())
    assert res["success"] is True
    assert res["summary"].startswith("Nothing to assess yet")
    assert not res["summary"].startswith("FEASIBLE")


# ---------------------------------------------------------------------------
# (b) stated workload with no tasks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workload_hours_gives_arithmetic_verdict_without_tasks(monkeypatch):
    _patch_tasks(monkeypatch, [])
    # 30h of work vs 3 days x 4h = 12h nominal (9.6h effective) -> INFEASIBLE
    done = await _final_done(days=3, hours_per_day=4.0, workload_hours=30.0)
    verdict = done["metadata"]["triage_plan"]["verdict"]
    assert verdict["demand_hours"] == 30.0
    assert verdict["capacity_hours"] == 12.0
    assert verdict["verdict"] == "INFEASIBLE"


@pytest.mark.asyncio
async def test_workload_hours_that_fits_is_feasible(monkeypatch):
    _patch_tasks(monkeypatch, [])
    done = await _final_done(days=5, hours_per_day=4.0, workload_hours=10.0)
    verdict = done["metadata"]["triage_plan"]["verdict"]
    assert verdict["demand_hours"] == 10.0
    assert verdict["capacity_hours"] == 20.0
    assert verdict["verdict"] == "FEASIBLE"


# ---------------------------------------------------------------------------
# (c) router parsing
# ---------------------------------------------------------------------------
def test_router_workload_is_not_hours_per_day():
    name, args, _ = _fallback_route("can i finish 30 hours of work in 3 days")
    assert name == "assess_feasibility"
    assert args["workload_hours"] == 30
    assert args["days"] == 3
    assert args["hours_per_day"] != 30
    assert args["hours_per_day"] == 4.0  # default budget


def test_router_hours_a_day_uses_default_days():
    name, args, _ = _fallback_route("Can I finish all of this at 2 hours a day?")
    assert name == "assess_feasibility"
    assert args["hours_per_day"] == 2.0
    assert args["days"] == 5
    assert args["days_stated"] is False


def test_router_stated_days_are_flagged():
    _, args, _ = _fallback_route("can i finish this in 3 days")
    assert args["days"] == 3
    assert args["days_stated"] is True


@pytest.mark.parametrize("message", ["can i finish everything this week", "can i finish it in a week"])
def test_router_week_is_seven_days(message):
    _, args, _ = _fallback_route(message)
    assert args["days"] == 7
    assert args["days_stated"] is True


def test_router_weekend_is_two_days():
    _, args, _ = _fallback_route("can i finish this over the weekend")
    assert args["days"] == 2
    assert args["days_stated"] is True


def test_router_decimal_days_not_read_as_five():
    _, args, _ = _fallback_route("can i finish this in 2.5 days")
    # "2.5 days" is read as 2.5 (never as 5) and flagged as stated.
    assert args["days"] == 2.5
    assert args["days_stated"] is True


# ---------------------------------------------------------------------------
# (d) assumptions in the skill summary
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_summary_mentions_assumptions_when_days_not_stated(monkeypatch):
    _patch_tasks(monkeypatch, _ONE_TASK)
    res = await handle_assess_feasibility(
        {"user_id": "u1", "days": 5, "hours_per_day": 4, "days_stated": False}, _DummyPool())
    assert res["success"] is True
    assert "I assumed the next 5 days at 4" in res["summary"]


@pytest.mark.asyncio
async def test_summary_has_no_assumption_when_days_stated(monkeypatch):
    _patch_tasks(monkeypatch, _ONE_TASK)
    res = await handle_assess_feasibility(
        {"user_id": "u1", "days": 3, "hours_per_day": 4, "days_stated": True}, _DummyPool())
    assert res["success"] is True
    assert "I assumed" not in res["summary"]
