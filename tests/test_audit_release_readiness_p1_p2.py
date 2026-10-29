"""
tests/test_audit_release_readiness_p1_p2.py
Comprehensive regression battery covering the Compass Release Readiness Audit fixes:
1. P1: Protect /api/demo/seed (401 without valid identity, reject forged guest token, zero mutations on reject)
2. P1: Enforce Vector-Memory Isolation (Guest A, Guest B, User A, User B, Public memory)
3. P1: Google OAuth Fail-Closed Battery (success, timeout, non-200, missing email, unverified email, malformed, no session / generic login)
4. P2: Same-IP Guest Session Isolation (two guests sharing an IP remain strictly isolated)
5. P2: Roadmap Intent Detection & Informational Filtering
"""
from __future__ import annotations

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from backend.main import app
from backend.dependencies import generate_guest_token
from backend.routers.auth import create_session
from backend.memory.db import get_pool
from backend.memory.vector import store_chunk, search_chunks
from backend.config import get_settings
from backend.services.oauth import exchange_code_for_tokens
from backend.router_helpers import is_schedule_or_agent_intent, _fallback_route


# ===========================================================================
# 1. P1: PROTECT /api/demo/seed
# ===========================================================================

@pytest.mark.asyncio
async def test_demo_seed_unauthenticated_request_rejected():
    """Requests without authentication or valid guest identity must return 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/demo/seed")
        assert res.status_code == 401
        assert "authentication required" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_demo_seed_forged_guest_token_rejected():
    """Requests with forged or tampered guest credentials must return 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        forged_token = f"{uuid.uuid4()}.123456789.bad_signature"
        res = await client.post("/api/demo/seed", headers={"x-guest-token": forged_token})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_demo_seed_rejected_causes_zero_database_writes():
    """A rejected request must not perform database mutations."""
    pool = await get_pool()
    initial_count = 0
    if pool:
        async with pool.acquire() as conn:
            initial_count = await conn.fetchval("SELECT COUNT(*) FROM tasks")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/demo/seed")
        assert res.status_code == 401

    if pool:
        async with pool.acquire() as conn:
            final_count = await conn.fetchval("SELECT COUNT(*) FROM tasks")
            assert final_count == initial_count


@pytest.mark.asyncio
async def test_demo_seed_authenticated_user_succeeds(monkeypatch):
    """A request with valid authenticated identity succeeds and seeds tasks."""
    monkeypatch.setattr(get_settings(), "ENABLE_DEMO_SEEDING", True)
    user_email = f"tester_{uuid.uuid4().hex[:6]}@example.com"
    session_token = create_session(user_email)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/demo/seed",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "ok"
        assert data.get("user_id") == user_email


# ===========================================================================
# 2. P1: VECTOR-MEMORY ISOLATION
# ===========================================================================

@pytest.mark.asyncio
async def test_vector_memory_isolation_across_tenants():
    """
    Seed test chunks in an isolated test domain:
    1. Guest A
    2. Guest B
    3. Signed-in User A
    4. Signed-in User B
    5. Intentionally shared/public content (user_id=None)
    Verify that each identity retrieves only its permitted records.
    """
    pool = await get_pool()
    if not pool:
        pytest.skip("PostgreSQL with pgvector pool required for vector isolation test")

    guest_a_id = f"guest_a_{uuid.uuid4().hex[:8]}"
    guest_b_id = f"guest_b_{uuid.uuid4().hex[:8]}"
    user_a_id = f"user_a_{uuid.uuid4().hex[:8]}@example.com"
    user_b_id = f"user_b_{uuid.uuid4().hex[:8]}@example.com"

    test_domain = f"iso_{uuid.uuid4().hex[:8]}"
    with patch("backend.memory.vector.get_embedding", AsyncMock(return_value=[0.05] * 768)):
        async with pool.acquire() as conn:
            await store_chunk(conn, "Secret notes of Guest A", domain=test_domain, user_id=guest_a_id)
            await store_chunk(conn, "Secret notes of Guest B", domain=test_domain, user_id=guest_b_id)
            await store_chunk(conn, "Confidential plan of User A", domain=test_domain, user_id=user_a_id)
            await store_chunk(conn, "Confidential plan of User B", domain=test_domain, user_id=user_b_id)
            await store_chunk(conn, "Public institutional policy", domain=test_domain, user_id=None)

            # 1. Guest A searches: sees Guest A + Public, NEVER Guest B, User A, User B
            res_ga = await search_chunks(conn, "notes plan policy", domain=test_domain, user_id=guest_a_id, limit=10)
            texts_ga = [r["content"] for r in res_ga]
            assert any("Guest A" in t for t in texts_ga)
            assert not any("Guest B" in t for t in texts_ga)
            assert not any("User A" in t for t in texts_ga)
            assert not any("User B" in t for t in texts_ga)

            # 2. Guest B searches: sees Guest B + Public, NEVER Guest A, User A, User B
            res_gb = await search_chunks(conn, "notes plan policy", domain=test_domain, user_id=guest_b_id, limit=10)
            texts_gb = [r["content"] for r in res_gb]
            assert any("Guest B" in t for t in texts_gb)
            assert not any("Guest A" in t for t in texts_gb)
            assert not any("User A" in t for t in texts_gb)
            assert not any("User B" in t for t in texts_gb)

            # 3. User A searches: sees User A + Public, NEVER User B, Guest A, Guest B
            res_ua = await search_chunks(conn, "notes plan policy", domain=test_domain, user_id=user_a_id, limit=10)
            texts_ua = [r["content"] for r in res_ua]
            assert any("User A" in t for t in texts_ua)
            assert not any("User B" in t for t in texts_ua)
            assert not any("Guest A" in t for t in texts_ua)
            assert not any("Guest B" in t for t in texts_ua)

            # 4. User B searches: sees User B + Public, NEVER User A, Guest A, Guest B
            res_ub = await search_chunks(conn, "notes plan policy", domain=test_domain, user_id=user_b_id, limit=10)
            texts_ub = [r["content"] for r in res_ub]
            assert any("User B" in t for t in texts_ub)
            assert not any("User A" in t for t in texts_ub)
            assert not any("Guest A" in t for t in texts_ub)
            assert not any("Guest B" in t for t in texts_ub)

            # 5. Anonymous / None searches: fails closed under null-owner isolation (returns [])
            res_anon = await search_chunks(conn, "notes plan policy", domain=test_domain, user_id=None, limit=10)
            assert res_anon == []


# ===========================================================================
# 3. P1: GOOGLE OAUTH FAIL-CLOSED BATTERY
# ===========================================================================

@pytest.mark.asyncio
async def test_oauth_userinfo_success_verified_email():
    """Successful token exchange with verified email returns valid identity dict."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "ya29.test_valid_token",
        "refresh_token": "1//test_refresh",
        "expires_in": 3600,
    }

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "email": "verified_scholar@vit.ac.in",
        "name": "Verified Scholar",
        "verified_email": True,
    }

    with patch("backend.services.oauth.get_settings") as mock_set, \
         patch("httpx.AsyncClient.post", return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", return_value=mock_userinfo_resp):
        mock_set.return_value.GOOGLE_CLIENT_ID = "cid"
        mock_set.return_value.GOOGLE_CLIENT_SECRET = "csec"
        mock_set.return_value.ENVIRONMENT = "production"
        res = await exchange_code_for_tokens("valid_auth_code_from_google")
        assert "error" not in res
        assert res["email"] == "verified_scholar@vit.ac.in"
        assert res["account_email"] == "verified_scholar@vit.ac.in"


@pytest.mark.asyncio
async def test_oauth_userinfo_timeout_fails_closed():
    """Timeout during userinfo retrieval fails closed without generic fallback account."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "ya29.test"}

    with patch("backend.services.oauth.get_settings") as mock_set, \
         patch("httpx.AsyncClient.post", return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", side_effect=Exception("ReadTimeout")):
        mock_set.return_value.GOOGLE_CLIENT_ID = "cid"
        mock_set.return_value.GOOGLE_CLIENT_SECRET = "csec"
        mock_set.return_value.ENVIRONMENT = "production"
        res = await exchange_code_for_tokens("code_123")
        assert "error" in res
        assert res.get("email") is None
        assert "user@gmail.com" not in str(res)
        assert "scholar.authenticated@gmail.com" not in str(res)


@pytest.mark.asyncio
async def test_oauth_userinfo_non_200_fails_closed():
    """Non-200 status from userinfo endpoint fails closed."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "ya29.test"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 401

    with patch("backend.services.oauth.get_settings") as mock_set, \
         patch("httpx.AsyncClient.post", return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", return_value=mock_userinfo_resp):
        mock_set.return_value.GOOGLE_CLIENT_ID = "cid"
        mock_set.return_value.GOOGLE_CLIENT_SECRET = "csec"
        mock_set.return_value.ENVIRONMENT = "production"
        res = await exchange_code_for_tokens("code_123")
        assert "error" in res
        assert res.get("email") is None


@pytest.mark.asyncio
async def test_oauth_userinfo_missing_email_fails_closed():
    """Userinfo omitting email address fails closed."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "ya29.test"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {"name": "No Email User"}

    with patch("backend.services.oauth.get_settings") as mock_set, \
         patch("httpx.AsyncClient.post", return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", return_value=mock_userinfo_resp):
        mock_set.return_value.GOOGLE_CLIENT_ID = "cid"
        mock_set.return_value.GOOGLE_CLIENT_SECRET = "csec"
        mock_set.return_value.ENVIRONMENT = "production"
        res = await exchange_code_for_tokens("code_123")
        assert "error" in res
        assert "valid email address" in res["error"].lower()
        assert res.get("email") is None


@pytest.mark.asyncio
async def test_oauth_userinfo_unverified_email_fails_closed():
    """Userinfo with verified_email=False fails closed."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "ya29.test"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "email": "unverified@example.com",
        "verified_email": False,
    }

    with patch("backend.services.oauth.get_settings") as mock_set, \
         patch("httpx.AsyncClient.post", return_value=mock_token_resp), \
         patch("httpx.AsyncClient.get", return_value=mock_userinfo_resp):
        mock_set.return_value.GOOGLE_CLIENT_ID = "cid"
        mock_set.return_value.GOOGLE_CLIENT_SECRET = "csec"
        mock_set.return_value.ENVIRONMENT = "production"
        res = await exchange_code_for_tokens("code_123")
        assert "error" in res
        assert "not verified" in res["error"].lower()
        assert res.get("email") is None


@pytest.mark.asyncio
async def test_oauth_callback_endpoint_missing_email_issues_no_session():
    """Calendar callback receiving token exchange without email returns 400 and sets no session cookie."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("backend.services.oauth.exchange_code_for_tokens", return_value={"access_token": "tok", "error": "No email"}):
            res = await client.get("/api/calendar/callback?code=some_test_code")
            assert res.status_code == 400
            assert "compass_session" not in res.cookies
            assert "scholar.authenticated@gmail.com" not in res.text


# ===========================================================================
# 4. P2: SAME-IP GUEST SESSION ISOLATION
# ===========================================================================

@pytest.mark.asyncio
async def test_two_guest_sessions_from_same_ip_are_isolated():
    """Two independent guest sessions from the same public IP must remain isolated."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Mint two guest tokens
        gid_a, tok_a = generate_guest_token()
        gid_b, tok_b = generate_guest_token()

        shared_ip_headers_a = {"x-guest-token": tok_a, "x-forwarded-for": "203.0.113.195"}
        shared_ip_headers_b = {"x-guest-token": tok_b, "x-forwarded-for": "203.0.113.195"}

        # Guest A creates a task
        res_a = await client.post(
            "/api/tasks",
            json={"title": "Guest A Secret Task", "domain": "hackathon"},
            headers=shared_ip_headers_a,
        )
        assert res_a.status_code == 200
        task_a_id = res_a.json()["id"]

        # Guest B lists tasks from the same IP -> must NOT see Guest A's task
        res_b = await client.get("/api/tasks", headers=shared_ip_headers_b)
        assert res_b.status_code == 200
        b_tasks = res_b.json()
        b_task_ids = [t["id"] for t in b_tasks]
        assert task_a_id not in b_task_ids


# ===========================================================================
# 5. P2: ROADMAP INTENT POSITIVE AND NEGATIVE TESTS
# ===========================================================================

def test_roadmap_intent_positive_and_negative_matching():
    """Verify prioritization and roadmap phrases trigger agent intent while informational queries do not."""
    # Positive
    assert is_schedule_or_agent_intent("roadmap") is True
    assert is_schedule_or_agent_intent("what should I do today?") is True
    assert is_schedule_or_agent_intent("prioritize my tasks") is True
    assert is_schedule_or_agent_intent("Suggest an optimal step-by-step roadmap for today") is True
    assert is_schedule_or_agent_intent("prioritize my day") is True

    # Negative (Informational questions)
    assert is_schedule_or_agent_intent("What is a roadmap?") is False
    assert is_schedule_or_agent_intent("Explain what a roadmap is") is False
    assert is_schedule_or_agent_intent("Define roadmap") is False
    assert is_schedule_or_agent_intent("What is a product roadmap in software engineering?") is False
    assert is_schedule_or_agent_intent("What does roadmap mean?") is False

    # Positive fallback routing
    skill, args, _ = _fallback_route("what should I do today?")
    assert skill == "agent"
    assert args is not None
    assert args.get("goal") == "what should I do today?"
