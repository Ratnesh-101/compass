"""
Compass — Persona and Profile Facts Memory Tests.

Tests the warm thinking partner persona prompts, signature phrase pools,
profile facts extraction, storage, and API endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient

from backend.persona import (
    STARTING_PHRASES,
    EXPLORING_PHRASES,
    RETURNING_PHRASES,
    MID_CHAT_PHRASES,
    CLOSING_PHRASES,
    build_persona_system_prompt,
    format_tool_response,
)
from backend.router import message_needs_tools, _fallback_route
from backend.skills.schemas import BASE_TOOL_DEFINITIONS
from backend.skills.handlers.profile import handle_remember_fact, handle_forget_fact
from backend.memory.profile import get_profile_facts, set_profile_fact, delete_profile_fact


def test_persona_phrase_pools():
    """Verify signature phrase pools are populated and contain key thinking partner phrases."""
    assert len(STARTING_PHRASES) >= 4
    assert len(EXPLORING_PHRASES) >= 3
    assert len(RETURNING_PHRASES) >= 2
    assert len(MID_CHAT_PHRASES) >= 4
    assert len(CLOSING_PHRASES) >= 2

    assert any("Where should we begin?" in p for p in STARTING_PHRASES)
    assert any("Let's noodle on it" in p for p in EXPLORING_PHRASES)
    assert any("Welcome back" in p for p in RETURNING_PHRASES)


def test_build_persona_system_prompt_empty_facts():
    """When no profile facts exist, facts section must be strictly omitted to save prompt tokens."""
    prompt = build_persona_system_prompt(profile_facts=None)
    assert "Compass" in prompt
    assert "VOICE:" in prompt
    assert "[WHAT THE USER HAS TOLD YOU" not in prompt

    prompt_empty_dict = build_persona_system_prompt(profile_facts={})
    assert "[WHAT THE USER HAS TOLD YOU" not in prompt_empty_dict


def test_build_persona_system_prompt_with_facts():
    """When profile facts exist, they are cleanly injected and formatted."""
    facts = {
        "name": "Jordan",
        "goal": "Ship hackathon project before Friday midnight",
        "preference": "Short, bulleted summaries",
    }
    prompt = build_persona_system_prompt(profile_facts=facts, extra_context="Upcoming deadline: CS189")
    assert "[WHAT THE USER HAS TOLD YOU" in prompt
    assert "- Name: Jordan" in prompt
    assert "- Goal: Ship hackathon project before Friday midnight" in prompt
    assert "- Preference: Short, bulleted summaries" in prompt
    assert "Upcoming deadline: CS189" in prompt


def test_build_persona_system_prompt_caps_facts_at_15():
    """To protect context window, facts are capped at 15 items."""
    large_facts = {f"fact_{i:02d}": f"value_{i}" for i in range(25)}
    prompt = build_persona_system_prompt(profile_facts=large_facts)
    lines = [line for line in prompt.split("\n") if line.strip().startswith("- Fact ")]
    assert len(lines) == 15


def test_format_tool_response():
    """Verify tool execution outputs are warmly formatted for human presentation."""
    task_res = format_tool_response("add_task", {"title": "Study for midterms", "due_date": "2026-10-10"})
    assert "Added task 'Study for midterms'" in task_res
    assert "Due 2026-10-10" in task_res

    res_plain = format_tool_response("unknown_tool", {"status": "ok"})
    assert res_plain == "Action completed."


def test_router_prompt_remains_lean():
    """Verify Nano router prompt remains fast (<400ms) without persona text bloat."""
    import inspect
    import backend.router as router_mod

    src = inspect.getsource(router_mod.route_message)
    assert "thinking partner" not in src
    assert "STARTING_PHRASES" not in src
    assert "PERSONA_CORE_INSTRUCTIONS" not in src


def test_tool_definitions_include_fact_tools():
    """Verify remember_fact and forget_fact are registered in base tool schemas."""
    tool_names = [t["function"]["name"] for t in BASE_TOOL_DEFINITIONS]
    assert "remember_fact" in tool_names
    assert "forget_fact" in tool_names

    remember_tool = next(t for t in BASE_TOOL_DEFINITIONS if t["function"]["name"] == "remember_fact")
    props = remember_tool["function"]["parameters"]["properties"]
    assert "key" in props
    assert "value" in props


def test_message_needs_tools_detects_personal_facts():
    """Verify message_needs_tools catches personal detail sharing."""
    assert message_needs_tools("My name is Jordan") is True
    assert message_needs_tools("call me Sam from now on") is True
    assert message_needs_tools("remember that I prefer dark mode") is True
    assert message_needs_tools("forget my preference") is True
    assert message_needs_tools("please forget that goal") is True

    # Pure greetings without facts bypass
    assert message_needs_tools("good morning!") is False
    assert message_needs_tools("how are things?") is False


def test_fallback_route_extracts_facts():
    """Verify rule-based fallback router properly identifies remember_fact and forget_fact."""
    # Remember name
    skill, args, _ = _fallback_route("My name is Taylor")
    assert skill == "remember_fact"
    assert args.get("key") == "name"
    assert args.get("value") == "Taylor"

    # Call me X
    skill, args, _ = _fallback_route("Please call me Alex")
    assert skill == "remember_fact"
    assert args.get("key") == "name"
    assert args.get("value") == "Alex"

    # Forget fact
    skill, args, _ = _fallback_route("Please forget my goal")
    assert skill == "forget_fact"
    assert args.get("key") == "goal"


@pytest.mark.asyncio
async def test_profile_handlers_execution():
    """Verify handle_remember_fact and handle_forget_fact skills."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with patch("backend.skills.handlers.profile.set_profile_fact", new_callable=AsyncMock) as mock_set:
        mock_set.return_value = {"key": "goal", "value": "Finish thesis"}
        res = await handle_remember_fact({"key": "goal", "value": "Finish thesis", "user_id": "u123"}, mock_pool)
        assert res["success"] is True
        assert res["data"]["key"] == "goal"
        assert res["data"]["value"] == "Finish thesis"
        assert "Finish thesis" in res["summary"]
        mock_set.assert_awaited_once_with(mock_conn, key="goal", value="Finish thesis", user_id="u123")

    with patch("backend.skills.handlers.profile.delete_profile_fact", new_callable=AsyncMock) as mock_del:
        mock_del.return_value = True
        res_del = await handle_forget_fact({"key": "goal", "user_id": "u123"}, mock_pool)
        assert res_del["success"] is True
        assert res_del["data"]["key"] == "goal"
        assert "forgotten" in res_del["summary"]
        mock_del.assert_awaited_once_with(mock_conn, key="goal", user_id="u123")


@pytest.mark.asyncio
async def test_memory_profile_db_queries():
    """Verify database CRUD functions for profile facts."""
    mock_conn = AsyncMock()

    # get_profile_facts
    mock_conn.fetch.return_value = [
        {"key": "name", "value": "Jordan"},
        {"key": "preference", "value": "Python"},
    ]
    facts = await get_profile_facts(mock_conn, user_id="u1")
    assert facts == {"name": "Jordan", "preference": "Python"}

    # set_profile_fact
    mock_conn.fetchrow.return_value = {"key": "goal", "value": "Pass exam"}
    set_res = await set_profile_fact(mock_conn, key="goal", value="Pass exam", user_id="u1")
    assert set_res["key"] == "goal"
    assert set_res["value"] == "Pass exam"

    # delete_profile_fact
    mock_conn.execute.return_value = "DELETE 1"
    deleted = await delete_profile_fact(mock_conn, key="goal", user_id="u1")
    assert deleted is True

    mock_conn.execute.return_value = "DELETE 0"
    deleted_false = await delete_profile_fact(mock_conn, key="nonexistent", user_id="u1")
    assert deleted_false is False


@pytest.mark.asyncio
async def test_profile_facts_api_endpoints(client: AsyncClient):
    """Verify GET and DELETE /api/profile/facts endpoints."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with patch("backend.routers.profile.get_pool", new_callable=AsyncMock) as mock_get_pool, \
         patch("backend.routers.profile.get_profile_facts", new_callable=AsyncMock) as mock_get_facts, \
         patch("backend.routers.profile.delete_profile_fact", new_callable=AsyncMock) as mock_del_fact:

        mock_get_pool.return_value = mock_pool
        mock_get_facts.return_value = {"name": "Jordan", "goal": "Hackathon"}
        mock_del_fact.return_value = True

        # Test GET /api/profile/facts
        resp_get = await client.get("/api/profile/facts")
        assert resp_get.status_code == 200
        data_get = resp_get.json()
        assert "facts" in data_get
        assert data_get["facts"]["name"] == "Jordan"

        # Test DELETE /api/profile/facts/{key}
        resp_del = await client.delete("/api/profile/facts/name")
        assert resp_del.status_code == 200
        data_del = resp_del.json()
        assert data_del["success"] is True
        assert data_del["deleted_key"] == "name"

        # Test DELETE 404 when key not found
        mock_del_fact.return_value = False
        resp_del_404 = await client.delete("/api/profile/facts/nonexistent")
        assert resp_del_404.status_code == 404
