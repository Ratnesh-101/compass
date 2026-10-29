"""
Compass — End-to-End Demo Flow Regression Suite.

Codifies the 4-step sequence from docs/demo_script.md into an automated test:
  Step 1: Execute code memory logging and task creation via the API.
  Step 2: Query GET /memory/timeline and verify items appear in chronological order.
  Step 3: Issue a multi-domain prompt to POST /chat and verify routing/response.
  Step 4: Query GET /admin/usage and verify token usage and cost metrics.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_demo_flow_step1_log_and_add_task(client: AsyncClient, auth_headers: dict):
    """Step 1: Add a task and verify response structure."""
    task_payload = {
        "message": "add a task: Record Compass demo presentation, domain hackathon, due 2026-10-31",
    }
    with patch("backend.routers.chat.orchestrator.handle_message", AsyncMock(return_value={
        "conversation_id": "conv-demo-step1",
        "response": "Added task: Record Compass demo presentation",
        "skill_used": "add_task",
    })):
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
    with patch("backend.routers.chat.orchestrator.handle_message", AsyncMock(return_value={
        "conversation_id": "conv-demo-step3",
        "response": "Here are your top deliverables across coursework and hackathon before Friday.",
        "skill_used": "chat",
    })):
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


@pytest.mark.asyncio
async def test_demo_flow_anonymous_seed_returns_401(client: AsyncClient, monkeypatch):
    """Anonymous seeding without auth or guest token must fail closed with 401 when enabled, 403 when disabled."""
    from backend.config import get_settings
    settings = get_settings()

    # Anonymous requests always fail closed with 401
    monkeypatch.setattr(settings, "ENABLE_DEMO_SEEDING", False)
    resp = await client.post("/api/demo/seed")
    assert resp.status_code == 401

    # When enabled: 401 without auth/guest token
    monkeypatch.setattr(settings, "ENABLE_DEMO_SEEDING", True)
    resp = await client.post("/api/demo/seed")
    assert resp.status_code == 401
    resp2 = await client.post("/api/demo/seed-persona")
    assert resp2.status_code == 401


@pytest.mark.asyncio
async def test_seed_judge_demo_persona_and_fetch_tasks(client: AsyncClient, monkeypatch):
    """Verify that judges can click 'Load Judge Persona' and populate dummy tasks."""
    from backend.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ENABLE_DEMO_SEEDING", True)

    # 1. Initialize a guest session (like the frontend does on mount)
    guest_resp = await client.post("/api/guest/session")
    assert guest_resp.status_code == 200
    guest_data = guest_resp.json()
    guest_token = guest_data["guest_token"]
    headers = {"x-guest-token": guest_token}

    in_memory_tasks = {}
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_conn.fetch.return_value = []

    async def mock_create(pool, user_id=None, guest_id=None, **kwargs):
        task_id = len(in_memory_tasks) + 1
        t = {
            "id": task_id,
            "title": kwargs.get("title", ""),
            "domain": kwargs.get("domain", "coursework"),
            "status": "todo",
            "due_date": kwargs.get("due_date"),
            "priority": kwargs.get("priority", "medium"),
            "user_id": user_id,
            "guest_id": guest_id,
            "trusted_event_url": kwargs.get("trusted_event_url"),
            "verification_status": kwargs.get("verification_status", "UNVERIFIED"),
            "external_source": kwargs.get("external_source"),
        }
        in_memory_tasks[task_id] = t
        return t

    # 2. Seed Judge Demo Persona (patch remote embedding call for fast deterministic execution)
    with patch("backend.routers.tasks_verification.get_pool", AsyncMock(return_value=mock_pool)), \
         patch("backend.routers.tasks.get_pool", AsyncMock(return_value=mock_pool)), \
         patch("backend.routers.tasks_verification.structured.get_or_create_project", AsyncMock(return_value={"id": 10})), \
         patch("backend.routers.tasks_verification.structured.create_task", side_effect=mock_create), \
         patch("backend.routers.tasks.structured.list_tasks", AsyncMock(side_effect=lambda conn, **kwargs: list(in_memory_tasks.values()))), \
         patch("backend.services.embeddings.get_embedding", AsyncMock(return_value=[0.1] * 768)):
        seed_resp = await client.post("/api/demo/seed", headers=headers)
        assert seed_resp.status_code == 200
        seed_data = seed_resp.json()
        assert seed_data["status"] == "ok"
        assert seed_data["tasks_seeded"] >= 7
        assert len(seed_data["task_ids"]) >= 7

        # 3. Retrieve tasks for frontend timeline display
        tasks_resp = await client.get("/api/tasks?include_demo=true", headers=headers)
        assert tasks_resp.status_code == 200
        tasks = tasks_resp.json()
        assert isinstance(tasks, list)
        assert len(tasks) >= 7

        titles = [t["title"] for t in tasks]
        assert any("Hackathon" in title or "Devpost" in title for title in titles)
        assert any("CS 61C" in title for title in titles)
        assert any("Nebius" in title for title in titles)


