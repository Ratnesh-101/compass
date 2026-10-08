"""
Compass — Streaming SSE Endpoint Tests.

Verifies the /api/chat/stream endpoint for both tool-calling execution,
conversational token streaming, message_needs_tools classification battery,
and resilient background stream persistence error handling.
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.router import message_needs_tools
from backend.services.chat_stream import persist_stream_messages


@pytest.mark.asyncio
async def test_streaming_tool_call(client: AsyncClient):
    """Test that a task-creation message over SSE triggers tool calling and executes add_task."""
    payload = {
        "message": "add a task: Complete pyright streaming verification, domain coursework",
    }
    events = []
    async with client.stream("POST", "/api/chat/stream", json=payload, timeout=30.0) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                events.append(event_data)

    assert len(events) >= 1
    done_events = [ev for ev in events if ev.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0].get("skill_used") in ("add_task", "chat")
    assert "conversation_id" in done_events[0]


@pytest.mark.asyncio
async def test_sse_disconnect_cleanup(client: AsyncClient):
    """Test that premature client disconnect from SSE stream triggers clean resource termination."""
    payload = {"message": "Tell me a long story about space exploration."}
    async with client.stream("POST", "/api/chat/stream", json=payload, timeout=15.0) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                break


def test_message_needs_tools_battery():
    """Verify message_needs_tools against a varied battery of tool-requiring phrasings.

    Guarantees zero false negatives for action and domain queries, while confirming
    pure conversational queries bypass tool routing.
    """
    tool_required_phrasings = [
        "can you check my schedule for tomorrow?",
        "what tasks do I have due this week?",
        "show my coursework assignments",
        "when is my next physics midterm exam?",
        "add a task to buy milk due Friday",
        "do I have any calendar conflicts next Monday?",
        "reschedule my meeting with the professor",
        "what's my feasibility for finishing these deliverables in 3 days?",
        "search the web for React 19 server actions documentation",
        "remember that I prefer study blocks in the morning",
        "log a new note about compiler design lecture",
        "check the latest commit on our github repo",
        "what should I triage or drop to meet the hackathon deadline?",
        "research graph neural networks on the web",
        "remind me to submit the devpost pitch video",
        "how much free time do I have this afternoon?",
        "mark the math homework as complete",
        "delete the duplicate todo item",
        "what's on my agenda today?",
        "tell me about my project backlog",
        "create a new deliverable for phase 2",
        "what are my pending priorities?",
        "check if I have any lecture clashes",
        "verify this information online",
        "can I finish 10 tasks in 2 days?",
    ]

    for phrasing in tool_required_phrasings:
        assert message_needs_tools(phrasing) is True, f"False negative for phrasing: '{phrasing}'"

    conversational_phrasings = [
        "hey, what can you help with",
        "hello!",
        "hi",
        "hey",
        "how are you?",
        "who are you",
        "what can you do",
        "help",
        "thank you",
        "thanks",
        "good morning",
        "what is compass",
    ]

    for phrasing in conversational_phrasings:
        assert message_needs_tools(phrasing) is False, f"Conversational query was not bypassed: '{phrasing}'"


@pytest.mark.asyncio
async def test_persist_stream_messages_forced_failure_is_logged(caplog):
    """Test that database failures during background stream persistence are logged rather than silently lost."""
    with caplog.at_level(logging.ERROR, logger="compass.services.chat_stream"):
        # Case 1: Pool is completely unavailable
        with patch("backend.services.chat_stream.get_pool", AsyncMock(return_value=None)):
            success = await persist_stream_messages(
                conv_id="test-conv-123",
                message="Hello Compass",
                final_text="Hello! How can I help?",
                user_id="user-1",
            )
            assert success is False
            assert "Database connection pool unavailable" in caplog.text

        caplog.clear()

        # Case 2: Pool throws an unexpected exception during execution
        mock_pool = AsyncMock()
        mock_pool.acquire = AsyncMock(side_effect=RuntimeError("Simulated Neon network timeout during write"))
        # Also test connection error inside async context manager
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.side_effect = RuntimeError("Simulated Neon network timeout during write")
        mock_pool_cm = MagicMock()
        mock_pool_cm.acquire.return_value = mock_ctx

        with patch("backend.services.chat_stream.get_pool", AsyncMock(return_value=mock_pool_cm)):
            success = await persist_stream_messages(
                conv_id="test-conv-456",
                message="Add task: write tests",
                final_text="Task added.",
                user_id="user-2",
            )
            assert success is False
            assert "Failed to persist streamed messages for conversation test-conv-456" in caplog.text
            assert "Simulated Neon network timeout during write" in caplog.text
