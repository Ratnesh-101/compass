"""
Compass — Feasibility uses saved task durations (not the model's guess), and a schedule
proposal never claims anything was scheduled.  DB-free: task loading and models are patched.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from backend.agents.feasibility import run_feasibility_review


class _DummyPool:
    """Never queried: _fetch_open_tasks is patched."""


def _task(tid: int, title: str, minutes: Any) -> Dict[str, Any]:
    return {"id": tid, "title": title, "priority": "medium", "domain": "coursework",
            "due_date": "2026-12-01", "status": "open", "duration_minutes": minutes}


def _planner_two_hours_each(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "loads": [
            {"task_id": t["id"], "title": t["title"], "domain": "coursework", "priority": "medium",
             "due_date": "2026-12-01", "estimated_hours": 2.0, "rationale": "model guess"}
            for t in tasks
        ],
        "ordering_rationale": "by deadline",
        "claimed_total_hours": 6.0,
    }


def _patch(monkeypatch, tasks: List[Dict[str, Any]]) -> None:
    async def fake_model(model, system, user, max_tokens=1400):
        if "PLANNER" in system and "REJECTED" not in system:
            return _planner_two_hours_each(tasks)
        return None

    monkeypatch.setattr("backend.agents.feasibility._fetch_open_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.agents.feasibility._call_model", fake_model)


async def _plan(**kwargs: Any) -> Dict[str, Any]:
    done = None
    async for ev in run_feasibility_review(_DummyPool(), **kwargs):
        assert ev["type"] != "error", ev
        if ev["type"] == "done":
            done = ev
    assert done is not None
    return done["metadata"]["triage_plan"]


def _all_loads(plan: Dict[str, Any]) -> Dict[int, float]:
    return {t["task_id"]: t["estimated_hours"] for b in ("keep", "defer", "drop") for t in plan[b]}


@pytest.mark.asyncio
async def test_saved_durations_override_planner_estimate(monkeypatch):
    _patch(monkeypatch, [_task(1, "A", 60), _task(2, "B", 30), _task(3, "C", 60)])
    plan = await _plan(days=5, hours_per_day=4.0)
    assert plan["verdict"]["demand_hours"] == 2.5
    assert plan["verdict"]["demand_hours"] != 6.0
    assert _all_loads(plan) == {1: 1.0, 2: 0.5, 3: 1.0}


@pytest.mark.asyncio
async def test_per_task_numbers_shown_are_saved_durations(monkeypatch):
    _patch(monkeypatch, [_task(1, "A", 60), _task(2, "B", 30), _task(3, "C", 60)])
    plan = await _plan(days=5, hours_per_day=4.0)
    md = plan["narrative"] + "\n" + _markdown(plan)
    assert "2h" not in md and "2.0h" not in md, md
    assert "0.5h" in md, md


def _markdown(plan: Dict[str, Any]) -> str:
    from backend.agents.feasibility import TriagePlan
    return TriagePlan.model_validate(plan).as_markdown()


@pytest.mark.asyncio
async def test_missing_duration_falls_back_to_estimate(monkeypatch):
    _patch(monkeypatch, [_task(1, "A", 60), _task(2, "B", None), _task(3, "C", 60)])
    plan = await _plan(days=5, hours_per_day=4.0)
    loads = _all_loads(plan)
    assert loads[1] == 1.0 and loads[3] == 1.0
    assert loads[2] == 2.0
    assert plan["verdict"]["demand_hours"] == 4.0


# ---------------------------------------------------------------------------
# Schedule proposal wording
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_propose_summary_does_not_claim_scheduled(monkeypatch):
    from backend.skills.handlers.calendar import handle_propose_schedule

    class _Conn:
        pass

    class _Acq:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return None

    class _Pool:
        def acquire(self):
            return _Acq()

    tasks = [{"id": 1, "title": "Essay", "priority": "high", "domain": "coursework", "status": "open",
              "due_date": None, "duration_minutes": 60, "owner_id": "u1"}]
    monkeypatch.setattr("backend.memory.structured.list_tasks", AsyncMock(return_value=tasks))
    monkeypatch.setattr("backend.memory.structured.get_scheduling_preferences",
                        AsyncMock(return_value={"work_start_time": "00:00:00", "work_end_time": "23:59:00",
                                                "work_days": [1, 2, 3, 4, 5, 6, 7], "buffer_minutes": 0}))
    monkeypatch.setattr("backend.memory.structured.get_all_dependencies_map", AsyncMock(return_value={}))
    monkeypatch.setattr("backend.services.calendar.get_calendar_freebusy", AsyncMock(return_value=[]))

    res = await handle_propose_schedule({"user_id": "u1", "timezone": "UTC"}, _Pool())
    text = res["response"] + "\n" + str(res["data"].get("summary", ""))
    assert res["data"]["status"] == "proposed"
    assert res["data"]["scheduled"], "expected the task to be proposed a slot"
    assert "Scheduled 1 tasks successfully" not in text
    assert "successfully" not in text.lower(), text
    assert any(p in text.lower() for p in ("nothing is saved until", "not saved until", "not saved yet")), text
