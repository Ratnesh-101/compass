"""A plan proposed via confirm_request without a synthesize step must still render a reply."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agent_types import AgentStep
from backend.agents.schedule_deterministic import _resolve_tz, drop_contradicting_sentences
from backend.orchestrator import _handle_message_core

BLOCKS = [{
    "task_id": 1, "title": "Buy groceries",
    "start": "2026-11-27T09:00:00+00:00", "end": "2026-11-27T10:00:00+00:00",
}]


async def _drive(monkeypatch, steps):
    async def fake_run_agent(**kwargs):
        for s in steps:
            yield s

    async def fake_fetch(pool, user_id, task_ids=None, include_demo=False):
        return {1: {"id": 1, "title": "Buy groceries", "domain": "general",
                    "due_date": "2026-11-28", "priority": "medium"}}

    monkeypatch.setattr("backend.agent.run_agent", fake_run_agent)
    monkeypatch.setattr("backend.agents.schedule_deterministic.fetch_real_tasks_for_schedule", fake_fetch)
    monkeypatch.setattr("backend.orchestrator.get_pool", AsyncMock(return_value=MagicMock()))
    return await _handle_message_core(
        conversation_id=None, message="plan my week", user_id="alice@example.com", guest_id=None,
        history=[], memory_context="", persist=False,
        pre_routed_skill="agent", pre_routed_args={"goal": "plan my week"},
    )


@pytest.mark.asyncio
async def test_confirm_request_without_synthesis_renders_plan(monkeypatch):
    steps = [
        AgentStep(type="confirm_request", tool_name="commit_schedule",
                  tool_args={"assignments": BLOCKS}, content="Commit?"),
        AgentStep(type="done", content=""),
    ]
    result = await _drive(monkeypatch, steps)
    text = result["response"]
    assert "Buy groceries" in text
    assert "Nothing is saved yet" in text
    assert "Unable to complete request" not in text
    assert result["data"]["confirm_request"]["tool"] == "commit_schedule"


@pytest.mark.asyncio
async def test_no_confirm_no_synthesis_keeps_generic_error(monkeypatch):
    result = await _drive(monkeypatch, [AgentStep(type="done", content="")])
    assert "Unable to complete request" in result["response"]


def test_drop_contradicting_sentences_due_today_and_ids():
    today = datetime.now(_resolve_tz()).date()
    tasks = {1: {"id": 1, "title": "Call the bank", "due_date": (today + timedelta(days=1)).isoformat()}}
    text = "Call the bank is due today. Call the bank is due tomorrow. Buy groceries (task ID 2433) is pending."
    out = drop_contradicting_sentences(text, "", tasks)
    assert "due today" not in out
    assert "task ID" not in out
    assert "Call the bank is due tomorrow." in out
