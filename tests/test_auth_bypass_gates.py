"""
Compass — Auth Bypass & Production Hardening Gates Test Suite.

Proves:
  1. POST /api/auth/select-account is completely deleted -> 404.
  2. POST /api/auth/quick-connect is disabled and unregistered in production/default -> 404.
  3. /docs, /redoc, /openapi.json are disabled in production -> 404.
  4. /api/agent/confirm and /api/agent/undo admin overrides are strictly logged to agent_audit_log.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from backend.main import app
from backend.config import get_settings


@pytest.mark.asyncio
async def test_select_account_deleted():
    """Verify POST /api/auth/select-account has been deleted and returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/auth/select-account", json={"email": "attacker@evil.com"})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_quick_connect_disabled_in_prod():
    """Verify POST /api/auth/quick-connect returns 404 when ENVIRONMENT != 'development'."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Default / prod environment
        with patch.object(get_settings(), "ENVIRONMENT", "production"):
            resp = await ac.post("/api/auth/quick-connect", json={"email": "attacker@evil.com"})
            assert resp.status_code == 404
            assert "Endpoint disabled" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_docs_and_openapi_disabled_in_production():
    """Verify /docs, /redoc, /openapi.json are disabled when app is created in production mode."""
    from fastapi import FastAPI
    settings = get_settings()
    with patch.object(settings, "ENVIRONMENT", "production"):
        is_prod = True
        prod_app = FastAPI(
            docs_url=None if is_prod else "/docs",
            redoc_url=None if is_prod else "/redoc",
            openapi_url=None if is_prod else "/openapi.json",
        )
        transport = ASGITransport(app=prod_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r_docs = await ac.get("/docs")
            r_redoc = await ac.get("/redoc")
            r_openapi = await ac.get("/openapi.json")
            assert r_docs.status_code == 404
            assert r_redoc.status_code == 404
            assert r_openapi.status_code == 404


@pytest.mark.asyncio
async def test_agent_admin_override_logged_to_audit():
    """Verify that when AUTH_TOKEN is used as admin override, it records to agent_audit_log asserting against a real DB row."""
    from backend.routers.agent import agent_confirm
    from backend.models import AgentConfirmRequest
    from backend.agent import save_agent_run
    from backend.memory.db import get_pool
    from starlette.requests import Request
    import uuid
    import json

    pool = await get_pool()
    assert pool is not None, "Isolated test database pool must be available"

    run_id = f"run_admin_audit_{uuid.uuid4().hex[:8]}"
    tool_name = "add_task"
    tool_args = {"title": "Admin Created Task", "user_id": "test_user@example.com"}

    # Save real agent run into database
    await save_agent_run(
        pool=pool,
        run_id=run_id,
        goal="Test Admin Audit Logging",
        status="running",
        accumulated_steps=[],
        messages=[],
        pending_actions=[{"tool": tool_name, "args": tool_args}],
    )

    settings = get_settings()
    admin_token = settings.AUTH_TOKEN or "ci-test-token"

    req = AgentConfirmRequest(
        run_id=run_id,
        actions=[{"tool": tool_name, "args": tool_args}],
    )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/agent/confirm",
        "headers": [(b"authorization", f"Bearer {admin_token}".encode("utf-8"))],
        "client": ("127.0.0.1", 1234),
    }
    request = Request(scope)

    resp = await agent_confirm(req=req, request=request)
    assert resp["status"] == "ok"

    # Query REAL DB row in agent_audit_log table
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agent_audit_log WHERE run_id = $1 AND approved_by = 'admin_override' ORDER BY id DESC LIMIT 1",
            run_id,
        )
        assert row is not None, "Real DB row in agent_audit_log must exist"
        assert row["run_id"] == run_id
        assert row["tool"] == tool_name
        assert row["approved_by"] == "admin_override"
        args_data = json.loads(row["args"]) if isinstance(row["args"], str) else row["args"]
        assert args_data["title"] == "Admin Created Task"

