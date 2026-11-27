"""
Compass — Feasibility: stated workload/days parsing and arithmetic, and chat
"mark X as done" with no matching task.  DB-free: task loading and models are patched.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from backend.agents.feasibility import run_feasibility_review
from backend.router_helpers import _fallback_route, parse_feasibility_intent
from backend.services import chat_task_actions
from backend.services.chat_task_actions import handle_chat_task_action, parse_task_action_intent
from backend.skills.handlers.feasibility import handle_assess_feasibility


class _DummyPool:
    """Never queried: _fetch_open_tasks is patched."""


_TASKS = [
    {"id": 1, "title": "A", "priority": "high", "domain": "coursework", "due_date": "2026-12-01",
     "duration_minutes": 60},
    {"id": 2, "title": "B", "priority": "medium", "domain": "coursework", "due_date": "2026-12-02",
     "duration_minutes": 30},
    {"id": 3, "title": "C", "priority": "low", "domain": "coursework", "due_date": "2026-12-03",
     "duration_minutes": 60},
]


def _patch_tasks(monkeypatch, tasks: List[Dict[str, Any]]) -> None:
    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", AsyncMock(return_value=None))


async def _verdict(**kwargs: Any) -> Dict[str, Any]:
    done = None
    async for ev in run_feasibility_review(_DummyPool(), **kwargs):
        assert ev["type"] != "error", ev
        if ev["type"] == "done":
            done = ev
    assert done is not None
    return done["metadata"]["triage_plan"]["verdict"]


# ---------------------------------------------------------------------------
# (1) parsing
# ---------------------------------------------------------------------------
_STATED = "I have 30 hours of work and only 2.5 days left. Is that doable?"


def test_fallback_route_reads_stated_workload_and_decimal_days():
    name, args, _ = _fallback_route(_STATED)
    assert name == "assess_feasibility"
    assert args["workload_hours"] == 30.0
    assert args["days"] == 2.5
    assert isinstance(args["days"], float)
    assert args["days"] not in (2, 5) or isinstance(args["days"], float)
    assert args["days_stated"] is True


def test_parse_feasibility_intent_reads_stated_workload_and_decimal_days():
    args = parse_feasibility_intent(_STATED)
    assert args is not None
    assert args["workload_hours"] == 30.0
    assert args["days"] == 2.5
    assert isinstance(args["days"], float)
    assert args["days_stated"] is True


def test_fallback_route_hours_a_day_not_workload():
    name, args, _ = _fallback_route("Can I finish all of this in 2 hours a day?")
    assert name == "assess_feasibility"
    assert args["hours_per_day"] == 2.0
    assert args["days_stated"] is False
    assert "workload_hours" not in args or args["workload_hours"] is None


# ---------------------------------------------------------------------------
# (2) arithmetic
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_saved_tasks_demand_is_2_5_hours_without_stated_workload(monkeypatch):
    _patch_tasks(monkeypatch, _TASKS)
    verdict = await _verdict(days=5, hours_per_day=4.0)
    assert verdict["demand_hours"] == 2.5
    assert verdict["demand_hours"] != 4.5


@pytest.mark.asyncio
async def test_stated_workload_replaces_saved_tasks_demand(monkeypatch):
    _patch_tasks(monkeypatch, _TASKS)
    verdict = await _verdict(days=2.5, hours_per_day=4.0, workload_hours=30.0)
    assert verdict["demand_hours"] == 30.0
    assert verdict["capacity_hours"] == 2.5 * 4.0
    assert verdict["verdict"] == "INFEASIBLE"


@pytest.mark.asyncio
async def test_handler_summary_with_stated_workload_and_saved_tasks(monkeypatch):
    _patch_tasks(monkeypatch, _TASKS)
    res = await handle_assess_feasibility(
        {"user_id": "u1", "days": 2.5, "hours_per_day": 4, "workload_hours": 30, "days_stated": True},
        _DummyPool(),
    )
    assert res["success"] is True
    verdict = res["data"]["triage_plan"]["verdict"]
    assert verdict["demand_hours"] == 30.0
    assert verdict["capacity_hours"] == 2.5 * 4.0
    assert "Not all of it fits" in res["summary"]
    assert "30" in res["summary"]


# ---------------------------------------------------------------------------
# (3) "Mark X as done" with no matching task
# ---------------------------------------------------------------------------
def test_parse_mark_as_done_is_complete_intent():
    intent = parse_task_action_intent("Mark the Quantum physics essay as done")
    assert intent is not None
    assert intent["action"] == "complete"
    assert "quantum physics essay" in intent["target"].lower()


class _Conn:
    pass


class _Acquire:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *exc):
        return None


class _Pool:
    def acquire(self):
        return _Acquire()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [[], [
    {"id": 7, "title": "Chemistry lab report", "status": "open"},
    {"id": 8, "title": "Buy groceries", "status": "open"},
]])
async def test_complete_unknown_task_creates_no_pending_action(monkeypatch, existing):
    create = AsyncMock()
    monkeypatch.setattr(chat_task_actions, "get_all_active_tasks_for_user",
                        AsyncMock(return_value=existing))
    monkeypatch.setattr(chat_task_actions, "create_chat_pending_action", create)

    intent = parse_task_action_intent("Mark the Quantum physics essay as done")
    assert intent is not None
    res = await handle_chat_task_action(
        intent, "Mark the Quantum physics essay as done", "c1", "u1", pool=_Pool(), persist=False,
    )
    assert "couldn't find" in res["response"]
    create.assert_not_called()
    assert "pending_action" not in (res["data"] or {})
    # The reply may suggest the user's own open tasks, but it must not claim anything was changed.
    assert "done" not in res["response"].lower().replace("mark", "").split("couldn't find")[0]
