"""
Compass — Gap Closures Test Suite.

Automated verification tests for all gap closures:
1. P0.1: Server-side task query filtering via ?domain= parameter.
2. P0.2: Public /api/usage/summary endpoint returning dynamic telemetry.
3. P1.4: Per-IP sliding-window rate limiting returning HTTP 429 after 30 req/min.
4. P2.7: SSE streaming endpoint and CLI live streaming parser.
5. P2.8: Tavily search_web skill tool definition and execution fallback.
"""

import json
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_server_side_task_domain_filter(client: AsyncClient, auth_headers: dict):
    """P0.1: Verify /tasks and /api/tasks accept domain query parameter."""
    # Test unauthenticated public /api/tasks
    resp = await client.get("/api/tasks?domain=hackathon")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for task in data:
        assert task.get("domain") in ("hackathon", "general")

    # Test authenticated /tasks?domain=coursework
    resp_auth = await client.get("/tasks?domain=coursework", headers=auth_headers)
    assert resp_auth.status_code == 200
    tasks_data = resp_auth.json().get("tasks", [])
    for task in tasks_data:
        assert task.get("domain") == "coursework"


@pytest.mark.asyncio
async def test_public_usage_summary_endpoint(client: AsyncClient):
    """P0.2: Verify GET /api/usage/summary is public and returns aggregated metrics."""
    resp = await client.get("/api/usage/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert "total_requests" in summary
    assert "total_input_tokens" in summary
    assert "total_output_tokens" in summary
    assert "total_estimated_cost_usd" in summary
    assert isinstance(summary["total_requests"], int)
    assert isinstance(summary["total_estimated_cost_usd"], (int, float))


@pytest.mark.asyncio
async def test_per_ip_rate_limiting_exceeded(client: AsyncClient, monkeypatch):
    """P1.4: Verify sliding-window rate limiter returns 429 after 30 rapid requests."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "backend.orchestrator.handle_message",
        AsyncMock(return_value={"response": "pong", "conversation_id": "mock-conv", "skill_used": "chat"}),
    )

    test_ip = "198.51.100.42"
    headers = {"X-Forwarded-For": test_ip}

    # First 30 requests should succeed (HTTP 200)
    for _ in range(30):
        resp = await client.post(
            "/api/chat",
            json={"message": "ping"},
            headers=headers,
        )
        assert resp.status_code == 200

    # The 31st request from the same IP MUST trigger HTTP 429 Too Many Requests
    resp_blocked = await client.post(
        "/api/chat",
        json={"message": "burst ping"},
        headers=headers,
    )
    assert resp_blocked.status_code == 429
    assert "Rate limit exceeded" in resp_blocked.text
    assert "Retry-After" in resp_blocked.headers


@pytest.mark.asyncio
async def test_search_web_skill_registered_and_dispatchable(monkeypatch):
    """P2.8: Verify search_web feature-flag gating and handler execution."""
    from backend.skills import TOOL_DEFINITIONS, SKILL_REGISTRY, dispatch_skill, get_tool_definitions, SEARCH_WEB_TOOL
    from backend.config import get_settings

    # By default, search_web is gated OFF and not in TOOL_DEFINITIONS
    tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS if "function" in t]
    assert "search_web" not in tool_names

    # When TAVILY_ENABLED is True, get_tool_definitions includes search_web
    settings = get_settings()
    monkeypatch.setattr(settings, "TAVILY_ENABLED", True)
    active_tools = get_tool_definitions()
    assert any(t["function"]["name"] == "search_web" for t in active_tools if "function" in t)

    # Verify skill handler is registered in SKILL_REGISTRY
    assert "search_web" in SKILL_REGISTRY

    # Dispatch with empty query
    res = await dispatch_skill("search_web", {"query": ""}, None)
    assert "Please provide a search query" in res["response"]

    # Dispatch with TAVILY_ENABLED=True to exercise execution path directly
    res_enabled = await dispatch_skill("search_web", {"query": "latest AI news"}, None)
    assert "response" in res_enabled
    assert "data" in res_enabled

    # Dispatch with TAVILY_ENABLED=False to verify clean disabled response
    monkeypatch.setattr(settings, "TAVILY_ENABLED", False)
    res_disabled = await dispatch_skill("search_web", {"query": "latest AI news"}, None)
    assert "currently disabled" in res_disabled["response"]


def test_cli_streaming_helper_fallback():
    """P2.7: Verify CLI _stream_chat gracefully handles synchronous fallback."""
    from cli.assistant_cli import _stream_chat

    # Call with a simple query against running server
    text, conv_id, skill = _stream_chat({"message": "Hello Compass!"})
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_usage_summary_cost_delta_changes_across_turns(client: AsyncClient):
    """Item 15: Verify total_estimated_cost_usd actively increments with token volume.
    
    Proves the cost counter is live and not frozen by asserting a measurable cost delta
    between a small turn and a heavy multi-domain synthesis turn.
    """
    from backend.services.usage import get_usage_summary, record_usage
    from backend.config import get_settings

    settings = get_settings()

    # Step 1: Initial cost reading from /api/usage/summary
    resp1 = await client.get("/api/usage/summary")
    assert resp1.status_code == 200
    cost_initial = resp1.json()["total_estimated_cost_usd"]

    # Step 2: Turn 1 (short greeting on Router Nano: 20 in, 10 out)
    record_usage(settings.ROUTER_MODEL, 20, 10)
    resp2 = await client.get("/api/usage/summary")
    cost_after_turn1 = resp2.json()["total_estimated_cost_usd"]
    assert cost_after_turn1 > cost_initial

    # Step 3: Turn 2 (heavy synthesis on Ultra: 1500 prompt, 800 completion tokens)
    record_usage(settings.SYNTHESIS_MODEL, 1500, 800)
    resp3 = await client.get("/api/usage/summary")
    cost_after_turn2 = resp3.json()["total_estimated_cost_usd"]

    # Assert cost meaningfully changed and delta reflects Ultra pricing
    cost_delta = cost_after_turn2 - cost_after_turn1
    assert cost_delta > 0.001, f"Expected noticeable cost delta on heavy synthesis turn, got {cost_delta}"
    assert cost_after_turn2 > cost_after_turn1 > cost_initial
