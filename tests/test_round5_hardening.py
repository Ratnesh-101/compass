"""
Compass — ROUND 5 Hardening & Verification Tests.

Covers:
1. XFF Edge Signature Verification (Item 2)
2. Strict Pinned Platform Matching (Item 3)
3. Unauthenticated 401 Gate on User Data / Seeding Routes (Item 5)
4. PostgreSQL Session Persistence, Hash, Expiration & Revocation (Item 6)
5. Test-DB Guard positive separation check (Item 7)
6. Agent Audit Log schema, run_id storage & failed-write abort (Item 8)
7. Production Code Mock Cleanup & Calendar Simulation Environment Gates (Item 9)
8. Cross-Identity Negative Tests across all user-data endpoints (Item 10)
"""

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.config import get_settings
from backend.dependencies import Identity, _get_current_identity, verify_token
from backend.memory.db import get_pool
from backend.routers.auth import (
    _SESSIONS,
    _hash_token,
    create_session,
    get_user_from_session,
    is_session_oauth_verified,
    load_sessions_from_db,
)
from backend.services.security import get_client_ip, verify_edge_signature
from backend.services.tavily_authority import classify_domain_authority, AuthorityTier


# ===========================================================================
# 1. XFF Edge Signature Verification (Item 2)
# ===========================================================================

def test_edge_signature_verification():
    """Verify HMAC SHA-256 edge signature verification with client_ip|timestamp|signature format."""
    secret = "test_secret_12345"
    client_ip = "198.51.100.42"
    now_ts = str(int(time.time()))
    payload = f"{client_ip}|{now_ts}"
    valid_hmac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    valid_header = f"{client_ip}|{now_ts}|{valid_hmac}"

    assert verify_edge_signature(valid_header, secret) is True
    # Forged signature
    assert verify_edge_signature(f"{client_ip}|{now_ts}|forged_signature_hex", secret) is False
    # Expired signature (older than max_age_seconds=300)
    old_ts = str(int(time.time()) - 400)
    old_payload = f"{client_ip}|{old_ts}"
    old_hmac = hmac.new(secret.encode(), old_payload.encode(), hashlib.sha256).hexdigest()
    assert verify_edge_signature(f"{client_ip}|{old_ts}|{old_hmac}", secret) is False
    # Malformed header
    assert verify_edge_signature("invalid_no_pipes", secret) is False


def test_forged_xff_direct_call_trusts_only_last_hop():
    """Direct-to-Render callers have 1 hop; forged XFF without edge signature must trust parts[-1]."""
    scope = {
        "type": "http",
        "headers": [
            (b"x-forwarded-for", b"203.0.113.195, 198.51.100.22"),
        ],
        "client": ("10.0.0.1", 12345),
    }
    req = Request(scope)
    # No edge signature -> effective hops = 1 -> parts[-1] is 198.51.100.22
    resolved_ip = get_client_ip(req)
    assert resolved_ip == "198.51.100.22"


def test_xff_via_trusted_vercel_edge_trusts_signed_client_ip():
    """Vercel edge middleware signs client_ip|timestamp|sig; backend extracts signed client_ip."""
    settings = get_settings()
    secret = settings.EDGE_HMAC_SECRET or settings.VERCEL_EDGE_SECRET
    now_ts = str(int(time.time()))
    client_ip = "203.0.113.195"
    payload = f"{client_ip}|{now_ts}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    header_val = f"{client_ip}|{now_ts}|{sig}".encode()

    scope = {
        "type": "http",
        "headers": [
            (b"x-forwarded-for", b"203.0.113.195, 198.51.100.22"),
            (b"x-compass-edge-sig", header_val),
        ],
        "client": ("10.0.0.1", 12345),
    }
    req = Request(scope)
    resolved_ip = get_client_ip(req)
    assert resolved_ip == "203.0.113.195"


def test_proxy_hops_chain_shorter_falls_back_to_client_host():
    """If chain has fewer hops than expected and no valid edge sig, falls back strictly to request.client.host."""
    from backend.config import Settings
    s = Settings(TRUSTED_PROXY_HOPS=2)
    with patch("backend.config.get_settings", return_value=s):
        scope = {
            "type": "http",
            "headers": [
                (b"x-forwarded-for", b"203.0.113.195"),  # only 1 hop in chain, but hops=2
            ],
            "client": ("192.0.2.1", 54321),
        }
        req = Request(scope)
        resolved_ip = get_client_ip(req)
        assert resolved_ip == "192.0.2.1"



# ===========================================================================
# 2. Strict Pinned Platform Matching (Item 3)
# ===========================================================================

def test_strict_pinned_platform_matching():
    """Verify exact pinned event matching and rejection of lookalike subdomains / software paths."""
    prefixes = ["https://nebiusglobalaihackathon.devpost.com"]
    # Official pinned event
    r1 = classify_domain_authority("https://nebiusglobalaihackathon.devpost.com/rules", pinned_event_prefixes=prefixes)
    assert r1["tier"] == AuthorityTier.TIER_1_OFFICIAL.value

    r2 = classify_domain_authority("https://nebiusglobalaihackathon.devpost.com/", pinned_event_prefixes=prefixes)
    assert r2["tier"] == AuthorityTier.TIER_1_OFFICIAL.value

    # Lookalike subdomains stay Tier 2
    r_fake1 = classify_domain_authority("https://nebiusfake.devpost.com/", pinned_event_prefixes=prefixes)
    assert r_fake1["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    r_fake2 = classify_domain_authority("https://bi.devpost.com/", pinned_event_prefixes=prefixes)
    assert r_fake2["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    r_fake3 = classify_domain_authority("https://nebius-ai.devpost.com/", pinned_event_prefixes=prefixes)
    assert r_fake3["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    # User project submission pages (/software/) strictly stay Tier 2
    r_soft = classify_domain_authority("https://nebiusglobalaihackathon.devpost.com/software/my-project", pinned_event_prefixes=prefixes)
    assert r_soft["tier"] == AuthorityTier.TIER_2_TECHNICAL.value


# ===========================================================================
# 3. PostgreSQL Session Persistence & Expiry (Item 6)
# ===========================================================================

async def _safe_get_pool():
    try:
        pool = await get_pool()
        if not pool:
            pytest.skip("PostgreSQL pool unavailable")
        return pool
    except Exception:
        pytest.skip("PostgreSQL pool unavailable")


@pytest.mark.asyncio
async def test_session_persistence_survives_restart_simulation():
    """Verify session survives server restart simulation via PostgreSQL sessions table."""
    pool = await _safe_get_pool()

    user_email = f"session_test_{uuid.uuid4().hex[:6]}@compass.ai"
    token = create_session(user_email, oauth_verified=True)
    token_hash = _hash_token(token)

    # Allow async background task to persist to DB
    await asyncio.sleep(0.1)

    # Verify session row exists in PostgreSQL
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM sessions WHERE token_hash = $1", token_hash)
        assert row is not None
        assert row["user_id"] == user_email
        assert row["oauth_verified"] is True
        assert row["revoked_at"] is None

    # Simulate server restart by clearing in-memory session cache
    _SESSIONS.clear()
    assert token_hash not in _SESSIONS

    # Hydrate active sessions from DB on startup
    loaded_count = await load_sessions_from_db(pool)
    assert loaded_count >= 1

    # Session is restored and valid
    user = get_user_from_session(token)
    assert user == user_email
    assert is_session_oauth_verified(token) is True


@pytest.mark.asyncio
async def test_session_idle_and_absolute_expiration():
    """Verify session rejects expired tokens based on absolute and idle timeouts."""
    token = f"exp_token_{uuid.uuid4().hex}"
    token_hash = _hash_token(token)

    # Test Absolute Expiration
    _SESSIONS[token_hash] = {
        "user_id": "alice@compass.ai",
        "oauth_verified": True,
        "created_at": datetime.now(timezone.utc) - timedelta(days=10),
        "last_accessed_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) - timedelta(days=3),  # expired 3 days ago
        "revoked_at": None,
    }
    assert get_user_from_session(token) is None

    # Test Idle Timeout (inactivity > 24 hours)
    _SESSIONS[token_hash] = {
        "user_id": "alice@compass.ai",
        "oauth_verified": True,
        "created_at": datetime.now(timezone.utc) - timedelta(days=2),
        "last_accessed_at": datetime.now(timezone.utc) - timedelta(hours=25),  # idle > 24h
        "expires_at": datetime.now(timezone.utc) + timedelta(days=5),
        "revoked_at": None,
    }
    assert get_user_from_session(token) is None


@pytest.mark.asyncio
async def test_session_revocation_on_logout():
    """Verify logging out marks session as revoked in DB and memory."""
    pool = await _safe_get_pool()

    user_email = f"logout_test_{uuid.uuid4().hex[:6]}@compass.ai"
    token = create_session(user_email)
    token_hash = _hash_token(token)
    await asyncio.sleep(0.1)

    assert get_user_from_session(token) == user_email

    # Revoke session (simulating auth_logout)
    _SESSIONS[token_hash]["revoked_at"] = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sessions SET revoked_at = now() WHERE token_hash = $1", token_hash)

    assert get_user_from_session(token) is None
    assert is_session_oauth_verified(token) is False


@pytest.mark.asyncio
async def test_session_revocation_propagates_within_ttl():
    """Verify session revocation in PostgreSQL propagates within the <=10s TTL cache."""
    from backend.routers.auth import (
        get_user_from_session_async,
        SESSION_CACHE_TTL,
        _persist_session_db,
        ABSOLUTE_TIMEOUT,
    )
    pool = await _safe_get_pool()

    user_email = f"ttl_revocation_{uuid.uuid4().hex[:6]}@compass.ai"
    token = create_session(user_email)
    token_hash = _hash_token(token)
    expires_at = datetime.now(timezone.utc) + ABSOLUTE_TIMEOUT
    await _persist_session_db(token_hash, user_email, False, expires_at)

    # Fast path: user resolves while cache is fresh
    assert await get_user_from_session_async(token) == user_email

    # Revoke in PostgreSQL directly (as if another worker received POST /api/auth/logout)
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sessions SET revoked_at = now() WHERE token_hash = $1", token_hash)

    # Simulate TTL expiration (advance cached_at past 10.0s TTL)
    assert token_hash in _SESSIONS
    _SESSIONS[token_hash]["cached_at"] = time.time() - (SESSION_CACHE_TTL + 1.0)

    # Next lookup detects TTL expiry, queries Postgres, sees revoked_at, invalidates local cache, returns None
    user_after_ttl = await get_user_from_session_async(token)
    assert user_after_ttl is None
    assert token_hash not in _SESSIONS


# ===========================================================================
# 4. Test-DB Guard Positive Separation (Item 7)
# ===========================================================================

def test_test_db_guard_aborts_when_urls_match():
    """Verify test-db guard aborts execution when TEST_DATABASE_URL matches DATABASE_URL."""
    from tests.conftest import validate_test_db_guard

    matching_url = "postgresql://user:pass@db.example.com:5432/compass_prod"

    # 1. Matching host AND database name -> must abort
    with patch("pytest.exit") as mock_exit:
        validate_test_db_guard(matching_url, matching_url)
        mock_exit.assert_called_once()
        msg, kwargs = mock_exit.call_args[0][0], mock_exit.call_args[1]
        assert "identical host and database" in msg
        assert kwargs.get("returncode") == 1

    # 2. Distinct host and database name -> allowed through
    with patch("pytest.exit") as mock_exit:
        validate_test_db_guard("postgresql://u:p@db.example.com:5432/compass_test", matching_url)
        mock_exit.assert_not_called()

    # 3. Hostname contains configured production marker -> must abort
    with patch("pytest.exit") as mock_exit:
        validate_test_db_guard(
            "postgresql://u:p@production-node.example.com:5432/compass_test",
            matching_url,
            prod_marker="production",
        )
        mock_exit.assert_called_once()
        msg = mock_exit.call_args[0][0]
        assert "production marker" in msg



# ===========================================================================
# 5. Agent Audit Log & Write Failure Abort (Item 8)
# ===========================================================================

@pytest.mark.asyncio
async def test_agent_audit_log_real_db_insert():
    """Verify mutation records run_id and audit trail into agent_audit_log."""
    pool = await _safe_get_pool()

    run_id = f"run_{uuid.uuid4().hex[:10]}"
    from backend.agent_persistence import record_audit_log

    audit_id = await record_audit_log(
        pool=pool,
        run_id=run_id,
        tool="add_task",
        args={"title": "Audit verification task", "domain": "hackathon"},
        affected_table="tasks",
        affected_id=99999,
        previous_state=None,
        new_state={"title": "Audit verification task"},
        approved_by="test_user",
    )
    assert audit_id > 0

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM agent_audit_log WHERE id = $1", audit_id)
        assert row is not None
        assert row["run_id"] == run_id
        assert row["tool"] == "add_task"
        assert row["approved_by"] == "test_user"
        # Cleanup
        await conn.execute("DELETE FROM agent_audit_log WHERE id = $1", audit_id)


@pytest.mark.asyncio
async def test_agent_audit_log_failed_write_aborts_operation():
    """Verify that if recording to agent_audit_log fails, the calling operation raises and aborts."""
    broken_pool = MagicMock()
    broken_conn = AsyncMock()
    broken_conn.fetchrow.side_effect = RuntimeError("Database disk full / connection terminated")
    broken_pool.acquire.return_value.__aenter__.return_value = broken_conn

    from backend.agent_persistence import record_audit_log

    with pytest.raises(RuntimeError, match="Database disk full"):
        await record_audit_log(
            pool=broken_pool,
            run_id="run_abort_test",
            tool="delete_task",
            args={"task_id": 1},
        )


# ===========================================================================
# 6. Production Code Cleanup & Environment Gates (Item 9)
# ===========================================================================

def test_prod_code_no_hasattr_mock_calls():
    """Assert production code does not contain hasattr(..., 'mock_calls')."""
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    for py_file in backend_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "hasattr(client, 'mock_calls')" not in content
        assert 'hasattr(client, "mock_calls")' not in content


@pytest.mark.asyncio
async def test_calendar_simulation_cannot_activate_in_production():
    """Verify is_simulated cannot activate when ENVIRONMENT is unset or 'production'."""
    settings = get_settings()
    with patch.object(settings, "ENVIRONMENT", "production"):
        assert settings.is_development() is False
        assert settings.is_production() is True

        from backend.services.calendar import get_calendar_connection_status, get_calendar_freebusy
        status = await get_calendar_connection_status(pool=None, user_id="prod_user@compass.ai")
        assert status["is_simulated"] is False
        assert status["mode"] == "live"

        now = datetime.now(timezone.utc)
        busy = await get_calendar_freebusy(
            start_dt=now,
            end_dt=now + timedelta(days=2),
            pool=None,
            user_id="prod_user@compass.ai",
            include_simulated=True,
        )
        # In production, simulated blocks are zero
        assert len(busy) == 0


# ===========================================================================
# 7. Cross-Identity Negative Tests for User Data Routes (Item 10)
# ===========================================================================

@pytest.mark.asyncio
async def test_cross_identity_tasks_isolation_negative():
    """User B cannot access or modify User A's tasks."""
    user_a = f"user_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_b_{uuid.uuid4().hex[:6]}"
    ident_b = Identity(id=user_b, is_admin=False, is_guest=False, user_id=user_b)

    pool = await _safe_get_pool()

    async with pool.acquire() as conn:
        task_id = await conn.fetchval(
            "INSERT INTO tasks (title, domain, user_id) VALUES ($1, 'hackathon', $2) RETURNING id",
            f"User A secret task {uuid.uuid4().hex[:6]}",
            user_a,
        )

    try:
        from backend.routers.tasks import update_frontend_task, delete_frontend_task
        from backend.models import UpdateTaskRequest

        req_scope = {"type": "http", "headers": [], "client": ("127.0.0.1", 1234)}
        fastapi_req = Request(req_scope)

        with patch("backend.routers.tasks._get_current_identity", return_value=ident_b), \
             patch("backend.dependencies._get_current_identity", return_value=ident_b):
            # Attempt to update User A's task as User B -> Expect 404 or 403
            with pytest.raises(HTTPException) as exc_info:
                await update_frontend_task(str(task_id), UpdateTaskRequest(title="Hacked title"), fastapi_req)
            assert exc_info.value.status_code in (403, 404)

            # Attempt to delete User A's task as User B -> Expect 404 or 403
            with pytest.raises(HTTPException) as exc_info:
                await delete_frontend_task(str(task_id), fastapi_req)
            assert exc_info.value.status_code in (403, 404)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)


@pytest.mark.asyncio
async def test_cross_identity_agent_undo_isolation_negative():
    """User B cannot undo an action initiated by User A."""
    user_a = f"user_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_b_{uuid.uuid4().hex[:6]}"
    ident_b = Identity(id=user_b, is_admin=False, is_guest=False, user_id=user_b)

    pool = await _safe_get_pool()

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    async with pool.acquire() as conn:
        audit_id = await conn.fetchval(
            """
            INSERT INTO agent_audit_log (run_id, tool, approved_by, affected_table, affected_id, new_state)
            VALUES ($1, 'add_task', $2, 'tasks', 1, '{"title": "test"}'::jsonb)
            RETURNING id
            """,
            run_id,
            user_a,
        )

    try:
        from backend.routers.agent import agent_undo
        from backend.models import AgentUndoRequest
        req_scope = {"type": "http", "headers": [], "client": ("127.0.0.1", 1234)}
        fastapi_req = Request(req_scope)

        with patch("backend.routers.agent._get_current_identity", return_value=ident_b), \
             patch("backend.dependencies._get_current_identity", return_value=ident_b):
            with pytest.raises(HTTPException) as exc_info:
                await agent_undo(AgentUndoRequest(audit_log_id=audit_id), fastapi_req)
            assert exc_info.value.status_code == 403
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_audit_log WHERE id = $1", audit_id)


@pytest.mark.asyncio
async def test_cross_identity_conversation_isolation_negative():
    """User B cannot access or delete User A's conversation."""
    user_a = f"user_a_{uuid.uuid4().hex[:6]}"
    user_b = f"user_b_{uuid.uuid4().hex[:6]}"
    ident_b = Identity(id=user_b, is_admin=False, is_guest=False, user_id=user_b)

    pool = await _safe_get_pool()
    if not pool:
        pytest.skip("PostgreSQL pool required for conversation isolation test")

    conv_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, 'Confidential A')",
            conv_id,
            user_a,
        )

    try:
        from backend.routers.chat import delete_past_conversation, get_messages
        req_scope = {"type": "http", "headers": [], "client": ("127.0.0.1", 1234)}
        fastapi_req = Request(req_scope)

        with patch("backend.routers.chat._get_current_identity", return_value=ident_b), \
             patch("backend.dependencies._get_current_identity", return_value=ident_b):
            with pytest.raises(HTTPException) as exc_info:
                await get_messages(conv_id, fastapi_req)
            assert exc_info.value.status_code == 403

            with pytest.raises(HTTPException) as exc_info:
                await delete_past_conversation(conv_id, fastapi_req)
            assert exc_info.value.status_code == 403
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM conversations WHERE id = $1", conv_id)


@pytest.mark.asyncio
async def test_cross_identity_migration_isolation_negative():
    """Unauthenticated caller or cross-identity caller cannot view or import migration items without valid auth."""
    from backend.routers.migration import list_migration_conversations
    req_scope = {
        "type": "http",
        "headers": [(b"x-guest-token", b"fake_guest_token.unsigned")],
        "client": ("127.0.0.1", 1234),
    }
    fastapi_req = Request(req_scope)

    with patch("backend.routers.migration._get_current_identity", return_value=None):
        # Unauthenticated request raises 401
        with pytest.raises(HTTPException) as exc_info:
            await list_migration_conversations(fastapi_req)
        assert exc_info.value.status_code == 401
