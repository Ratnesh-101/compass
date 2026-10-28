"""
Compass — Operational & Abuse Budgets.

Enforces per-run and per-day computational, tool, and search credit limits.
Fails gracefully with clear user-facing messages.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from fastapi import HTTPException

from backend.memory.db import get_pool
from backend.services import budget_context

logger = logging.getLogger("compass.budgets")

# Per-Run Budgets
MAX_RUN_MODEL_CALLS = 15
MAX_RUN_TOOL_CALLS = 20
MAX_RUN_TAVILY_CREDITS = 6

# Per-Day Budgets
MAX_DAILY_USER_MODEL_CALLS = 150
MAX_DAILY_GUEST_MODEL_CALLS = 40
# Documented defaults; enforcement reads the live Settings values
# (TAVILY_DAILY_USER_CREDITS / TAVILY_DAILY_GUEST_CREDITS), which fall back to these.
MAX_DAILY_USER_TAVILY_CREDITS = 30
MAX_DAILY_GUEST_TAVILY_CREDITS = 25


class BudgetExceededError(Exception):
    """Raised when an execution or daily budget is exceeded."""
    def __init__(self, message: str, budget_type: str, limit: int, current: int):
        super().__init__(message)
        self.budget_type = budget_type
        self.limit = limit
        self.current = current


def check_run_limits(model_calls: int, tool_calls: int, tavily_credits: int) -> None:
    """Validate that the active agent run has not exceeded per-run budget limits."""
    if model_calls > MAX_RUN_MODEL_CALLS:
        raise BudgetExceededError(
            f"Per-run model call budget exceeded ({model_calls}/{MAX_RUN_MODEL_CALLS}). Run terminated gracefully.",
            "model_calls",
            MAX_RUN_MODEL_CALLS,
            model_calls,
        )
    if tool_calls > MAX_RUN_TOOL_CALLS:
        raise BudgetExceededError(
            f"Per-run tool call budget exceeded ({tool_calls}/{MAX_RUN_TOOL_CALLS}). Run terminated gracefully.",
            "tool_calls",
            MAX_RUN_TOOL_CALLS,
            tool_calls,
        )
    if tavily_credits > MAX_RUN_TAVILY_CREDITS:
        raise BudgetExceededError(
            f"Per-run Tavily search credit budget exceeded ({tavily_credits}/{MAX_RUN_TAVILY_CREDITS}). Search capped gracefully.",
            "tavily_credits",
            MAX_RUN_TAVILY_CREDITS,
            tavily_credits,
        )


_daily_recap_calls: Dict[str, Dict[str, int]] = {}  # date_str -> {identity_id -> count}
MAX_DAILY_IDENTITY_RECAP_CALLS = 10  # Cap recap calls per identity per day


def check_daily_budget(identity_id: str, cost_increment_usd: float = 0.0, limit: int = MAX_DAILY_IDENTITY_RECAP_CALLS) -> None:
    """Validate identity's daily model/recap call budget by counting calls (not word estimates).
    Raises HTTPException(429) if daily call limit is exceeded.
    """
    from datetime import date
    today_str = date.today().isoformat()
    if today_str not in _daily_recap_calls:
        _daily_recap_calls.clear()
        _daily_recap_calls[today_str] = {}

    calls_today = _daily_recap_calls[today_str].get(identity_id, 0)
    if calls_today >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily recap call budget of {limit} calls reached for this identity. Please try again tomorrow.",
        )
    _daily_recap_calls[today_str][identity_id] = calls_today + 1


def reset_daily_budget(identity_id: Optional[str] = None) -> None:
    """Reset daily budget counts for tests."""
    from datetime import date
    today_str = date.today().isoformat()
    if identity_id and today_str in _daily_recap_calls:
        _daily_recap_calls[today_str].pop(identity_id, None)
    else:
        _daily_recap_calls.clear()



def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


def _daily_tavily_limit(is_guest: bool) -> int:
    """Live per-identity daily limit from settings; invalid values fall back to the default (never disabled)."""
    default = MAX_DAILY_GUEST_TAVILY_CREDITS if is_guest else MAX_DAILY_USER_TAVILY_CREDITS
    name = "TAVILY_DAILY_GUEST_CREDITS" if is_guest else "TAVILY_DAILY_USER_CREDITS"
    value = getattr(_get_budget_settings(), name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        logger.warning("Invalid %s=%r; using default %d", name, value, default)
        return default
    return value


def _daily_identity_exceeded(is_guest: bool, limit: int) -> HTTPException:
    identity_label = "guest session" if is_guest else "user account"
    return HTTPException(
        status_code=429,
        detail={
            "code": "tavily_budget_exceeded",
            "message": (
                f"Daily Tavily search credit budget of {limit} credits reached for this "
                f"{identity_label}. Please try again tomorrow."
            ),
        },
        headers={"Retry-After": str(_seconds_until_utc_midnight())},
    )


async def _identity_credits_today(identity_id: str) -> int:
    """Sum today's (UTC) Tavily credits recorded for ONE identity. Raises on DB errors."""
    pool = await get_pool()
    if not pool:
        return 0
    async with pool.acquire() as conn:
        used = await conn.fetchval(
            "SELECT COALESCE(SUM(credits), 0) FROM tavily_usage_log "
            "WHERE identity = $1 AND created_at >= (date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')",
            identity_id,
        )
    return int(used or 0)


async def check_daily_identity_budget(
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    cost: int = 0,
) -> None:
    """Check ONE identity's Tavily credits for the current UTC day against its guest/user limit.

    The identity is ``user_id`` (authenticated) or else ``guest_id``. Raises HTTPException(429)
    with code ``tavily_budget_exceeded`` when used + cost would exceed the limit (with cost=0,
    when the limit is already reached). Fails open on DB errors (the global cap is the hard backstop).
    """
    is_guest = bool(not user_id or (guest_id and not user_id))
    identity_id = user_id or guest_id
    if not identity_id:
        return
    limit = _daily_tavily_limit(is_guest)
    try:
        used = await _identity_credits_today(identity_id)
    except Exception as e:
        logger.warning("Could not verify daily Tavily budget against DB: %s", e)
        return
    if used + max(0, cost) > limit or (cost == 0 and used >= limit):
        raise _daily_identity_exceeded(is_guest, limit)


async def enforce_tavily_budget(cost: int) -> None:
    """Enforce per-run, global and per-identity Tavily budgets BEFORE spending ``cost`` credits.

    Per-run credits are reserved on success; the caller must refund via
    ``budget_context.add_run_credits(-cost)`` if the Tavily call then fails.
    Raises BudgetExceededError (per-run) or HTTPException (429 daily / global, 503 kill switch).
    Jobs without a bound identity (nightly consolidation, radar sync) face only the global cap.
    """
    cost = max(0, int(cost))
    used = budget_context.run_credits_used()
    if used is not None and used + cost > MAX_RUN_TAVILY_CREDITS:
        check_run_limits(0, 0, used + cost)

    await check_global_spend_cap()

    caller = budget_context.get_identity()
    if caller is not None and not caller.is_admin:
        await check_daily_identity_budget(
            user_id=None if caller.is_guest else caller.identity_id,
            guest_id=caller.identity_id if caller.is_guest else None,
            cost=cost,
        )

    budget_context.add_run_credits(cost)


def _get_budget_settings():
    from backend.config import get_settings
    return get_settings()


def _fail_closed_in_production(settings: Any, what: str, exc: Exception) -> None:
    """Global abuse caps fail closed (503) in production when the DB check errors; fail open elsewhere."""
    logger.warning("%s check failed: [%s] %s", what, type(exc).__name__, exc)
    if settings.is_production():
        raise HTTPException(
            status_code=503,
            detail=f"Service temporarily unavailable: {what} could not be verified.",
            headers={"Retry-After": "5"},
        ) from exc


async def check_global_spend_cap(pool: Any = None) -> None:
    """Validate that global daily consumption across all users and guests has not exceeded hard limits.
    Prevents sybil or mass-guest creation attacks from draining paid external API credits.
    """
    settings = _get_budget_settings()
    import os
    if settings.COMPASS_KILL_SWITCH_ACTIVE or os.environ.get("COMPASS_KILL_SWITCH_ACTIVE", "").lower() in ("true", "1", "yes"):
        raise HTTPException(
            status_code=503,
            detail="Service temporarily paused: Global API kill-switch is engaged.",
        )

    tav_cap = getattr(settings, "GLOBAL_DAILY_TAVILY_CREDIT_CAP", 100)

    try:
        p = pool or await get_pool()
        if p:
            async with p.acquire() as conn:
                global_tav = await conn.fetchval(
                    "SELECT COALESCE(SUM(credits), 0) FROM tavily_usage_log WHERE created_at >= date_trunc('day', now())"
                ) or 0
                if int(global_tav) >= tav_cap:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Global daily Tavily credit cap ({tav_cap} credits) reached. Operations paused until reset.",
                    )
    except HTTPException:
        raise
    except Exception as e:
        _fail_closed_in_production(settings, "global spend cap", e)


async def check_global_mint_cap(pool: Any = None) -> None:
    """Check that total minted guests today do not exceed the DB-backed global mint cap.
    
    Prevents bot networks or distributed sybil scripts from creating unbounded guest sessions.
    """
    settings = _get_budget_settings()
    import os
    if settings.COMPASS_KILL_SWITCH_ACTIVE or os.environ.get("COMPASS_KILL_SWITCH_ACTIVE", "").lower() in ("true", "1", "yes"):
        raise HTTPException(
            status_code=503,
            detail="Service temporarily paused: Global API kill-switch is engaged.",
        )

    mint_cap = getattr(settings, "GLOBAL_DAILY_MINT_CAP", 200)

    try:
        p = pool or await get_pool()
        if p:
            async with p.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM guest_mint_log WHERE created_at >= date_trunc('day', now())"
                ) or 0
                if int(count) >= mint_cap:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Global daily guest creation limit of {mint_cap} reached. Guest session creation paused until tomorrow.",
                    )
    except HTTPException:
        raise
    except Exception as e:
        _fail_closed_in_production(settings, "global mint cap", e)


async def record_guest_mint(guest_id: str, client_ip: str, pool: Any = None) -> None:
    """Record guest session creation in DB for audit and global abuse tracking."""
    try:
        p = pool or await get_pool()
        if p:
            async with p.acquire() as conn:
                await conn.execute(
                    "INSERT INTO guest_mint_log (guest_id, client_ip, created_at) VALUES ($1, $2, now())",
                    guest_id,
                    client_ip,
                )
    except Exception as e:
        logger.warning(f"Failed to record guest mint in DB: {e}")


async def prune_expired_guests(retention_days: int = 30, pool: Any = None, dry_run: bool = False) -> int:
    """Purge expired guest sessions, guest mint logs, and orphaned conversations (count only when dry_run)."""
    try:
        p = pool or await get_pool()
        if p:
            async with p.acquire() as conn:
                if dry_run:
                    interval = str(retention_days)
                    mint_rows = await conn.fetchval(
                        "SELECT COUNT(*) FROM guest_mint_log WHERE created_at < now() - ($1 || ' days')::interval",
                        interval,
                    )
                    conv_rows = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM conversations
                        WHERE (user_id LIKE 'guest_%' OR user_id IS NULL)
                          AND last_active_at < now() - ($1 || ' days')::interval
                        """,
                        interval,
                    )
                    return int(mint_rows or 0) + int(conv_rows or 0)
                res1 = await conn.execute(
                    "DELETE FROM guest_mint_log WHERE created_at < now() - ($1 || ' days')::interval",
                    str(retention_days),
                )
                res2 = await conn.execute(
                    """
                    DELETE FROM conversations
                    WHERE (user_id LIKE 'guest_%' OR user_id IS NULL)
                      AND last_active_at < now() - ($1 || ' days')::interval
                    """,
                    str(retention_days),
                )
                count1 = int(res1.split()[-1]) if res1 and "DELETE" in res1 else 0
                count2 = int(res2.split()[-1]) if res2 and "DELETE" in res2 else 0
                return count1 + count2
    except Exception as e:
        logger.warning(f"Guest session pruning failed: {e}")
    return 0

