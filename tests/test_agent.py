"""
Compass — Agent Tests.
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


@pytest.mark.asyncio
async def test_demo_reject_scenario_execution(client: AsyncClient):
    """Addition 5 (Item 13/29): Pre-loaded reject-path re-planning runs and completes without mutating."""
    pool = await get_pool()
    demo_run_id = f"demo_rej_{uuid.uuid4().hex[:6]}"

    # Mock the Nebius-backed OpenAI client so this test never makes a real
    # network request in CI. Matches the pattern already used by the other
    # reject-path agent test in this file (test_agent_replan_diff_generated):
    # pass client=mock_client directly and disable the critic pass for a
    # deterministic single-synthesis trace.
    mock_client = MagicMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_create_mock_completion(
            content=(
                "Understood, I will not move OS Homework 2. Here is an alternative "
                "reschedule that keeps the hackathon deliverables on track without "
                "touching that deadline."
            )
        )
    )

    # Simulate resuming with action='reject' and feedback
    events = []
    async for step in run_agent(
        goal="Detect deadline conflicts between hackathon deliverables and coursework and reschedule",
        pool=pool,
        client=mock_client,
        run_id=demo_run_id,
        action="reject",
        feedback="Do not move OS Homework 2 deadline",
        wait_for_confirmation=False,
        enable_critic=False,
    ):
        events.append(step)

    # Verify agent re-planned and finished
    event_types = [e.type for e in events]
    assert "done" in event_types
    assert any(e.type == "synthesize" for e in event_types)

    # Verify run recorded as completed/draft in agent_runs
    async with pool.acquire() as conn:
        run_row = await conn.fetchrow("SELECT * FROM agent_runs WHERE id = $1", demo_run_id)
        assert run_row is not None
        await conn.execute("DELETE FROM agent_runs WHERE id = $1", demo_run_id)