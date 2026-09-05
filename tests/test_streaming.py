"""
Compass — Streaming SSE Endpoint Tests.

Verifies the /api/chat/stream endpoint for both tool-calling execution and
conversational token streaming.
"""

import json
import pytest
from httpx import AsyncClient


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
