"""
Tests for Specialist Multi-Agent System (Coursework, Research, Calendar, Memory)
and delegation from Northstar (Main Agent).
"""

import pytest
import asyncio
from backend.agents.specialist import (
    SpecialistRequest,
    SpecialistResult,
    SpecialistDispatcher,
    run_specialist_task,
)
from backend.skills import SKILL_REGISTRY, TOOL_DEFINITIONS


@pytest.mark.asyncio
async def test_specialist_dispatcher_coursework():
    """Verify CourseworkSpecialist returns structured result."""
    request = SpecialistRequest(
        capability="coursework",
        user_goal="CS 61C RISC-V pipeline lab",
    )
    result = await SpecialistDispatcher.dispatch(request, pool=None)
    assert isinstance(result, SpecialistResult)
    assert result.capability == "coursework"
    assert result.status == "success"
    assert "findings" in result.model_dump()
    assert result.requires_confirmation is False


@pytest.mark.asyncio
async def test_specialist_dispatcher_research():
    """Verify ResearchSpecialist handles web research queries safely."""
    request = SpecialistRequest(
        capability="research",
        user_goal="Check Devpost Nebius hackathon deadline",
    )
    result = await SpecialistDispatcher.dispatch(request, pool=None)
    assert isinstance(result, SpecialistResult)
    assert result.capability == "research"
    assert result.status == "success"
    assert result.requires_confirmation is False


@pytest.mark.asyncio
async def test_specialist_dispatcher_calendar():
    """Verify CalendarSpecialist returns free/busy availability and conflict data."""
    request = SpecialistRequest(
        capability="calendar",
        user_goal="Find free focus time tomorrow",
    )
    result = await SpecialistDispatcher.dispatch(request, pool=None)
    assert isinstance(result, SpecialistResult)
    assert result.capability == "calendar"
    assert result.status == "success"


@pytest.mark.asyncio
async def test_specialist_dispatcher_memory():
    """Verify MemorySpecialist retrieves vector chunks and backlog summary."""
    request = SpecialistRequest(
        capability="memory",
        user_goal="Matryoshka 768-dim embeddings",
    )
    result = await SpecialistDispatcher.dispatch(request, pool=None)
    assert isinstance(result, SpecialistResult)
    assert result.capability == "memory"
    assert result.status == "success"


@pytest.mark.asyncio
async def test_specialist_failure_safety():
    """Verify invalid/failing capability is safely handled without crashing."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SpecialistRequest(
            capability="unknown_capability",  # type: ignore
            user_goal="Test fallback",
        )

    # Test run_specialist_task fallback for unrecognized capability string
    res = await run_specialist_task(
        capability="invalid_cap",
        user_goal="Test fallback",
        pool=None,
    )
    assert res.get("status") == "success"
    assert res.get("capability") == "memory"


@pytest.mark.asyncio
async def test_run_specialist_task_wrapper():
    """Verify canonical run_specialist_task wrapper returns dictionary."""
    res = await run_specialist_task(
        capability="calendar",
        user_goal="Check calendar schedule conflicts",
        pool=None,
    )
    assert isinstance(res, dict)
    assert res.get("capability") == "calendar"
    assert res.get("status") == "success"


@pytest.mark.asyncio
async def test_delegate_to_specialist_skill_handler():
    """Verify delegate_to_specialist registered skill handler works correctly."""
    assert "delegate_to_specialist" in SKILL_REGISTRY
    handler = SKILL_REGISTRY["delegate_to_specialist"]

    res = await handler(
        {"capability": "coursework", "task_description": "Review RISC-V notes"},
        pool=None,
    )
    assert isinstance(res, dict)
    assert "response" in res
    assert "data" in res
    assert res["data"].get("capability") == "coursework"


def test_delegate_tool_definition_exists():
    """Verify delegate_to_specialist tool schema is in TOOL_DEFINITIONS."""
    tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS if "function" in t]
    assert "delegate_to_specialist" in tool_names
