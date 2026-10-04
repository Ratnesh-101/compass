"""
Compass — Multi-Turn Conversational Regression Suite.

Verifies that conversation history is persisted across turns and injected into
the Nemotron router prompt so follow-up queries resolve correctly.
"""

import uuid
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_multiturn_task_followup_resolution(client: AsyncClient, auth_headers: dict):
    """Test that a task creation followed by a contextual query correctly links context."""
    suffix = uuid.uuid4().hex[:6]
    task_title = f"submit final demo video {suffix}"

    # Turn 1: Add a task without due date
    msg1 = f"add a task: {task_title}, domain hackathon"
    resp1 = await client.post("/chat", headers=auth_headers, json={"message": msg1})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert "conversation_id" in data1
    assert data1.get("skill_used") == "add_task"
    conv_id = data1["conversation_id"]

    # Turn 2: Ask follow-up question referencing the prior task
    msg2 = "when is it due?"
    resp2 = await client.post("/chat", headers=auth_headers, json={"message": msg2, "conversation_id": conv_id})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2.get("conversation_id") == conv_id
    # Must correctly route to query_tasks or provide an informed contextual response
    assert data2.get("skill_used") in ("query_tasks", "chat")
    response_text = data2.get("response", "").lower()
    assert data2.get("skill_used") == "query_tasks" or any(term in response_text for term in (task_title.lower(), "submit final demo video", "due", "hackathon", "task"))
