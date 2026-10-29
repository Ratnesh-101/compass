"""
Tests for model empty-response handling, bounded retries, tool shedding, and failure propagation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend import orchestrator
from backend.router import route_message
from backend.router_helpers import message_needs_tools
from backend.skills.handlers.context import handle_summarize_day


def _make_mock_response(content="", tool_calls=None):
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=20, completion_tokens=10)
    return resp


@pytest.mark.asyncio
async def test_empty_provider_completion_retries_and_succeeds():
    """Verify that if attempt 1 returns empty content, attempt 2 retries without tools and recovers."""
    mock_client = MagicMock()
    # First attempt: empty content; second attempt: valid response
    resp_empty = _make_mock_response(content="")
    resp_ok = _make_mock_response(content="The MESI protocol defines Modified, Exclusive, Shared, and Invalid states.")
    mock_client.chat.completions.create = AsyncMock(side_effect=[resp_empty, resp_ok])

    with patch("backend.router.get_openai_client", return_value=mock_client):
        skill_name, args, text_reply = await route_message(
            "Provide a detailed deep dive into how the MESI cache coherence protocol works and its four states."
        )
        assert mock_client.chat.completions.create.call_count == 2
        # Verify first call had tools, second call dropped tools for clean chat recovery
        call_1_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
        call_2_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "tools" not in call_2_kwargs or call_2_kwargs.get("tools") is None
        assert skill_name is None
        assert "MESI protocol" in text_reply


@pytest.mark.asyncio
async def test_empty_provider_completion_exhaustion_propagates_error():
    """Verify that when all bounded retry attempts return empty content, empty_model_response is reported with can_retry=True."""
    mock_client = MagicMock()
    resp_empty1 = _make_mock_response(content="")
    resp_empty2 = _make_mock_response(content="")
    mock_client.chat.completions.create = AsyncMock(side_effect=[resp_empty1, resp_empty2])

    with patch("backend.router.get_openai_client", return_value=mock_client):
        result = await orchestrator.handle_message(
            conversation_id="test-empty-exhaustion",
            message="Explain quantum entanglement in detail.",
            persist=False,
        )
        assert mock_client.chat.completions.create.call_count == 2
        assert result["success"] is False
        assert result["error"] == "empty_model_response"
        assert result.get("data", {}).get("can_retry") is True
        assert "empty response" in result["response"].lower() or "retry" in result["response"].lower()


@pytest.mark.asyncio
async def test_transient_provider_exception_retries_and_succeeds():
    """Verify that a transient network exception on attempt 1 is retried safely and succeeds on attempt 2."""
    mock_client = MagicMock()
    resp_ok = _make_mock_response(content="RISC stands for Reduced Instruction Set Computer.")
    mock_client.chat.completions.create = AsyncMock(side_effect=[
        Exception("Connection reset by peer"),
        resp_ok,
    ])

    with patch("backend.router.get_openai_client", return_value=mock_client):
        skill_name, args, text_reply = await route_message("What does RISC stand for?")
        assert mock_client.chat.completions.create.call_count == 2
        assert "Reduced Instruction Set Computer" in text_reply


@pytest.mark.asyncio
async def test_provider_exception_exhaustion_propagates_cleanly():
    """Verify that when all attempts fail with exceptions, error is handled safely without leaking raw credentials."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("Bearer secret_token_123 failed 503"))

    with patch("backend.router.get_openai_client", return_value=mock_client):
        result = await orchestrator.handle_message(
            conversation_id="test-exception-exhaustion",
            message="What is the difference between TCP and UDP?",
            persist=False,
        )
        assert result["success"] is False
        assert "secret_token_123" not in result["response"]
        assert result["error"] == "empty_model_response"


@pytest.mark.asyncio
async def test_no_duplicate_tool_calls_on_retry():
    """Verify that when the LLM returns a tool call, it is NEVER retried, preventing duplicate mutations."""
    mock_client = MagicMock()
    tc = MagicMock()
    tc.function.name = "query_code_context"
    tc.function.arguments = '{"query": "auth tokens"}'
    resp_tool = _make_mock_response(content="", tool_calls=[tc])
    mock_client.chat.completions.create = AsyncMock(return_value=resp_tool)

    with patch("backend.router.get_openai_client", return_value=mock_client):
        skill_name, args, text_reply = await route_message("Search codebase for auth tokens")
        assert mock_client.chat.completions.create.call_count == 1
        assert skill_name == "query_code_context"
        assert args is not None
        assert args["query"] == "auth tokens"


@pytest.mark.asyncio
async def test_malformed_response_empty_choices():
    """Verify that if choices is an empty list, it does not crash with IndexError and retries/recovers."""
    mock_client = MagicMock()
    empty_choices_resp = MagicMock(choices=[], usage=None)
    resp_ok = _make_mock_response(content="Hello! How can I help you?")
    mock_client.chat.completions.create = AsyncMock(side_effect=[empty_choices_resp, resp_ok])

    with patch("backend.router.get_openai_client", return_value=mock_client):
        skill_name, args, text_reply = await route_message("Hello")
        assert mock_client.chat.completions.create.call_count == 2
        assert "How can I help" in text_reply


def test_message_needs_tools_word_boundary_no_false_positives():
    """Verify that short keywords like 'pr' or 'git' do not trigger tool attachment on non-tool technical terms."""
    # 'pr' inside 'protocol', 'provide', 'sprint' must NOT trigger tools
    assert message_needs_tools("Provide a detailed deep dive into how the MESI cache coherence protocol works and its four states.") is False
    assert message_needs_tools("What does RISC stand for?") is False
    assert message_needs_tools("Can you explain what CPU pipelining is in simple terms for a beginner?") is False
    assert message_needs_tools("Can you help me with my work?") is False

    # Actual tool queries must trigger tools
    assert message_needs_tools("Check my PR on github") is True
    assert message_needs_tools("Add a task to buy groceries") is True
    assert message_needs_tools("What tasks do I have due today?") is True


@pytest.mark.asyncio
async def test_summarize_day_communicates_total_task_count():
    """Verify handle_summarize_day explicitly communicates the total task count (e.g. 369) in large collections."""
    large_task_set = [
        {"id": 1, "title": "Urgent Token Factory Benchmark", "domain": "hackathon", "due_date": "2026-10-17", "priority": "urgent", "status": "open"},
        {"id": 2, "title": "CS 61C RISC-V Report", "domain": "coursework", "due_date": "2026-10-18", "priority": "high", "status": "open"},
    ] + [
        {"id": i, "title": f"Archived Task #{i}", "domain": "general", "due_date": None, "priority": "low", "status": "open"}
        for i in range(3, 370)
    ]
    assert len(large_task_set) == 369

    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("backend.memory.structured.list_tasks", new_callable=AsyncMock, return_value=large_task_set), \
         patch("backend.config.get_settings") as mock_settings:
        mock_settings.return_value.NEBIUS_API_KEY = None
        result = await handle_summarize_day({"user_id": "summary_user"}, mock_pool)
        assert result["data"]["total"] == 369
        assert "369" in result["response"]
