"""
Compass — Distributed Shared Rate Limiter.

Implements token bucket algorithm backed by PostgreSQL (rate_limit_buckets table)
with automatic fallback to in-memory state when DB is unreachable.
Supports per-IP, per-user, and per-guest limits across multiple workers.
"""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque
from typing import Optional, Tuple

from fastapi import HTTPException, Request

from backend.memory.db import get_pool
from backend.services.security import get_client_ip

logger = logging.getLogger("compass.rate_limiter")

# In-memory fallback buckets if PostgreSQL is offline or during testing
_MEM_BUCKETS: dict[str, dict] = {}


async def _consume_token(
    key: str,
    capacity: float,
    refill_rate_per_sec: float,
    fail_closed: Optional[bool] = None,
) -> Tuple[bool, int]:
    """Atomically consume 1 token for a given key.
    
    Returns:
        (allowed, retry_after_seconds)
    """
    from backend.config import get_settings
    settings = get_settings()
    is_fail_closed = fail_closed if fail_closed is not None else getattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)
    if getattr(settings, "ENVIRONMENT", "").lower() == "test":
        is_fail_closed = False

    try:
        pool = await get_pool()
        if not pool and is_fail_closed:
            raise HTTPException(
                status_code=503,
                detail="Service unavailable: rate limiter database connection is unavailable.",
            )
        if pool:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("SET LOCAL lock_timeout = '2000ms';")
                    row = await conn.fetchrow(
                        """
                        SELECT tokens, EXTRACT(EPOCH FROM (now() - last_updated)) AS elapsed
                        FROM rate_limit_buckets
                        WHERE key = $1
                        FOR UPDATE
                        """,
                        key,
                    )
                    now_tokens = capacity
                    if row is not None:
                        elapsed = float(row["elapsed"] or 0.0)
                        prev_tokens = float(row["tokens"])
                        now_tokens = min(capacity, prev_tokens + (elapsed * refill_rate_per_sec))

                    if now_tokens >= 1.0:
                        new_tokens = now_tokens - 1.0
                        await conn.execute(
                            """
                            INSERT INTO rate_limit_buckets (key, tokens, last_updated)
                            VALUES ($1, $2, now())
                            ON CONFLICT (key) DO UPDATE
                            SET tokens = EXCLUDED.tokens, last_updated = EXCLUDED.last_updated
                            """,
                            key,
                            new_tokens,
                        )
                        return True, 0
                    else:
                        needed = 1.0 - now_tokens
                        retry_after = max(1, int(needed / max(0.0001, refill_rate_per_sec)) + 1)
                        return False, retry_after
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"DB rate limiter failure for key {key}: {e}")
        if is_fail_closed:
            raise HTTPException(
                status_code=503,
                detail="Service unavailable: rate limiter database is unreachable.",
            ) from e

    # Fallback: In-memory token bucket
    now = time.monotonic()
    bucket = _MEM_BUCKETS.get(key)
    if not bucket:
        bucket = {"tokens": capacity - 1.0, "last_updated": now}
        _MEM_BUCKETS[key] = bucket
        return True, 0

    elapsed = now - bucket["last_updated"]
    tokens = min(capacity, bucket["tokens"] + (elapsed * refill_rate_per_sec))

    if tokens >= 1.0:
        bucket["tokens"] = tokens - 1.0
        bucket["last_updated"] = now
        return True, 0
    else:
        bucket["tokens"] = tokens
        bucket["last_updated"] = now
        needed = 1.0 - tokens
        retry_after = max(1, int(needed / max(0.0001, refill_rate_per_sec)) + 1)
        return False, retry_after


async def enforce_rate_limit(
    request: Request,
    action: str = "chat",
    ip_capacity: float = 30.0,
    ip_refill_per_sec: float = 0.5,       # 30/minute
    identity_capacity: float = 30.0,
    identity_refill_per_sec: float = 0.5, # 30/minute
) -> None:
    """Enforce shared multi-tier rate limits: per-IP AND per-Identity (user or guest)."""
    from backend.dependencies import _get_current_identity

    client_ip = get_client_ip(request)
    ip_key = f"ip:{client_ip}:{action}"

    allowed, retry_after = await _consume_token(ip_key, ip_capacity, ip_refill_per_sec)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for IP. Maximum {int(ip_capacity)} requests per minute.",
            headers={"Retry-After": str(retry_after)},
        )

    # Check identity if authenticated or guest
    ident = _get_current_identity(request)
    identity_key = None
    if ident:
        if ident.is_guest and ident.guest_id:
            identity_key = f"guest:{ident.guest_id}:{action}"
        elif ident.user_id:
            identity_key = f"user:{ident.user_id}:{action}"

    if identity_key:
        id_allowed, id_retry = await _consume_token(
            identity_key, identity_capacity, identity_refill_per_sec
        )
        if not id_allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for identity. Maximum {int(identity_capacity)} requests per minute.",
                headers={"Retry-After": str(id_retry)},
            )


async def enforce_mint_rate_limit(request: Request) -> None:
    """Rate limiter for guest session minting: configurable per-IP budget per hour.
    
    Prevents mass guest creation attacks while providing an admin override and clear 429 detail.
    """
    from backend.config import get_settings
    settings = get_settings()

    # 1. Admin override check via Authorization Bearer token
    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        bearer_token = auth_hdr.split(" ", 1)[1].strip()
        if settings.AUTH_TOKEN and hmac.compare_digest(bearer_token, settings.AUTH_TOKEN):
            return

    try:
        from backend.dependencies import _get_current_identity
        ident = _get_current_identity(request)
        if ident and ident.is_admin:
            return
    except Exception:
        pass

    # 2. Configurable per-IP hourly capacity
    hourly_limit = int(getattr(settings, "GUEST_MINT_HOURLY_IP_LIMIT", 5))
    capacity = float(hourly_limit)
    refill_rate = capacity / 3600.0

    client_ip = get_client_ip(request)
    mint_key = f"mint:ip:{client_ip}"
    allowed, retry_after = await _consume_token(mint_key, capacity=capacity, refill_rate_per_sec=refill_rate)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Guest token minting rate limit exceeded: session creation limit reached for this IP (max {hourly_limit} per hour). Please try again later or log in.",
            headers={"Retry-After": str(retry_after)},
        )


async def cleanup_stale_rate_limit_buckets(older_than_hours: int = 24) -> int:
    """Purge expired rate limit buckets to prevent table bloat."""
    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                res = await conn.execute(
                    "DELETE FROM rate_limit_buckets WHERE last_updated < now() - ($1 || ' hours')::interval",
                    str(older_than_hours),
                )
                return int(res.split()[-1]) if res and "DELETE" in res else 0
    except Exception as e:
        logger.warning("Failed to clean up stale rate limit buckets: %s", e)
    return 0
