"""
Compass x Tavily Integration Test Suite - Repeated Memory Fallback Escalation Tests.
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

@pytest.mark.asyncio
async def test_run_5_repeated_memory_tools_fallback_escalates_before_max_steps(monkeypatch):
    """Replicate Run 5's tool-call sequence across memory tools and verify fallback triggers escalation before max_steps."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    run_5_tools = [
        ("get_hackathon_deadlines", {}),
        ("get_hackathon_deadlines", {}),
        ("query_coursework_notes", {"query": "Nebius hackathon deadline"}),
        ("query_coursework_notes", {"query": "Nebius hackathon deadline"}),
        ("query_coursework_notes", {"query": "Nebius hackathon deadline"}),
        ("get_hackathon_deadlines", {}),
        ("get_hackathon_deadlines", {}),
        ("query_tasks", {"domain": "hackathon"}),
    ]

    call_count = 0

    async def mock_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # If forced_tool_choice was search_web or tool_choice function is search_web
        tool_choice = kwargs.get("tool_choice")
        if isinstance(tool_choice, dict) and tool_choice.get("function", {}).get("name") == "search_web":
            return _create_mock_completion(tool_name="search_web", tool_args={"query": "Nebius hackathon deadline Devpost"})
        if any(m.get("role") == "tool" and "Devpost" in str(m.get("content", "")) for m in kwargs.get("messages", [])):
            return _create_mock_completion(content="The official submission deadline is October 30, 2026.")

        # Replicate tool calls from Run 5
        idx = min(call_count - 1, len(run_5_tools) - 1)
        t_name, t_args = run_5_tools[idx]
        return _create_mock_completion(tool_name=t_name, tool_args=t_args)

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    from backend.skills import SKILL_REGISTRY
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "get_hackathon_deadlines",
        AsyncMock(return_value={"response": "🚀 Hackathon: 6 active deliverables for Nebius Token Factory benchmark.", "data": {"tasks": [{"title": "Demo"}], "count": 6}}),
    )
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "query_coursework_notes",
        AsyncMock(return_value={"response": "No coursework notes found.", "data": {"notes": []}}),
    )
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "query_tasks",
        AsyncMock(return_value={"response": "Found 6 task(s) in HACKATHON.", "data": {"tasks": [{"title": "Task 1"}], "count": 6}}),
    )
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "search_web",
        AsyncMock(return_value={"response": "Devpost deadline: October 30, 2026 at 10:00 AM PDT", "data": {"results": []}}),
    )

    steps = []
    async for step in run_agent(
        goal="What is the official submission deadline date for the Nebius x NVIDIA AI Hackathon on Devpost?",
        client=mock_client,
        max_steps=8,
        enable_critic=False,
    ):
        steps.append(step)

    step_types = [s.type for s in steps]
    assert "escalate" in step_types, f"Expected 'escalate' step in {step_types}"
    assert any(s.tool_name == "search_web" for s in steps), "Expected search_web to be executed after escalation"
    assert any(s.type == "done" for s in steps), "Expected run to complete with 'done'"


@pytest.mark.asyncio
async def test_one_memory_tool_then_abstain_produces_escalate_step(monkeypatch):
    """Item 4: Mock model that calls one memory tool, gets nothing useful, then emits '[ABSTAIN] ...' as text.
    Assert this produces an escalate step (not silent unlock).
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    captured_tools = []
    call_count = 0

    async def mock_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_tools.append(kwargs.get("tools", []))

        # Turn 1: call widened memory tool get_hackathon_deadlines
        if call_count == 1:
            return _create_mock_completion(tool_name="get_hackathon_deadlines", tool_args={})

        # Turn 2: model sees get_hackathon_deadlines returned no deadline, and search_web is still locked
        # Model emits [ABSTAIN] as text
        if call_count == 2:
            return _create_mock_completion(content="[ABSTAIN] The stored hackathon data does not contain the official Devpost deadline.")

        # Turn 3: after escalate step, forced_tool_choice="search_web"
        tool_choice = kwargs.get("tool_choice")
        if isinstance(tool_choice, dict) and tool_choice.get("function", {}).get("name") == "search_web":
            return _create_mock_completion(tool_name="search_web", tool_args={"query": "Nebius hackathon Devpost deadline"})

        # Turn 4: synthesize answer
        return _create_mock_completion(content="The official submission deadline is October 30, 2026.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    from backend.skills import SKILL_REGISTRY
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "get_hackathon_deadlines",
        AsyncMock(return_value={"response": "🚀 Hackathon: 0 active deliverables.", "data": {"tasks": [], "count": 0}}),
    )
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "search_web",
        AsyncMock(return_value={"response": "Devpost deadline: October 30, 2026", "data": {"results": []}}),
    )

    steps = []
    async for step in run_agent(
        goal="What is the official submission deadline date for the Nebius x NVIDIA AI Hackathon on Devpost?",
        client=mock_client,
        max_steps=6,
        enable_critic=False,
    ):
        steps.append(step)

    # Step 1: search_web was locked
    names_step1 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in names_step1

    # Step 2: after 1 unhelpful call, one-tool grace period keeps search_web locked
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" not in names_step2, "search_web should NOT be auto-unlocked after just 1 unhelpful memory tool call"

    # Verify escalate step was emitted
    escalate_steps = [s for s in steps if s.type == "escalate"]
    assert len(escalate_steps) >= 1, f"Expected escalate step, found: {[s.type for s in steps]}"
    assert escalate_steps[0].type == "escalate"

    # Verify search_web was called and agent completed
    assert any(s.type == "tool_call" and s.tool_name == "search_web" for s in steps)
    assert any(s.type == "done" for s in steps)


@pytest.mark.asyncio
async def test_two_memory_tools_back_to_back_falls_back_to_silent_unlock(monkeypatch):
    """Item 5: Mock model that calls two memory tools back to back without ever emitting [ABSTAIN].
    Assert this falls back to silent unlock (not stalling).
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ABSTAIN_FIRST", True)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)

    captured_tools = []
    call_count = 0

    async def mock_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        captured_tools.append(kwargs.get("tools", []))

        # Turn 1: call first memory tool
        if call_count == 1:
            return _create_mock_completion(tool_name="get_hackathon_deadlines", tool_args={})

        # Turn 2: model calls second memory tool without emitting [ABSTAIN]
        if call_count == 2:
            return _create_mock_completion(tool_name="list_projects", tool_args={})

        # Turn 3: search_web should now be silently unlocked in available tools
        current_tools = kwargs.get("tools", [])
        tool_names = [
            t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
            for t in current_tools
        ]
        if "search_web" in tool_names:
            return _create_mock_completion(tool_name="search_web", tool_args={"query": "Nebius hackathon Devpost deadline"})

        return _create_mock_completion(content="No tools left.")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=mock_create)

    from backend.skills import SKILL_REGISTRY
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "get_hackathon_deadlines",
        AsyncMock(return_value={"response": "🚀 Hackathon: 0 active deliverables.", "data": {"tasks": [], "count": 0}}),
    )
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "list_projects",
        AsyncMock(return_value={"response": "0 projects found.", "data": {"projects": []}}),
    )
    monkeypatch.setitem(
        SKILL_REGISTRY,
        "search_web",
        AsyncMock(return_value={"response": "Devpost deadline: October 30, 2026", "data": {"results": []}}),
    )

    steps = []
    async for step in run_agent(
        goal="Find deadline for hackathon",
        client=mock_client,
        max_steps=5,
        enable_critic=False,
    ):
        steps.append(step)

    # Step 1: search_web was absent
    names_step1 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[0]
    ]
    assert "search_web" not in names_step1

    # Step 2: search_web still absent (1-tool grace period)
    assert len(captured_tools) >= 2
    names_step2 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[1]
    ]
    assert "search_web" not in names_step2

    # Step 3: after 2nd memory tool, search_web MUST be silently unlocked
    assert len(captured_tools) >= 3
    names_step3 = [
        t.get("function", {}).get("name") if isinstance(t.get("function"), dict) else t.get("name")
        for t in captured_tools[2]
    ]
    assert "search_web" in names_step3

    # Assert this fell back to silent unlock, not explicit escalate step
    assert not any(s.type == "escalate" for s in steps), "Should fall back to silent unlock without an explicit escalate step"
    # Assert it called search_web and didn't stall
    assert any(s.tool_name == "search_web" for s in steps)



