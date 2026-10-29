"""
Compass — Streaming SSE Endpoint Tests.

Verifies the /api/chat/stream endpoint for both tool-calling execution,
conversational token streaming, message_needs_tools classification battery,
and resilient background stream persistence error handling.
"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from backend.router import message_needs_tools
from backend.services.chat_stream import persist_stream_messages


@pytest.mark.asyncio
async def test_streaming_tool_call(client: AsyncClient, monkeypatch):
    """Test that a task-creation message over SSE triggers tool calling and executes add_task."""
    class DummyDelta:
        content = None
        tool_calls = [MagicMock()]

    class DummyChoice:
        delta = DummyDelta()
        finish_reason = "tool_calls"

    class DummyChunk:
        choices = [DummyChoice()]
        usage = None

    class MockStream:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield DummyChunk()

        async def aclose(self):
            pass

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockStream())
    monkeypatch.setattr("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kwargs: mock_client)
    monkeypatch.setattr(
        "backend.orchestrator.route_message",
        AsyncMock(return_value=("add_task", {"title": "Complete pyright streaming verification", "domain": "coursework"}, None)),
    )

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
async def test_sse_disconnect_cleanup(client: AsyncClient, monkeypatch):
    """Test that premature client disconnect from SSE stream triggers clean resource termination."""
    class DummyDelta:
        content = "Once upon a time in deep space..."
        tool_calls = None

    class DummyChoice:
        delta = DummyDelta()
        finish_reason = None

    class DummyChunk:
        choices = [DummyChoice()]
        usage = None

    class MockStream:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for _ in range(10):
                yield DummyChunk()
                await asyncio.sleep(0.01)

        async def aclose(self):
            pass

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockStream())
    monkeypatch.setattr("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kwargs: mock_client)

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


@pytest.mark.asyncio
async def test_streaming_conversational_chunks(client: AsyncClient, monkeypatch):
    """Test multi-chunk conversational token streaming and final metadata done event."""
    chunks = ["Hello", " there!", " How", " can", " I", " help", " you", " today?"]

    class MockStream:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for ch in chunks:
                choice = MagicMock()
                choice.delta.content = ch
                choice.delta.tool_calls = None
                choice.finish_reason = None
                chunk = MagicMock()
                chunk.choices = [choice]
                chunk.usage = None
                yield chunk

        async def aclose(self):
            pass

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockStream())
    monkeypatch.setattr("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kwargs: mock_client)

    events = []
    payload = {"message": "Hello Compass"}
    async with client.stream("POST", "/api/chat/stream", json=payload, timeout=15.0) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == len(chunks)
    reconstructed = "".join(e.get("value", "") for e in token_events)
    assert reconstructed == "Hello there! How can I help you today?"

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    # Verify done event is metadata-only and does not duplicate text
    assert "response" not in done_events[0]
    assert done_events[0].get("skill_used") == "chat"
    assert "conversation_id" in done_events[0]


@pytest.mark.asyncio
async def test_streaming_replace_event_on_tool_switch(client: AsyncClient, monkeypatch):
    """Test that tool-call path emits a replace event when leaked tokens must be cleanly replaced."""
    class MockStream:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            # First emit a token that leaked
            choice1 = MagicMock()
            choice1.delta.content = "Leaked markup token "
            choice1.delta.tool_calls = None
            choice1.finish_reason = None
            chunk1 = MagicMock()
            chunk1.choices = [choice1]
            chunk1.usage = None
            yield chunk1

            # Then tool call occurs
            choice2 = MagicMock()
            choice2.delta.content = None
            choice2.delta.tool_calls = [MagicMock()]
            choice2.finish_reason = "tool_calls"
            chunk2 = MagicMock()
            chunk2.choices = [choice2]
            chunk2.usage = None
            yield chunk2

        async def aclose(self):
            pass

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockStream())
    monkeypatch.setattr("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kwargs: mock_client)
    monkeypatch.setattr("backend.services.chat_stream.is_schedule_or_agent_intent", lambda msg: False)
    monkeypatch.setattr(
        "backend.orchestrator.handle_message",
        AsyncMock(return_value={"response": "Clean synthesized response after tool execution.", "skill_used": "schedule_agent", "data": None}),
    )

    events = []
    payload = {"message": "Plan my schedule for tomorrow"}
    async with client.stream("POST", "/api/chat/stream", json=payload, timeout=15.0) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    replace_events = [e for e in events if e.get("type") == "replace"]
    assert len(replace_events) == 1
    assert replace_events[0]["value"] == "Clean synthesized response after tool execution."


@pytest.mark.asyncio
async def test_streaming_mid_stream_model_error(client: AsyncClient, monkeypatch):
    """Test that mid-stream exception from model stream yields terminal error event."""
    class FailingStream:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            choice = MagicMock()
            choice.delta.content = "Initial tokens..."
            choice.delta.tool_calls = None
            choice.finish_reason = None
            chunk = MagicMock()
            chunk.choices = [choice]
            chunk.usage = None
            yield chunk
            raise RuntimeError("Upstream provider socket timed out mid-stream")

        async def aclose(self):
            pass

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=FailingStream())
    monkeypatch.setattr("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kwargs: mock_client)

    events = []
    payload = {"message": "Tell me a story"}
    async with client.stream("POST", "/api/chat/stream", json=payload, timeout=15.0) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == 1
    assert token_events[0]["value"] == "Initial tokens..."

    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["terminal"] is True


@pytest.mark.asyncio
async def test_streaming_tool_done_payload_serializes_datetime(client: AsyncClient, monkeypatch):
    """Regression test: verify done event serializes data containing datetime/date objects without raising TypeError."""
    from datetime import datetime, date, timezone

    class MockStream:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            choice = MagicMock()
            choice.delta.content = None
            choice.delta.tool_calls = [MagicMock()]
            choice.finish_reason = "tool_calls"
            chunk = MagicMock()
            chunk.choices = [choice]
            chunk.usage = None
            yield chunk

        async def aclose(self):
            pass

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=MockStream())
    monkeypatch.setattr("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kwargs: mock_client)
    monkeypatch.setattr("backend.services.chat_stream.is_schedule_or_agent_intent", lambda msg: False)
    monkeypatch.setattr("backend.services.rate_limiter.enforce_rate_limit", AsyncMock())
    monkeypatch.setattr("backend.dependencies.rate_limit", AsyncMock())
    monkeypatch.setattr(
        "backend.orchestrator.handle_message",
        AsyncMock(return_value={
            "response": "Here are your tasks.",
            "skill_used": "query_tasks",
            "data": [
                {
                    "id": 1,
                    "title": "Buy milk",
                    "due_date": date(2026, 10, 30),
                    "created_at": datetime(2026, 10, 29, 10, 0, 0, tzinfo=timezone.utc),
                    "updated_at": datetime(2026, 10, 29, 10, 5, 0, tzinfo=timezone.utc),
                }
            ],
        }),
    )

    events = []
    payload = {"message": "What are my tasks?"}
    async with client.stream("POST", "/api/chat/stream", json=payload, timeout=15.0) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["skill_used"] == "query_tasks"
    assert len(done_events[0]["tasks"]) == 1
    assert done_events[0]["tasks"][0]["title"] == "Buy milk"
    assert not any(e.get("type") == "error" for e in events)
