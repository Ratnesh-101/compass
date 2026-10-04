"""
Compass — Tests for Guest Session Minting & Abuse Limiter.

Covers:
1. Real handler minting on isolated DB (returns 200 and verified guest token).
2. DB limiter error handling (returns 503 Service Unavailable, NOT 500).
3. Hourly IP mint budget and clear 429 message.
4. Admin override bypassing the hourly mint budget.
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch
from backend.dependencies import verify_guest_token
from backend.config import get_settings


@pytest.mark.asyncio
async def test_mint_guest_through_real_handler_isolated_db(client: AsyncClient):
    """Mints a guest session through the real handler on isolated test database."""
    resp = await client.post("/api/guest/session")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "guest_id" in data
    assert "guest_token" in data
    assert data["is_new"] is True

    # Validate HMAC cryptographic signature
    verified = verify_guest_token(data["guest_token"])
    assert verified == data["guest_id"]


@pytest.mark.asyncio
async def test_mint_guest_db_limiter_error_returns_503(client: AsyncClient):
    """When the DB rate limiter encounters a database failure, return 503 (NOT 500)."""
    with patch(
        "backend.services.rate_limiter.get_pool",
        side_effect=Exception("FATAL: Neon connection pool exhausted"),
    ):
        resp = await client.post("/api/guest/session")
        assert resp.status_code == 503
        assert "Service unavailable" in resp.json().get("detail", "")
        assert resp.status_code != 500


@pytest.mark.asyncio
async def test_mint_limiter_hourly_budget_and_admin_override(client: AsyncClient):
    """Hourly budget limits client IP minting, returns clear 429, and allows admin override."""
    settings = get_settings()
    client_ip = "198.51.100.77"
    headers = {"X-Forwarded-For": client_ip}

    # Simulate 5 mints within the hour (hourly budget)
    limit = getattr(settings, "GUEST_MINT_HOURLY_IP_LIMIT", 5)
    for _ in range(limit):
        res = await client.post("/api/guest/session", headers=headers)
        assert res.status_code in (200, 429)

    # Subsequent mint without admin auth must return 429 with clear message
    res_blocked = await client.post("/api/guest/session", headers=headers)
    assert res_blocked.status_code == 429
    assert f"max {limit} per hour" in res_blocked.json()["detail"]

    # Admin override with valid AUTH_TOKEN bypasses the mint rate limit
    admin_auth = {"Authorization": f"Bearer {settings.AUTH_TOKEN}", "X-Forwarded-For": client_ip}
    res_admin = await client.post("/api/guest/session", headers=admin_auth)
    assert res_admin.status_code == 200
    assert res_admin.json()["status"] == "ok"
