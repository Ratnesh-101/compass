"""
Tests for Specialist Agent Slash Routing, Authoritative Registry, and Chat Integration.
"""

import pytest
import asyncio
from backend.agents.specialist_registry import (
    SPECIALIST_REGISTRY,
    get_specialist,
    validate_specialist_id,
    list_specialists,
)
from backend.agents.specialist import SpecialistRequest, SpecialistDispatcher
from backend.models import ChatRequest, PublicChatRequest, StreamChatRequest


# ---------------------------------------------------------------------------
# A. Specialist Registry Tests
# ---------------------------------------------------------------------------

def test_specialist_registry_all_agents_present():
    """Verify all five specialist agents are registered in authoritative registry."""
    expected_ids = {"auto-dispatcher", "coursework", "research", "calendar", "memory"}
    assert set(SPECIALIST_REGISTRY.keys()) == expected_ids
    assert len(SPECIALIST_REGISTRY) == 5


def test_specialist_registry_unique_ids_and_metadata():
    """Verify registry IDs are unique and metadata fields exist."""
    specialists = list_specialists()
    ids = [s["id"] for s in specialists]
    assert len(ids) == len(set(ids))

    for spec in specialists:
        assert "id" in spec and spec["id"]
        assert "name" in spec and spec["name"]
        assert "description" in spec and spec["description"]
        assert "icon" in spec and spec["icon"]
        assert "capabilities" in spec and isinstance(spec["capabilities"], list)


def test_specialist_alias_lookup():
    """Verify get_specialist resolves canonical IDs and common command aliases."""
    assert get_specialist("calendar").id == "calendar"
    assert get_specialist("/calendar").id == "calendar"
    assert get_specialist("schedule").id == "calendar"
    assert get_specialist("auto").id == "auto-dispatcher"
    assert get_specialist("/auto").id == "auto-dispatcher"
    assert get_specialist("academic").id == "coursework"
    assert get_specialist("web").id == "research"
    assert get_specialist("vector").id == "memory"


# ---------------------------------------------------------------------------
# B. Invalid Specialist ID Rejection Tests
# ---------------------------------------------------------------------------

def test_invalid_specialist_id_validation():
    """Verify unknown or malicious specialist IDs are rejected safely."""
    assert validate_specialist_id("invalid_specialist_999") is None
    assert validate_specialist_id("DROP TABLE users;") is None
    assert validate_specialist_id("../../etc/passwd") is None
    assert validate_specialist_id("") is None
    assert validate_specialist_id(None) is None


# ---------------------------------------------------------------------------
# C. Chat Request Models Specialist ID Parsing Tests
# ---------------------------------------------------------------------------

def test_chat_models_parse_specialist_id():
    """Verify Pydantic chat request models support specialist_id and specialistId."""
    req1 = PublicChatRequest(message="What is my free time?", specialist_id="calendar")
    assert req1.get_specialist_id() == "calendar"

    req2 = PublicChatRequest(message="Check devpost deadline", specialistId="research")
    assert req2.get_specialist_id() == "research"

    req3 = StreamChatRequest(message="Review coursework tasks", specialist_id="coursework")
    assert req3.get_specialist_id() == "coursework"


# ---------------------------------------------------------------------------
# D. Routing & Specialist Execution Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_route_calendar_specialist():
    """Verify specialistId=calendar executes Calendar Agent availability/conflict logic."""
    req = SpecialistRequest(capability="calendar", user_goal="What is my free time tomorrow?")
    result = await SpecialistDispatcher.dispatch(req, pool=None)
    assert result.status == "success"
    assert result.capability == "calendar"
    assert "findings" in result.model_dump()


@pytest.mark.asyncio
async def test_route_coursework_specialist():
    """Verify specialistId=coursework executes Coursework Agent task/notes logic."""
    req = SpecialistRequest(capability="coursework", user_goal="CS 61C RISC-V pipeline lab")
    result = await SpecialistDispatcher.dispatch(req, pool=None)
    assert result.status == "success"
    assert result.capability == "coursework"


@pytest.mark.asyncio
async def test_route_research_specialist():
    """Verify specialistId=research executes Research Agent web/deadline search logic."""
    req = SpecialistRequest(capability="research", user_goal="Verify Nebius hackathon deadline on Devpost")
    result = await SpecialistDispatcher.dispatch(req, pool=None)
    assert result.status == "success"
    assert result.capability == "research"


@pytest.mark.asyncio
async def test_route_memory_specialist():
    """Verify specialistId=memory executes Memory Agent vector recall logic."""
    req = SpecialistRequest(capability="memory", user_goal="Matryoshka 768-dim embeddings")
    result = await SpecialistDispatcher.dispatch(req, pool=None)
    assert result.status == "success"
    assert result.capability == "memory"


@pytest.mark.asyncio
async def test_route_auto_dispatcher():
    """Verify specialistId=auto-dispatcher infers capability from intent and delegates."""
    req = SpecialistRequest(capability="auto-dispatcher", user_goal="Check calendar schedule conflicts tomorrow")
    result = await SpecialistDispatcher.dispatch(req, pool=None)
    assert result.status == "success"
    assert result.capability == "calendar"

    req2 = SpecialistRequest(capability="auto-dispatcher", user_goal="Review CS 61C lab assignment notes")
    result2 = await SpecialistDispatcher.dispatch(req2, pool=None)
    assert result2.status == "success"
    assert result2.capability == "coursework"
