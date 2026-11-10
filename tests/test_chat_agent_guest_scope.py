"""
Compass — Chat agent skill identity scoping.

The chat orchestrator's agent block must pass the caller's owner id (signed-in user,
else guest id) and an is_guest flag to run_agent, never None for a guest.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agent_types import AgentStep
from backend.orchestrator import _handle_message_core
from backend.services.ownership import NO_OWNER


async def _run_chat_agent(monkeypatch, user_id, guest_id):
    """Drive _handle_message_core into the agent block with run_agent faked; return recorded kwargs."""
    recorded: list[dict] = []

    async def fake_run_agent(**kwargs):
        recorded.append(kwargs)
        yield AgentStep(type="synthesize", content="ok")

    monkeypatch.setattr("backend.agent.run_agent", fake_run_agent)
    monkeypatch.setattr("backend.orchestrator.get_pool", AsyncMock(return_value=MagicMock()))

    result = await _handle_message_core(
        conversation_id=None,
        message="plan my week",
        user_id=user_id,
        guest_id=guest_id,
        history=[],
        memory_context="",
        persist=False,
        pre_routed_skill="agent",
        pre_routed_args={"goal": "plan my week"},
    )
    assert result["skill_used"] == "agent"
    assert len(recorded) == 1
    return recorded[0]


@pytest.mark.asyncio
async def test_guest_agent_runs_scoped_to_guest_id(monkeypatch):
    guest_id = str(uuid.uuid4())
    kwargs = await _run_chat_agent(monkeypatch, user_id=None, guest_id=guest_id)
    assert kwargs["user_id"] == guest_id
    assert kwargs["is_guest"] is True


@pytest.mark.asyncio
async def test_signed_in_agent_runs_scoped_to_user(monkeypatch):
    kwargs = await _run_chat_agent(monkeypatch, user_id="alice@example.com", guest_id=None)
    assert kwargs["user_id"] == "alice@example.com"
    assert kwargs.get("is_guest") is False


@pytest.mark.asyncio
async def test_no_identity_agent_fails_closed_not_unscoped(monkeypatch):
    kwargs = await _run_chat_agent(monkeypatch, user_id=None, guest_id=None)
    assert kwargs["user_id"] == NO_OWNER
    assert kwargs["user_id"] is not None
