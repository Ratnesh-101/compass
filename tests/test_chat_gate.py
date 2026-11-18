"""
Tests for Chat Gate on Mutating Skills.
Ensures mutating skills (other than add_task) cannot execute through chat dispatch
and instruct the user to use the Agent Planner.
"""

import pytest
from unittest.mock import AsyncMock, patch
from backend.orchestrator import handle_message
from backend.skills import SKILL_REGISTRY
from backend.memory.db import get_pool


@pytest.mark.asyncio
@pytest.mark.parametrize("skill_name,args", [
    ("delete_task", {"task_id": 999999}),
    ("edit_task", {"task_id": 999999, "title": "Mutated Title"}),
    ("apply_triage_plan", {"plan": {}}),
    ("ingest_url", {"url": "https://example.com/test-doc"}),
])
async def test_chat_gate_blocks_mutating_skills(skill_name, args):
    """Test that chat dispatch blocks mutating skills without calling the handler or mutating DB."""
    # Spy on the real handler in SKILL_REGISTRY to verify it is NEVER called
    original_handler = SKILL_REGISTRY.get(skill_name)
    mock_handler = AsyncMock()

    with patch.dict(SKILL_REGISTRY, {skill_name: mock_handler}):
        with patch("backend.orchestrator.route_message", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = (skill_name, args, "I'll do that for you.")

            res = await handle_message(
                conversation_id=None,
                message=f"Please execute {skill_name}",
            )

            # Assert handler was NOT called
            assert mock_handler.call_count == 0

            # Assert gate response returned
            assert res["success"] is False
            assert res["error"] == "confirmation_required"
            assert "modifies data and requires approval" in res["response"]
            assert "Agent Planner" in res["response"]
            assert res["skill_used"] == skill_name


@pytest.mark.asyncio
async def test_chat_gate_allows_add_task():
    """Assert add_task is not blocked by the gate: it reaches the preview-and-confirm step (nothing saved yet)."""
    with patch("backend.orchestrator.route_message", new_callable=AsyncMock) as mock_route:
        mock_route.return_value = (
            "add_task",
            {"title": "Gate Verification Task", "domain": "general", "priority": "medium"},
            "Task added.",
        )

        res = await handle_message(
            conversation_id=None,
            message="add a task: Gate Verification Task",
        )

        assert res.get("error") != "confirmation_required"
        assert res["skill_used"] == "add_tasks_preview"
        assert res["success"] is True
        assert "Gate Verification Task" in res["response"]
        assert "Nothing has been added yet" in res["response"]
        pending = res["data"]["pending_action"]
        assert pending["action"] == "add_tasks" and len(pending["items"]) == 1

        # Clean up the pending preview row (no task was created)
        try:
            pool = await get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute("DELETE FROM chat_pending_actions WHERE id = $1", pending["id"])
        except Exception:
            pass
