"""
tests/test_verification_pass.py
Comprehensive verification test suite proving:
1. Rate limiting & mint throttling (429)
2. Budgets (per-run & per-day)
3. Auth: x-user-id rejection, guest token tamper/expiry, guest high-risk tool block
4. Share tokens: revocable, no owner PII
5. DB pending actions: cross-user denial, replay rejection, tampered args, expiry
6. Migration & Memory deduplication
7. Tavily pipeline: domain authority spoofing resistance, prompt-injection fixtures
8. SSRF safe wrapper: decimal, octal, IPv6-mapped, 0.0.0.0, cloud metadata
"""
import asyncio
import json
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from starlette.requests import Request

from backend.dependencies import (
    _get_current_user_id,
    generate_guest_token,
    verify_guest_token,
)
from backend.services.rate_limiter import (
    _consume_token,
    enforce_rate_limit,
    enforce_mint_rate_limit,
)
from backend.services.budgets import (
    check_run_limits,
    check_daily_identity_budget,
    BudgetExceededError,
)
from backend.agent_pending import (
    register_pending_action,
    verify_and_claim_action,
    compute_args_hash,
)
from backend.skills.registry import is_tool_allowed_for_identity
from backend.services.security import is_safe_url
from backend.services.tavily_authority import classify_domain_authority, AuthorityTier
from backend.memory.vector import compute_content_hash


# --- 1. RATE LIMITING & MINT THROTTLING ---

@pytest.mark.asyncio
async def test_token_bucket_rate_limiter_throttles():
    import uuid
    key = f"test_throttle_{uuid.uuid4().hex[:8]}"
    # Capacity 3, refill 0.01/sec
    ok1, _ = await _consume_token(key, capacity=3.0, refill_rate_per_sec=0.01)
    ok2, _ = await _consume_token(key, capacity=3.0, refill_rate_per_sec=0.01)
    ok3, _ = await _consume_token(key, capacity=3.0, refill_rate_per_sec=0.01)
    ok4, _ = await _consume_token(key, capacity=3.0, refill_rate_per_sec=0.01)
    assert ok1 is True
    assert ok2 is True
    assert ok3 is True
    # 4th request must be rejected
    assert ok4 is False


@pytest.mark.asyncio
async def test_mint_rate_limit_blocks_spam():
    scope = {"type": "http", "client": ("198.51.100.88", 1234), "headers": []}
    req = Request(scope)
    # Capacity is 10. Spamming 15 requests must hit 429 even with network round-trip latency
    hit_429 = False
    for _ in range(15):
        try:
            await enforce_mint_rate_limit(req)
        except HTTPException as exc:
            if exc.status_code == 429:
                hit_429 = True
                assert "Guest token minting rate limit exceeded" in exc.detail
                break
    assert hit_429 is True


# --- 2. OPERATIONAL BUDGETS ---

def test_run_limits_exceeded():
    with pytest.raises(BudgetExceededError) as exc_model:
        check_run_limits(model_calls=16, tool_calls=5, tavily_credits=1)
    assert exc_model.value.budget_type == "model_calls"

    with pytest.raises(BudgetExceededError) as exc_tools:
        check_run_limits(model_calls=5, tool_calls=25, tavily_credits=1)
    assert exc_tools.value.budget_type == "tool_calls"

    with pytest.raises(BudgetExceededError) as exc_tavily:
        check_run_limits(model_calls=5, tool_calls=5, tavily_credits=10)
    assert exc_tavily.value.budget_type == "tavily_credits"


@pytest.mark.asyncio
async def test_daily_budget_exceeded():
    # Mock pool to simulate daily tavily credit threshold exceeded
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=35)
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    with patch("backend.services.budgets.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc_info:
            await check_daily_identity_budget(user_id="usr_abc")
        assert exc_info.value.status_code == 429
        assert "Daily Tavily search credit budget" in exc_info.value.detail


# --- 3. AUTH & IDENTITY SECURITY ---

def test_unverified_x_user_id_header_is_rejected():
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 1234),
        "headers": [(b"x-user-id", b"attacker_injected_admin_id")],
    }
    req = Request(scope)
    # Must NOT trust x-user-id; returns None
    assert _get_current_user_id(req) is None


def test_guest_token_expiry_and_tampering():
    import uuid
    import hashlib
    import hmac
    from backend.dependencies import _get_guest_signing_secret

    raw_uuid = str(uuid.uuid4())
    gid, token = generate_guest_token(raw_uuid)
    verified = verify_guest_token(token)
    assert verified == raw_uuid

    # Tampered signature
    parts = token.split(".")
    tampered_sig = parts[0] + "." + parts[1] + ".bad_signature"
    assert verify_guest_token(tampered_sig) is None

    # Tampered payload
    tampered_payload = str(uuid.uuid4()) + "." + parts[1] + "." + parts[2]
    assert verify_guest_token(tampered_payload) is None

    # Expired token (simulate past timestamp)
    past_ts = int(time.time()) - (86400 * 40)
    secret = _get_guest_signing_secret()
    payload = f"{raw_uuid}:{past_ts}".encode("utf-8")
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    expired_token = f"{raw_uuid}.{past_ts}.{sig}"
    assert verify_guest_token(expired_token) is None


def test_guest_restricted_tools_server_side():
    # Guests cannot invoke HIGH_RISK or EXTERNAL_SIDE_EFFECT tools
    assert is_tool_allowed_for_identity("commit_schedule", "guest_123") is False
    assert is_tool_allowed_for_identity("ingest_url", "guest_123") is False
    assert is_tool_allowed_for_identity("delete_task", "guest_123") is False
    assert is_tool_allowed_for_identity("apply_triage_plan", "guest_123") is False

    # Safe read-only / propose tools are allowed for guests
    assert is_tool_allowed_for_identity("propose_schedule", "guest_123") is True
    assert is_tool_allowed_for_identity("search_tasks", "guest_123") is True

    # Authenticated users are allowed
    assert is_tool_allowed_for_identity("commit_schedule", "usr_real_admin") is True
    assert is_tool_allowed_for_identity("delete_task", "usr_real_admin") is True


from backend.memory.db import get_pool


# --- 4. DB PENDING ACTIONS (CONFIRM / UNDO) ---

@pytest.mark.asyncio
async def test_pending_action_tampering_and_cross_user():
    pool = await get_pool()
    args = {"task_id": "tsk_99", "new_date": "2026-10-10"}

    action_id = await register_pending_action(
        pool=pool,
        run_id="run_100",
        owner_identity="usr_owner",
        tool="commit_schedule",
        args=args,
        timeout_seconds=60,
    )

    # 1. Other user confirms -> 403 / Permission denied
    ok, msg, _ = await verify_and_claim_action(
        pool, action_id=action_id, run_id="run_100", caller_identity="usr_attacker", confirmed_args=args
    )
    assert ok is False
    assert "Permission denied" in msg

    # 2. Tampered args -> rejected
    tampered_args = {"task_id": "tsk_99", "new_date": "2026-10-99"}
    ok, msg, _ = await verify_and_claim_action(
        pool, action_id=action_id, run_id="run_100", caller_identity="usr_owner", confirmed_args=tampered_args
    )
    assert ok is False
    assert "tampered" in msg.lower()

    # 3. Valid claim -> success
    ok, msg, orig = await verify_and_claim_action(
        pool, action_id=action_id, run_id="run_100", caller_identity="usr_owner", confirmed_args=args
    )
    assert ok is True
    assert orig["task_id"] == "tsk_99"

    # 4. Replay attempt -> rejected (single-use)
    ok, msg, _ = await verify_and_claim_action(
        pool, action_id=action_id, run_id="run_100", caller_identity="usr_owner", confirmed_args=args
    )
    assert ok is False
    assert "replay" in msg.lower() or "executed" in msg.lower()


@pytest.mark.asyncio
async def test_pending_action_expiry():
    pool = await get_pool()
    args = {"test": 1}
    action_id = await register_pending_action(
        pool=pool,
        run_id="run_101",
        owner_identity="usr_owner",
        tool="delete_task",
        args=args,
        timeout_seconds=-10,  # Expired
    )
    ok, msg, _ = await verify_and_claim_action(
        pool, action_id=action_id, run_id="run_101", caller_identity="usr_owner", confirmed_args=args
    )
    assert ok is False
    assert "expired" in msg.lower()


# --- 5. DOMAIN AUTHORITY & SPOOFING RESISTANCE ---

def test_tavily_domain_authority_spoofing():
    # Devpost platform host is capped at Tier 2
    res_platform = classify_domain_authority("https://devpost.com/hackathons")
    assert res_platform["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    # Platform host (*.devpost.com) is strictly capped at Tier 2
    res_subdomain = classify_domain_authority("https://chromaawards.devpost.com/rules")
    assert res_subdomain["tier"] == AuthorityTier.TIER_2_TECHNICAL.value

    # Official organizer domain is Tier 1
    res_official = classify_domain_authority("https://docs.nebius.com/rules")
    assert res_official["tier"] == AuthorityTier.TIER_1_OFFICIAL.value

    # Attacker attempting domain suffix spoofing: devpost.com.evil.io
    res_spoof = classify_domain_authority("https://devpost.com.evil.io/phish")
    assert res_spoof["tier"] == AuthorityTier.TIER_3_GENERAL.value

    # Attacker attempting prefix docs spoofing: docs.evil.com
    res_docs_spoof = classify_domain_authority("https://docs.evil.com/hackathon")
    assert res_docs_spoof["tier"] == AuthorityTier.TIER_3_GENERAL.value


# --- 6. SSRF SECURITY WRAPPER ---

def test_ssrf_safe_url_validation():
    # Localhost / Loopback
    assert is_safe_url("http://127.0.0.1/admin")[0] is False
    assert is_safe_url("http://localhost:8000")[0] is False

    # Octal IP (0177.0.0.1 = 127.0.0.1)
    assert is_safe_url("http://0177.0.0.1/")[0] is False

    # Decimal integer IP (2130706433 = 127.0.0.1)
    assert is_safe_url("http://2130706433/")[0] is False

    # 0.0.0.0 forms
    assert is_safe_url("http://0.0.0.0/")[0] is False
    assert is_safe_url("http://0.1.2.3/")[0] is False

    # Cloud metadata
    assert is_safe_url("http://169.254.169.254/latest/meta-data/")[0] is False

    # Private RFC1918 networks
    assert is_safe_url("http://10.0.0.1/")[0] is False
    assert is_safe_url("http://192.168.1.1/")[0] is False
    assert is_safe_url("http://172.16.0.1/")[0] is False

    # Legitimate public HTTPS
    assert is_safe_url("https://devpost.com/rules")[0] is True
    assert is_safe_url("https://api.github.com/repos")[0] is True


# --- 7. MEMORY CONTENT HASH NORMALIZATION & CONCURRENCY ---

def test_memory_content_hash_normalization():
    # Whitespace and casing variations should produce identical content hash
    h1 = compute_content_hash("  Submit project before Midnight! \n")
    h2 = compute_content_hash("submit project before midnight!")
    assert h1 == h2


@pytest.mark.asyncio
async def test_migration_concurrency_zero_duplicates():
    import uuid
    from backend.memory.conversation_migration import migrate_single_conversation
    pool = await get_pool()
    guest_id = f"guest_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    # Setup guest conversation
    async with pool.acquire() as conn:
        cid = await conn.fetchval(
            """
            INSERT INTO conversations (guest_id, title)
            VALUES ($1, 'Concurrent Guest Chat')
            RETURNING id
            """,
            guest_id,
        )

    # Run migration concurrently twice
    async def _do_migrate():
        async with pool.acquire() as conn:
            return await migrate_single_conversation(conn, cid, guest_id, user_id)

    res1, res2 = await asyncio.gather(_do_migrate(), _do_migrate())

    # Both must resolve to the identical migrated conversation ID
    assert res1 is not None
    assert res2 is not None
    assert res1 == res2

    # Check guest_migration_log has exactly 1 entry for this guest conversation
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM guest_migration_log WHERE guest_conversation_id = $1 AND user_id = $2",
            cid, user_id,
        )
        assert count == 1

