"""Agent-proposed plan blocks must respect saved work hours, days, due times and the clock."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agent_types import AgentStep
from backend.agents.schedule_deterministic import validate_proposed_blocks
from backend.orchestrator import _handle_message_core

TZ = "Asia/Kolkata"
PREFS = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "working_days": [1, 2, 3, 4, 5]}
NOW = datetime(2026, 11, 27, 10, 10, tzinfo=timezone.utc)  # Fri 15:40 IST
TASKS = {1: {"id": 1, "title": "Call the bank", "due_at": "2026-11-28T11:30:00+00:00"}}  # Sat 17:00 IST


def _blk(start_utc: str, end_utc: str, tid: int = 1) -> dict:
    return {"task_id": tid, "title": "Call the bank", "scheduled_start": start_utc, "scheduled_end": end_utc}


CLEAN = _blk("2026-11-27T10:30:00+00:00", "2026-11-27T11:30:00+00:00")  # Fri 16:00-17:00 IST


def _check(blocks, tasks=TASKS):
    return validate_proposed_blocks(blocks, PREFS, TZ, NOW, tasks)


def test_clean_set_accepted():
    assert _check([CLEAN]) == (True, [])


def test_after_work_end_flagged():
    ok, problems = _check([_blk("2026-11-27T11:45:00+00:00", "2026-11-27T12:45:00+00:00")])  # 17:15-18:15 IST
    assert not ok and any("working hours" in p for p in problems)


def test_non_working_day_flagged():
    ok, problems = _check([_blk("2026-11-28T05:00:00+00:00", "2026-11-28T06:00:00+00:00")])  # Sat 10:30 IST
    assert not ok and any("non-working" in p for p in problems)


def test_after_due_at_flagged():
    tasks = {1: {"id": 1, "due_at": "2026-11-27T10:45:00+00:00"}}
    ok, problems = _check([CLEAN], tasks)
    assert not ok and any("due" in p for p in problems)


def test_past_block_flagged():
    ok, problems = _check([_blk("2026-11-27T04:00:00+00:00", "2026-11-27T05:00:00+00:00")])
    assert not ok and any("past" in p for p in problems)


def test_overlap_flagged():
    other = _blk("2026-11-27T11:00:00+00:00", "2026-11-27T12:00:00+00:00")
    ok, problems = _check([CLEAN, other])
    assert not ok and any("overlap" in p for p in problems)


BAD = [{"task_id": 1, "title": "Call the bank",
        "start": "2026-11-27T11:45:00+00:00", "end": "2026-11-27T12:45:00+00:00"}]
GOOD = [{"task_id": 1, "title": "Call the bank",
         "scheduled_start": "2026-11-28T04:00:00+00:00", "scheduled_end": "2026-11-28T05:00:00+00:00"}]


@pytest.mark.asyncio
async def test_orchestrator_replaces_violating_assignments(monkeypatch):
    class FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW

    async def fake_run_agent(**kwargs):
        yield AgentStep(type="confirm_request", tool_name="commit_schedule",
                        tool_args={"assignments": [dict(b) for b in BAD]}, content="Commit?")
        yield AgentStep(type="done", content="")

    async def fake_fetch(pool, user_id, task_ids=None, include_demo=False):
        return {1: {"id": 1, "title": "Call the bank", "domain": "general",
                    "due_at": "2026-11-30T11:30:00+00:00", "priority": "medium"}}

    async def fake_prefs(pool, user_id):
        return dict(PREFS)

    async def fake_propose(args, pool):
        return {"data": {"scheduled": [dict(b) for b in GOOD]}}

    monkeypatch.setattr("backend.agent.run_agent", fake_run_agent)
    monkeypatch.setattr("backend.agents.schedule_deterministic.fetch_real_tasks_for_schedule", fake_fetch)
    monkeypatch.setattr("backend.agents.schedule_deterministic.fetch_saved_preferences", fake_prefs)
    monkeypatch.setattr("backend.agents.schedule_deterministic.datetime", FixedDT)
    monkeypatch.setattr("backend.skills.handlers.calendar.handle_propose_schedule", fake_propose)
    monkeypatch.setattr("backend.orchestrator.get_pool", AsyncMock(return_value=MagicMock()))
    result = await _handle_message_core(
        conversation_id=None, message="plan my week", user_id="alice@example.com", guest_id=None,
        history=[], memory_context="", persist=False,
        pre_routed_skill="agent", pre_routed_args={"goal": "plan my week"},
    )
    assigns = result["data"]["confirm_request"]["args"]["assignments"]
    assert [a["scheduled_start"] for a in assigns] == [GOOD[0]["scheduled_start"]]
    assert "Call the bank" in result["response"]
    assert "Sat" in result["response"]
