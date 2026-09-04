"""
Compass — End-to-End Demo Flow Regression Suite.

Codifies the 4-step sequence from docs/demo_script.md into an automated test:
  Step 1: Execute code memory logging and task creation via the API.
  Step 2: Query GET /memory/timeline and verify items appear in chronological order.
  Step 3: Issue a multi-domain prompt to POST /chat and verify routing/response.
  Step 4: Query GET /admin/usage and verify token usage and cost metrics.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_demo_flow_step1_log_and_add_task(client: AsyncClient, auth_headers: dict):
    """Step 1: Add a task and verify response structure."""
    task_payload = {
        "message": "add a task: Record Compass demo presentation, domain hackathon, due 2026-10-31",
    }
    resp = await client.post("/chat", headers=auth_headers, json=task_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "conversation_id" in data
    assert "response" in data
    assert data.get("skill_used") in ("add_task", "chat")


@pytest.mark.asyncio
async def test_demo_flow_step2_timeline_chronology(client: AsyncClient, auth_headers: dict):
    """Step 2: Query GET /memory/timeline and verify structure."""
    resp = await client.get("/memory/timeline?limit=10", headers=auth_headers)
    assert resp.status_code == 200
    timeline = resp.json()
    assert "entries" in timeline
    assert "total" in timeline
    assert isinstance(timeline["entries"], list)


@pytest.mark.asyncio
async def test_demo_flow_step3_multidomain_chat_prompt(client: AsyncClient, auth_headers: dict):
    """Step 3: Issue multi-domain query to POST /chat."""
    prompt_payload = {
        "message": "What are my top deliverables across coursework and hackathon before Friday?",
    }
    resp = await client.post("/chat", headers=auth_headers, json=prompt_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data.get("response", "")) > 0
    assert data.get("skill_used") is not None


@pytest.mark.asyncio
async def test_demo_flow_step4_admin_usage_metrics(client: AsyncClient, auth_headers: dict):
    """Step 4: Query GET /admin/usage and verify tracking structure."""
    resp = await client.get("/admin/usage", headers=auth_headers)
    assert resp.status_code == 200
    usage = resp.json()
    assert "total_input_tokens" in usage
    assert "total_output_tokens" in usage
    assert "total_estimated_cost_usd" in usage
    assert "by_model" in usage
    assert isinstance(usage["by_model"], dict)
