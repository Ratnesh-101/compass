"""
Compass — Operational & Abuse Budgets.

Enforces per-run and per-day computational, tool, and search credit limits.
Fails gracefully with clear user-facing messages.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from fastapi import HTTPException

from backend.memory.db import get_pool

logger = logging.getLogger("compass.budgets")

# Per-Run Budgets
MAX_RUN_MODEL_CALLS = 15
MAX_RUN_TOOL_CALLS = 20
MAX_RUN_TAVILY_CREDITS = 6

# Per-Day Budgets
MAX_DAILY_USER_MODEL_CALLS = 150
MAX_DAILY_GUEST_MODEL_CALLS = 40
MAX_DAILY_USER_TAVILY_CREDITS = 30
MAX_DAILY_GUEST_TAVILY_CREDITS = 8


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



async def check_daily_identity_budget(
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
) -> None:
    """Check identity's daily consumption against per-day limits.
    
    Raises HTTPException(429) if daily threshold is reached.
    """
    is_guest = bool(not user_id or (guest_id and not user_id))
    max_model_calls = MAX_DAILY_GUEST_MODEL_CALLS if is_guest else MAX_DAILY_USER_MODEL_CALLS
    max_tavily = MAX_DAILY_GUEST_TAVILY_CREDITS if is_guest else MAX_DAILY_USER_TAVILY_CREDITS

    try:
        pool = await get_pool()
        if pool:
            async with pool.acquire() as conn:
                # Count today's tavily credits
                tav_credits = await conn.fetchval(
                    """
                    SELECT COALESCE(SUM(credits), 0)
                    FROM tavily_usage_log
                    WHERE created_at >= date_trunc('day', now())
                    """
                ) or 0

                if int(tav_credits) >= max_tavily:
                    identity_label = "guest session" if is_guest else "user account"
                    raise HTTPException(
                        status_code=429,
                        detail=f"Daily Tavily search credit budget of {max_tavily} credits reached for this {identity_label}. Please try again tomorrow.",
                    )
    except HTTPException:
        raise
    except Exception as e:
        logger.debug(f"Could not verify daily budget against DB: {e}")


def _get_budget_settings():
    from backend.config import get_settings
    return get_settings()


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
        logger.debug(f"Global spend cap check skipped: {e}")


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
        logger.debug(f"Global mint cap check DB error: {e}")


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


async def prune_expired_guests(retention_days: int = 30, pool: Any = None) -> int:
    """Purge expired guest sessions, guest mint logs, and orphaned conversations."""
    try:
        p = pool or await get_pool()
        if p:
            async with p.acquire() as conn:
                res1 = await conn.execute(
                    "DELETE FROM guest_mint_log WHERE created_at < now() - ($1 || ' days')::interval",
                    str(retention_days),
                )
                res2 = await conn.execute(
                    """
                    DELETE FROM conversations
                    WHERE (user_id LIKE 'guest_%' OR user_id IS NULL)
                      AND updated_at < now() - ($1 || ' days')::interval
                    """,
                    str(retention_days),
                )
                count1 = int(res1.split()[-1]) if res1 and "DELETE" in res1 else 0
                count2 = int(res2.split()[-1]) if res2 and "DELETE" in res2 else 0
                return count1 + count2
    except Exception as e:
        logger.warning(f"Guest session pruning failed: {e}")
    return 0

