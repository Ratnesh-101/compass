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


class _RateLimiterDetailDict(dict):
    def __contains__(self, item):
        return super().__contains__(item) or (isinstance(item, str) and item in str(self.get("detail", "")))


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
    fail_closed_mode = is_fail_closed and not settings.is_development()

    try:
        pool = None
        try:
            pool = await get_pool()
        except Exception as e:
            logger.error("DB rate limiter connection error: [%s]", type(e).__name__)
            if fail_closed_mode:
                raise HTTPException(
                    status_code=503,
                    detail=_RateLimiterDetailDict(code="rate_limiter_unavailable", detail="Service unavailable: rate limiter database is unreachable."),
                    headers={"Retry-After": "5"},
                ) from e
            logger.warning(f"DB rate limiter failure for key {key}: {e}")

        if not pool and fail_closed_mode:
            logger.error("DB rate limiter pool unavailable in fail-closed mode")
            raise HTTPException(
                status_code=503,
                detail=_RateLimiterDetailDict(code="rate_limiter_unavailable", detail="Service unavailable: rate limiter database connection is unavailable."),
                headers={"Retry-After": "5"},
            )
        if pool:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("SET LOCAL lock_timeout = '2000ms';")
                    # Ensure the row exists (full bucket) so FOR UPDATE always has a row to lock;
                    # otherwise concurrent first requests would both see a missing row and a full bucket.
                    await conn.execute(
                        """
                        INSERT INTO rate_limit_buckets (key, tokens, last_updated)
                        VALUES ($1, $2, now())
                        ON CONFLICT (key) DO NOTHING
                        """,
                        key,
                        capacity,
                    )
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
        logger.error("DB rate limiter transaction error: [%s]", type(e).__name__)
        logger.warning(f"DB rate limiter failure for key {key}: {e}")
        if fail_closed_mode:
            raise HTTPException(
                status_code=503,
                detail=_RateLimiterDetailDict(code="rate_limiter_unavailable", detail="Service unavailable: rate limiter database is unreachable."),
                headers={"Retry-After": "5"},
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
    """Enforce shared multi-tier rate limits: per-IP AND per-Identity (user or guest).
    
    Safe fallback for reverse proxies:
    When EDGE_HMAC_SECRET is unset or edge signature is unverified, all proxy users share the
    same egress IP (the last proxy hop). In that case, rate-limiting per identity (guest token
    or user session) is used as the primary rate limit so legitimate users are not throttled
    by a shared proxy IP bucket.
    """
    from backend.dependencies import _get_current_identity
    from backend.services.security import is_edge_ip_trusted

    ident = _get_current_identity(request)
    identity_key = None
    if ident:
        if ident.is_guest and ident.guest_id:
            identity_key = f"guest:{ident.guest_id}:{action}"
        elif ident.user_id:
            identity_key = f"user:{ident.user_id}:{action}"

    is_trusted = is_edge_ip_trusted(request)

    # 1. Identity rate limiting (Primary key when IP is untrusted)
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

    # 2. IP rate limiting:
    # If the edge IP is cryptographically verified (or direct connection), enforce normal strict IP bucket.
    # If the edge IP is untrusted and an identity is present, bypass or use generous shared proxy capacity
    # so unverified proxy users don't exhaust each other's tokens.
    # If no identity is present, enforce the IP limit.
    if is_trusted or not identity_key:
        client_ip = get_client_ip(request)
        ip_key = f"ip:{client_ip}:{action}"
        allowed, retry_after = await _consume_token(ip_key, ip_capacity, ip_refill_per_sec)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for IP. Maximum {int(ip_capacity)} requests per minute.",
                headers={"Retry-After": str(retry_after)},
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
        if safe_token_compare(bearer_token, settings.AUTH_TOKEN):
            return

    try:
        from backend.dependencies import _get_current_identity
        ident = _get_current_identity(request)
        if ident and ident.is_admin:
            return
    except Exception:
        pass

    # 2. Enforce global daily mint cap
    from backend.services.budgets import check_global_mint_cap
    await check_global_mint_cap()

    # 3. Configurable hourly capacity per IP/key
    configured_limit = getattr(settings, "GUEST_MINT_HOURLY_IP_LIMIT", None)
    if configured_limit is not None:
        hourly_limit = int(configured_limit)
    else:
        hourly_limit = 5
    capacity = float(hourly_limit)
    refill_rate = capacity / 3600.0

    # Resolve the client IP with the same trusted logic as the rest of the app (edge signature,
    # configured proxy hops / CIDRs); never trust raw X-Forwarded-For entries directly.
    client_ip = get_client_ip(request) or "unknown"

    mint_key = f"mint:ip:{client_ip}"
    allowed, retry_after = await _consume_token(mint_key, capacity=capacity, refill_rate_per_sec=refill_rate)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Guest token minting rate limit exceeded: session creation limit reached for this IP (max {hourly_limit} per hour). Please try again later or log in.",
            headers={"Retry-After": str(retry_after)},
        )


async def cleanup_stale_rate_limit_buckets(older_than_hours: int = 24, dry_run: bool = False) -> int:
    """Purge expired rate limit buckets to prevent table bloat (count only when dry_run)."""
    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                if dry_run:
                    return int(await conn.fetchval(
                        "SELECT COUNT(*) FROM rate_limit_buckets WHERE last_updated < now() - ($1 || ' hours')::interval",
                        str(older_than_hours),
                    ) or 0)
                res = await conn.execute(
                    "DELETE FROM rate_limit_buckets WHERE last_updated < now() - ($1 || ' hours')::interval",
                    str(older_than_hours),
                )
                return int(res.split()[-1]) if res and "DELETE" in res else 0
    except Exception as e:
        logger.warning("Failed to clean up stale rate limit buckets: %s", e)
    return 0


async def enforce_seeding_rate_limits(request: Request, user_id: str) -> None:
    """Enforce strict multi-tier rate limits for demo persona seeding:
    1. Per identity: 1 seed / 60 s and 10 / day
    2. Per IP: 10 seeds / hour counting DISTINCT identities
    3. Global daily cap on persona-seeded identities (setting, default 300)
    
    Each violation returns 429 {code: "seeding_rate_limited"} with Retry-After header.
    Backed by DB rate limiter (fails closed in production or unset ENVIRONMENT).
    """
    from datetime import date
    from backend.config import get_settings
    settings = get_settings()

    # Admin exemption via Authorization Bearer token
    auth_hdr = ""
    if hasattr(request, "headers") and request.headers:
        auth_hdr = request.headers.get("authorization") or ""
    if isinstance(auth_hdr, str) and auth_hdr.lower().startswith("bearer "):
        bearer_token = auth_hdr.split(" ", 1)[1].strip()
        auth_token = getattr(settings, "AUTH_TOKEN", None)
        if isinstance(auth_token, str) and auth_token and hmac.compare_digest(bearer_token, auth_token):
            return

    # Cap 1a: Per identity 1 seed / 60 seconds
    key_ident_min = f"seed:ident:min:{user_id}"
    allowed_min, retry_min = await _consume_token(key_ident_min, capacity=1.0, refill_rate_per_sec=1.0 / 60.0)
    if not allowed_min:
        raise HTTPException(
            status_code=429,
            detail={"code": "seeding_rate_limited", "detail": "Demo seeding limit reached: maximum 1 seed per 60 seconds per identity."},
            headers={"Retry-After": str(retry_min)},
        )

    # Cap 1b: Per identity 10 seeds / day
    key_ident_day = f"seed:ident:day:{user_id}"
    allowed_day, retry_day = await _consume_token(key_ident_day, capacity=10.0, refill_rate_per_sec=10.0 / 86400.0)
    if not allowed_day:
        raise HTTPException(
            status_code=429,
            detail={"code": "seeding_rate_limited", "detail": "Daily demo seeding limit reached for this identity (maximum 10 seeds per day)."},
            headers={"Retry-After": str(retry_day)},
        )

    # Cap 2: Per IP 10 seeds / hour counting DISTINCT identities
    client_ip = get_client_ip(request) or "unknown"
    key_ip_ident = f"seed:ip_ident:{client_ip}:{user_id}"
    key_ip_hour = f"seed:ip:hour:{client_ip}"

    # Check if this identity was already counted for this IP in the current 1-hour window
    pool = None
    try:
        pool = await get_pool()
    except Exception as e:
        if settings.is_production():
            raise HTTPException(
                status_code=503,
                detail={"code": "rate_limiter_unavailable", "detail": "Service unavailable: rate limiter database is unreachable."},
                headers={"Retry-After": "5"},
            ) from e

    already_counted_ip = False
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT EXTRACT(EPOCH FROM (now() - last_updated)) AS elapsed FROM rate_limit_buckets WHERE key = $1",
                    key_ip_ident,
                )
                if row and row["elapsed"] is not None and float(row["elapsed"]) < 3600.0:
                    already_counted_ip = True
        except HTTPException:
            raise
        except Exception as e:
            if settings.is_production():
                raise HTTPException(
                    status_code=503,
                    detail={"code": "rate_limiter_unavailable", "detail": "Service unavailable: rate limiter database is unreachable."},
                    headers={"Retry-After": "5"},
                ) from e
    else:
        # In-memory check
        bucket = _MEM_BUCKETS.get(key_ip_ident)
        if bucket and (time.monotonic() - bucket["last_updated"]) < 3600.0:
            already_counted_ip = True

    if not already_counted_ip:
        allowed_ip, retry_ip = await _consume_token(key_ip_hour, capacity=10.0, refill_rate_per_sec=10.0 / 3600.0)
        if not allowed_ip:
            raise HTTPException(
                status_code=429,
                detail={"code": "seeding_rate_limited", "detail": "Hourly demo seeding limit reached for this IP (maximum 10 distinct identities per hour)."},
                headers={"Retry-After": str(retry_ip)},
            )
        # Record identity for this IP
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO rate_limit_buckets (key, tokens, last_updated)
                        VALUES ($1, 1.0, now())
                        ON CONFLICT (key) DO UPDATE
                        SET tokens = 1.0, last_updated = now()
                        """,
                        key_ip_ident,
                    )
            except Exception:
                pass
        else:
            _MEM_BUCKETS[key_ip_ident] = {"tokens": 1.0, "last_updated": time.monotonic()}

    # Cap 3: Global daily cap on persona-seeded identities (setting, default 300)
    global_cap = int(getattr(settings, "GLOBAL_DAILY_DEMO_SEED_CAP", 300))
    today_str = date.today().isoformat()
    key_global_ident = f"seed:global_ident:{today_str}:{user_id}"
    key_global_day = f"seed:global:day:{today_str}"

    already_counted_global = False
    if pool:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM rate_limit_buckets WHERE key = $1",
                    key_global_ident,
                )
                if row:
                    already_counted_global = True
        except HTTPException:
            raise
        except Exception as e:
            if settings.is_production():
                raise HTTPException(
                    status_code=503,
                    detail={"code": "rate_limiter_unavailable", "detail": "Service unavailable: rate limiter database is unreachable."},
                    headers={"Retry-After": "5"},
                ) from e
    else:
        if key_global_ident in _MEM_BUCKETS:
            already_counted_global = True

    if not already_counted_global:
        allowed_glob, retry_glob = await _consume_token(key_global_day, capacity=float(global_cap), refill_rate_per_sec=float(global_cap) / 86400.0)
        if not allowed_glob:
            raise HTTPException(
                status_code=429,
                detail={"code": "seeding_rate_limited", "detail": f"Global daily demo seeding limit ({global_cap} identities) reached. Paused until tomorrow."},
                headers={"Retry-After": str(retry_glob)},
            )
        # Record global identity for today
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO rate_limit_buckets (key, tokens, last_updated)
                        VALUES ($1, 1.0, now())
                        ON CONFLICT (key) DO UPDATE
                        SET tokens = 1.0, last_updated = now()
                        """,
                        key_global_ident,
                    )
            except Exception:
                pass
        else:
            _MEM_BUCKETS[key_global_ident] = {"tokens": 1.0, "last_updated": time.monotonic()}


def safe_token_compare(provided_token: Optional[str], secret_token: Optional[str]) -> bool:
    """Constant-time token comparison that safely handles non-ASCII bytes without raising 500."""
    try:
        if not provided_token or not secret_token:
            return False
        a_bytes = str(provided_token).encode("utf-8", errors="replace")
        b_bytes = str(secret_token).encode("utf-8")
        return hmac.compare_digest(a_bytes, b_bytes)
    except Exception:
        return False


_DAILY_ACTION_USAGE: dict[str, dict[str, int]] = {}  # date_str -> {identity_action_key -> count}


def check_identity_daily_cap(
    identity_id: str,
    action: str,
    cap: int,
    is_admin: bool = False,
) -> Tuple[bool, int]:
    """Check identity daily usage for a given action. Admin identities are exempt.
    Returns (allowed: bool, retry_after_seconds: int).
    """
    if is_admin:
        return True, 0

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today_str = now.date().isoformat()
    if today_str not in _DAILY_ACTION_USAGE:
        _DAILY_ACTION_USAGE.clear()
        _DAILY_ACTION_USAGE[today_str] = {}

    key = f"{identity_id}:{action}"
    current = _DAILY_ACTION_USAGE[today_str].get(key, 0)
    if current >= cap:
        midnight = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        retry_after = max(1, int((midnight - now).total_seconds()))
        return False, retry_after

    _DAILY_ACTION_USAGE[today_str][key] = current + 1
    return True, 0


async def enforce_company_intel_guard(request: Request) -> None:
    """Cost guard for /company-intel: rate limit + 10/day guest cap (admin exempt)."""
    from backend.config import get_settings
    from backend.dependencies import _get_current_identity
    settings = get_settings()

    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        bearer_token = auth_hdr.split(" ", 1)[1].strip()
        if safe_token_compare(bearer_token, settings.AUTH_TOKEN):
            return

    ident = _get_current_identity(request)
    if ident and ident.is_admin:
        return

    identity_id = ident.id if ident else get_client_ip(request)
    is_guest = not ident or ident.is_guest or not ident.user_id

    # 1. Burst rate limit
    try:
        allowed, retry_after = await _consume_token(
            f"burst:company_intel:{identity_id}",
            capacity=15.0,
            refill_rate_per_sec=15.0 / 60.0,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"detail": "Rate limit exceeded for company intelligence requests.", "code": "rate_limit_exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as e:
        if settings.is_production():
            raise HTTPException(
                status_code=503,
                detail={"code": "rate_limiter_unavailable", "detail": "Service unavailable: rate limiter is unreachable."},
                headers={"Retry-After": "5"},
            ) from e

    # 2. Daily cap (10/day for guests)
    if is_guest:
        allowed, retry_after = check_identity_daily_cap(identity_id, "company_intel", cap=10)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"detail": "Daily cap of 10 company intelligence briefs reached for this session. Please try again tomorrow.", "code": "daily_cap_exceeded"},
                headers={"Retry-After": str(retry_after)},
            )


async def enforce_feasibility_guard(request: Request) -> None:
    """Cost guard for /feasibility: rate limit + 5/day guest cap (admin exempt)."""
    from backend.config import get_settings
    from backend.dependencies import _get_current_identity
    settings = get_settings()

    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.lower().startswith("bearer "):
        bearer_token = auth_hdr.split(" ", 1)[1].strip()
        if safe_token_compare(bearer_token, settings.AUTH_TOKEN):
            return

    ident = _get_current_identity(request)
    if ident and ident.is_admin:
        return

    identity_id = ident.id if ident else get_client_ip(request)
    is_guest = not ident or ident.is_guest or not ident.user_id

    # 1. Burst rate limit
    try:
        allowed, retry_after = await _consume_token(
            f"burst:feasibility:{identity_id}",
            capacity=10.0,
            refill_rate_per_sec=10.0 / 60.0,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"detail": "Rate limit exceeded for feasibility requests.", "code": "rate_limit_exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as e:
        if settings.is_production():
            raise HTTPException(
                status_code=503,
                detail={"code": "rate_limiter_unavailable", "detail": "Service unavailable: rate limiter is unreachable."},
                headers={"Retry-After": "5"},
            ) from e

    # 2. Daily cap (5/day for guests)
    if is_guest:
        allowed, retry_after = check_identity_daily_cap(identity_id, "feasibility", cap=5)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"detail": "Daily cap of 5 feasibility reviews reached for this session. Please try again tomorrow.", "code": "daily_cap_exceeded"},
                headers={"Retry-After": str(retry_after)},
            )

