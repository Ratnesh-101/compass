import pytest
from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.dependencies import generate_guest_token
from backend.config import get_settings


@pytest.mark.asyncio
async def test_unauthenticated_post_api_chat_rejected(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GUEST_SIGNING_SECRET", "test-secret-12345678901234567890")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Completely unauthenticated request in production
        resp = await client.post(
            "/api/chat",
            json={"message": "Hello without token"},
        )
        assert resp.status_code == 401, f"Expected 401 for unauthenticated chat, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_guest_post_api_chat_accepted(monkeypatch):
    from unittest.mock import AsyncMock
    from backend import orchestrator

    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GUEST_SIGNING_SECRET", "test-secret-12345678901234567890")

    # Mock handle_message so we don't call real Nebius
    mock_handle = AsyncMock(return_value={
        "response": "Hello guest",
        "routing_latency_ms": 10,
        "message": "Hello guest",
        "conversation_id": "conv_guest_1",
        "skill_used": "chat",
    })
    monkeypatch.setattr(orchestrator, "handle_message", mock_handle)

    guest_id, guest_token = generate_guest_token()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/chat",
            json={"message": "Hello as guest"},
            headers={"x-guest-token": guest_token},
        )
        assert resp.status_code == 200, f"Expected 200 for signed guest token, got {resp.status_code}: {resp.text}"
        assert resp.json()["response"] == "Hello guest"
