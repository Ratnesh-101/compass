"""
Compass x Tavily Integration Test Suite - Abstain-First Policy Tests.
"""

import pytest
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

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

from backend.config import get_settings
from backend.services import tavily as tavily_service
from backend.agent import run_agent

async def test_abstain_first_flag_off_current_behavior_unchanged(monkeypatch):
    """When TAVILY_ABSTAIN_FIRST is False, search_web is visible on step 1."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", False)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        return _create_mock_completion(content="Answer from step 1.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    steps = []
    async for step in run_agent(
        goal="Check live schedule",
        client=mock_client,
        max_steps=2,
        enable_critic=False,
    ):
        steps.append(step)

    assert len(captured_tools) >= 1
    tool_names = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" in tool_names


@pytest.mark.asyncio
async def test_abstain_first_flag_on_search_web_absent_on_step_1(monkeypatch):
    """When TAVILY_ABSTAIN_FIRST is True, search_web is excluded from step 1 tools."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        return _create_mock_completion(content="Answer from step 1.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    steps = []
    async for step in run_agent(
        goal="Check live schedule",
        client=mock_client,
        max_steps=2,
        enable_critic=False,
    ):
        steps.append(step)

    assert len(captured_tools) >= 1
    tool_names = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in tool_names


@pytest.mark.asyncio
async def test_abstain_first_flag_on_abstention_escalates_and_exposes_search_web(monkeypatch):
    """When TAVILY_ABSTAIN_FIRST is True, [ABSTAIN] in reasoning fires escalate and exposes search_web."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "search", AsyncMock(return_value={
        "results": [{"title": "Live Devpost", "url": "https://devpost.com/live", "content": "Deadline October 30", "score": 0.95}]
    }))

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        idx = len(captured_tools)
        if idx == 1:
            return _create_mock_completion(content="[ABSTAIN] Not in memory.")
        elif idx == 2:
            return _create_mock_completion(tool_name="search_web", tool_args={"query": "hackathon deadline"})
        return _create_mock_completion(content="Deadline verified as October 30.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    steps = []
    async for step in run_agent(
        goal="When is the hackathon deadline?",
        client=mock_client,
        max_steps=5,
        enable_critic=False,
    ):
        steps.append(step)

    escalate_steps = [s for s in steps if s.type == "escalate"]
    assert len(escalate_steps) == 1
    assert any(s.type == "tool_call" and s.tool_name == "search_web" for s in steps)

    # Step 1: search_web was absent
    names_step1 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in names_step1

    # Step 2 (after escalation): search_web was exposed
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" in names_step2


@pytest.mark.asyncio
async def test_abstain_first_flag_on_memory_query_with_results_no_web_call(monkeypatch):
    """When TAVILY_ABSTAIN_FIRST is True and memory query returns results, search_web remains hidden."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        idx = len(captured_tools)
        if idx == 1:
            return _create_mock_completion(tool_name="query_tasks", tool_args={"domain": "hackathon"})
        return _create_mock_completion(content="Found 2 hackathon tasks.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    # Mock query_tasks to return non-zero tasks
    from backend.skills import SKILL_REGISTRY
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "query_tasks",
        AsyncMock(return_value={"response": "Found 2 tasks", "data": [{"id": 1, "title": "Submit Demo"}, {"id": 2, "title": "Prep Slides"}]})
    )

    steps = []
    async for step in run_agent(
        goal="List hackathon tasks",
        client=mock_client,
        max_steps=4,
        enable_critic=False,
    ):
        steps.append(step)

    # In step 2, search_web should still NOT be present because memory returned results
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" not in names_step2
    assert not any(s.type == "escalate" for s in steps)
    assert not any(s.tool_name == "search_web" for s in steps)


@pytest.mark.asyncio
async def test_abstain_first_unlocks_on_real_query_tasks_empty(monkeypatch):
    """Verify abstain-first unlocks search_web when handle_query_tasks returns its real empty shape."""
    from backend.skills import handle_query_tasks, SKILL_REGISTRY

    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    # Obtain the real handler output shape
    real_empty_output = await handle_query_tasks({"domain": "hackathon"}, mock_pool)
    assert real_empty_output == {"response": "Found 0 task(s) in HACKATHON.", "data": []}

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        idx = len(captured_tools)
        if idx == 1:
            return _create_mock_completion(tool_name="query_tasks", tool_args={"domain": "hackathon"})
        return _create_mock_completion(content="No tasks found locally, searching web.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    monkeypatch.setitem(
        SKILL_REGISTRY,
        "query_tasks",
        AsyncMock(return_value=real_empty_output),
    )

    steps = []
    async for step in run_agent(
        goal="Check hackathon tasks",
        client=mock_client,
        max_steps=4,
        enable_critic=False,
    ):
        steps.append(step)

    # Step 1: search_web was absent
    names_step1 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in names_step1

    # Step 2: search_web must be unlocked due to zero-result memory query
    assert len(captured_tools) >= 2
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" in names_step2


@pytest.mark.asyncio
async def test_abstain_first_unlocks_on_real_query_coursework_notes_empty(monkeypatch):
    """Verify abstain-first unlocks search_web when handle_query_coursework_notes returns its real empty shape."""
    from backend.skills import handle_query_coursework_notes, SKILL_REGISTRY

    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    # Obtain the real handler output shape
    real_empty_output = await handle_query_coursework_notes({"query": "RISC-V lab notes"}, mock_pool)
    assert real_empty_output["response"] == "Retrieved 0 relevant memory chunk(s) for query: 'RISC-V lab notes'."
    assert real_empty_output["data"] == {"chunks": [], "count": 0}

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        idx = len(captured_tools)
        if idx == 1:
            return _create_mock_completion(tool_name="query_coursework_notes", tool_args={"query": "RISC-V lab notes"})
        return _create_mock_completion(content="No notes found locally, searching web.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    monkeypatch.setitem(
        SKILL_REGISTRY,
        "query_coursework_notes",
        AsyncMock(return_value=real_empty_output),
    )

    steps = []
    async for step in run_agent(
        goal="Find RISC-V notes",
        client=mock_client,
        max_steps=4,
        enable_critic=False,
    ):
        steps.append(step)

    # Step 1: search_web was absent
    names_step1 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in names_step1

    # Step 2: search_web must be unlocked due to zero-result memory query
    assert len(captured_tools) >= 2
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" in names_step2


@pytest.mark.asyncio
async def test_abstain_first_unlocks_on_real_query_code_context_empty(monkeypatch):
    """Verify abstain-first unlocks search_web when handle_query_code_context returns its real empty shape."""
    from backend.skills import handle_query_code_context, SKILL_REGISTRY

    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    # Obtain the real handler output shape
    real_empty_output = await handle_query_code_context({"query": "vector search"}, mock_pool)
    assert real_empty_output["response"] == "Retrieved 0 relevant memory chunk(s) for query: 'vector search'."
    assert real_empty_output["data"] == {"chunks": [], "count": 0}

    captured_tools = []

    async def mock_create(*args, **kwargs):
        captured_tools.append(kwargs.get("tools", []))
        idx = len(captured_tools)
        if idx == 1:
            return _create_mock_completion(tool_name="query_code_context", tool_args={"query": "vector search"})
        return _create_mock_completion(content="No code found locally, searching web.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    monkeypatch.setitem(
        SKILL_REGISTRY,
        "query_code_context",
        AsyncMock(return_value=real_empty_output),
    )

    steps = []
    async for step in run_agent(
        goal="Find code context",
        client=mock_client,
        max_steps=4,
        enable_critic=False,
    ):
        steps.append(step)

    # Step 1: search_web was absent
    names_step1 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in names_step1

    # Step 2: search_web must be unlocked due to zero-result memory query
    assert len(captured_tools) >= 2
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" in names_step2


