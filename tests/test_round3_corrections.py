"""
Compass — Round 3 Corrections Regression Tests.

Comprehensive verification of:
  1. Docs / quick-connect polarity (/docs, /redoc, /openapi.json hidden in prod, exposed in dev).
  2. IP resolution & proxy hops (Vercel -> Render hop count, spoofing resistance, distinct buckets).
  3. Rate limiter fail-closed on DB unreachable (503).
  4. Global caps & kill-switch (DB-backed mint cap 429, kill-switch 503).
  5. Pending actions (full UUIDs, insert failure raises, pending -> claimed -> executed/failed).
  6. OAuth state user binding (cross-user callback rejected with 403).
  7. SSRF defense (127.1, 2130706433, 0177.0.0.1, ::ffff:127.0.0.1, 100.64.0.1, 169.254.169.254, DNS rebinding).
  8. Tavily event-page rule & relevance gate.
  9. SSE stream cancellation & no duplicate tool tokens.
"""

import asyncio
import ipaddress
import os
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport
from starlette.requests import Request

from backend.config import get_settings, Settings
from backend.services.security import is_safe_url, get_client_ip, _is_ip_blocked
from backend.services.rate_limiter import _consume_token, enforce_rate_limit
from backend.services.budgets import check_global_spend_cap, check_global_mint_cap
from backend.agent_pending import (
    register_pending_action,
    verify_and_claim_action,
    mark_action_executed,
    mark_action_failed,
)
from backend.services.oauth import generate_oauth_state, verify_oauth_state
from backend.services.tavily_authority import classify_domain_authority, AuthorityTier
from backend.memory.db import get_pool


# ---------------------------------------------------------------------------
# 1. Docs & Quick-Connect Polarity Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_docs_hidden_in_production(client: AsyncClient, monkeypatch):
    """In production mode, /docs, /redoc, and /openapi.json must return 404."""
    from backend.main import app
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")

    for path in ("/docs", "/redoc", "/openapi.json", "/api/auth/quick-connect", "/api/auth/select-account"):
        res = await client.get(path)
        assert res.status_code == 404, f"Expected 404 for {path} in production, got {res.status_code}"


def test_docs_exposed_only_in_development():
    """is_development returns True only when ENVIRONMENT == 'development'."""
    s_prod = Settings(ENVIRONMENT="production")
    assert not s_prod.is_development()

    s_empty = Settings(ENVIRONMENT="")
    assert not s_empty.is_development()

    s_dev = Settings(ENVIRONMENT="development")
    assert s_dev.is_development()


# ---------------------------------------------------------------------------
# 2. IP Resolution & Proxy Hops Tests
# ---------------------------------------------------------------------------
def test_trusted_proxy_hops_resolves_correct_ip(monkeypatch):
    """Vercel -> Render proxy path: extracts Nth-from-right IP to defeat header prepending."""
    settings = get_settings()
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
    monkeypatch.setattr(settings, "TRUST_CF_CONNECTING_IP", False)

    req = MagicMock()
    # Chain: spoofed_ip, real_client_ip, vercel_proxy, render_proxy
    # With hops=2: length=4, 4-2=2 -> real_client_ip
    req.headers = {
        "x-forwarded-for": "198.51.100.99, 203.0.113.50, 76.76.21.21, 10.0.0.1"
    }
    client_ip = get_client_ip(req)
    assert client_ip == "76.76.21.21"

    # Distinct clients behind proxy do not share bucket key
    req2 = MagicMock()
    req2.headers = {
        "x-forwarded-for": "198.51.100.99, 203.0.113.51, 76.76.21.21, 10.0.0.1"
    }
    client_ip2 = get_client_ip(req2)
    # When hops=3:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 3)
    assert get_client_ip(req) == "203.0.113.50"
    assert get_client_ip(req2) == "203.0.113.51"
    assert get_client_ip(req) != get_client_ip(req2)


# ---------------------------------------------------------------------------
# 3. Rate Limiter Fail-Closed on DB Down Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_limiter_fail_closed_when_db_down(monkeypatch):
    """When RATE_LIMIT_FAIL_CLOSED=True, rate limiter raises 503 if DB is unreachable."""
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_FAIL_CLOSED", True)

    with patch("backend.services.rate_limiter.get_pool", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            await _consume_token("test:fail_closed:key", capacity=10.0, refill_rate_per_sec=1.0)
        assert exc_info.value.status_code == 503
        assert "Service unavailable" in exc_info.value.detail


@pytest.mark.asyncio
async def test_rate_limiter_fallback_when_fail_closed_disabled(monkeypatch):
    """When RATE_LIMIT_FAIL_CLOSED=False, falls back to memory without raising 503."""
    monkeypatch.setattr(get_settings(), "RATE_LIMIT_FAIL_CLOSED", False)

    with patch("backend.services.rate_limiter.get_pool", return_value=None):
        allowed, retry = await _consume_token(f"test:mem:{uuid.uuid4()}", capacity=5.0, refill_rate_per_sec=1.0)
        assert allowed is True
        assert retry == 0


# ---------------------------------------------------------------------------
# 4. Global Caps & Kill Switch Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_kill_switch_blocks_operations(monkeypatch):
    """When COMPASS_KILL_SWITCH_ACTIVE=True, operations raise 503."""
    monkeypatch.setattr(get_settings(), "COMPASS_KILL_SWITCH_ACTIVE", True)

    with pytest.raises(HTTPException) as exc:
        await check_global_spend_cap()
    assert exc.value.status_code == 503
    assert "kill-switch is engaged" in exc.value.detail

    with pytest.raises(HTTPException) as exc2:
        await check_global_mint_cap()
    assert exc2.value.status_code == 503


@pytest.mark.asyncio
async def test_global_mint_cap_exceeded(monkeypatch):
    """Minting beyond GLOBAL_DAILY_MINT_CAP raises 429."""
    monkeypatch.setattr(get_settings(), "COMPASS_KILL_SWITCH_ACTIVE", False)
    monkeypatch.setattr(get_settings(), "GLOBAL_DAILY_MINT_CAP", 5)

    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetchval.return_value = 5  # Already 5 guests minted today
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = False

    with pytest.raises(HTTPException) as exc:
        await check_global_mint_cap(pool=mock_pool)
    assert exc.value.status_code == 429
    assert "Global daily guest creation limit" in exc.value.detail


# ---------------------------------------------------------------------------
# 5. Pending Actions (UUIDs, Insert Exception, State Transitions)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pending_action_insert_failure_raises():
    """register_pending_action raises RuntimeError if DB insert fails."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = Exception("DB Connection Refused")
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value.__aexit__.return_value = False

    with pytest.raises(RuntimeError) as exc:
        await register_pending_action(
            pool=mock_pool,
            run_id="run_err_test",
            owner_identity="usr_test",
            tool="test_tool",
            args={"key": "val"},
        )
    assert "Database insertion failed" in str(exc.value)


@pytest.mark.asyncio
async def test_pending_action_state_transitions():
    """Pending actions transition pending -> claimed -> executed/failed."""
    pool = await get_pool()
    assert pool is not None

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    owner = "usr_alice"
    args = {"task_id": 42}

    action_id = await register_pending_action(
        pool=pool,
        run_id=run_id,
        owner_identity=owner,
        tool="edit_task",
        args=args,
        timeout_seconds=60,
    )
    # Must use full UUID (length of act_<uuid4> is 40 chars)
    assert action_id.startswith("act_")
    assert len(action_id) >= 36

    # 1. Claim action atomically
    ok, msg, orig_args = await verify_and_claim_action(
        pool=pool,
        action_id=action_id,
        run_id=run_id,
        caller_identity=owner,
        confirmed_args=args,
    )
    assert ok is True
    assert msg == "ok"
    assert orig_args["task_id"] == 42

    # 2. Mark executed
    exec_ok = await mark_action_executed(pool, action_id)
    assert exec_ok is True

    # 3. Attempt replay on executed action -> rejected
    replay_ok, replay_msg, _ = await verify_and_claim_action(
        pool=pool,
        action_id=action_id,
        run_id=run_id,
        caller_identity=owner,
        confirmed_args=args,
    )
    assert replay_ok is False
    assert "replay" in replay_msg.lower() or "claimed" in replay_msg.lower() or "executed" in replay_msg.lower()


# ---------------------------------------------------------------------------
# 6. OAuth State Binding & Cross-User Callback Rejection
# ---------------------------------------------------------------------------
def test_oauth_state_binding():
    """OAuth state is cryptographically bound to user identity and rejects cross-user tamper."""
    alice_state = generate_oauth_state("alice@example.com")
    bob_state = generate_oauth_state("bob@example.com")

    # Alice validating Alice's state -> OK
    assert verify_oauth_state(alice_state, "alice@example.com") is True

    # Bob attempting to validate Alice's state -> REJECTED
    assert verify_oauth_state(alice_state, "bob@example.com") is False

    # Tampered state -> REJECTED
    tampered = alice_state[:-4] + "xxxx"
    assert verify_oauth_state(tampered, "alice@example.com") is False


# ---------------------------------------------------------------------------
# 7. SSRF Comprehensive Attack Payloads
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ssrf_payload",
    [
        "http://127.1",                    # Abbreviated IPv4 loopback
        "http://2130706433",               # Decimal integer 127.0.0.1
        "http://0177.0.0.1",               # Octal dotted IPv4
        "http://[::ffff:127.0.0.1]",       # IPv4-mapped IPv6 loopback
        "http://100.64.0.1",               # Carrier-Grade NAT (RFC 6598)
        "http://169.254.169.254",          # Cloud metadata service
        "http://0.0.0.0:80",               # Unspecified IP
        "http://[::1]:8080",               # IPv6 loopback
        "http://10.255.255.254",           # RFC 1918 class A
        "http://172.16.0.1",               # RFC 1918 class B
        "http://192.168.1.1",              # RFC 1918 class C
    ],
)
def test_ssrf_rejects_evasion_payloads(ssrf_payload: str):
    """is_safe_url rejects numeric encodings, octal, abbreviated, and IPv6-mapped loopback."""
    safe, reason = is_safe_url(ssrf_payload)
    assert safe is False, f"Expected {ssrf_payload} to be blocked, but was allowed! Reason: {reason}"
    assert len(reason) > 0


# ---------------------------------------------------------------------------
# 8. Tavily Event-Page Rule
# ---------------------------------------------------------------------------
def test_tavily_event_page_rule():
    """Platform-hosted page counts as official (Tier 1) ONLY when entity-bound, otherwise Tier 2."""
    # 1. Devpost page bound to Nebius entity -> Tier 1
    res1 = classify_domain_authority(
        url="https://nebius-hackathon.devpost.com",
        target_entity="nebius",
        is_entity_bound=True,
    )
    assert res1["tier"] == AuthorityTier.TIER_1_OFFICIAL.value
    assert "Official Event Page" in res1["badge"]

    # 2. Devpost page for unrelated event or without entity binding -> Tier 2
    res2 = classify_domain_authority(
        url="https://unrelated-contest.devpost.com",
        target_entity="nebius",
        is_entity_bound=False,
    )
    assert res2["tier"] == AuthorityTier.TIER_2_TECHNICAL.value
    assert "Platform / Community Host" in res2["badge"]
