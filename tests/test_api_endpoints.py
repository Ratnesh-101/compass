"""
Compass — API Endpoint Tests.

Tests:
  - Root redirect (/ -> /docs).
  - Health check endpoint (/health).
  - Authentication checks (401 for unauthorized access).
  - Authenticated queries across all endpoints.
  - CORS header responses for frontend origin.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_redirect(client: AsyncClient):
    """GET / should redirect to /docs."""
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/docs"


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """GET /health should return 200 without auth."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "db_connected" in data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/tasks",
        "/projects",
        "/dashboard",
        "/memory/timeline",
        "/admin/usage",
    ],
)
async def test_auth_enforcement(client: AsyncClient, path: str):
    """Unauthenticated requests must return 401 Unauthorized or 403 Forbidden."""
    resp = await client.get(path)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/tasks",
        "/projects",
        "/dashboard",
        "/memory/timeline",
        "/admin/usage",
    ],
)
async def test_authenticated_endpoints(client: AsyncClient, path: str, auth_headers: dict):
    """Authenticated requests should return 200 OK."""
    resp = await client.get(path, headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cors_headers(client: AsyncClient):
    """OPTIONS request with Vite frontend origin should include CORS headers."""
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    }
    resp = await client.options("/tasks", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
