"""
Compass — Internship Radar Batch Close Operations.

Closes opportunities identified as inactive by upstream datasets or authoritative sources.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import asyncpg

from backend.memory.db import get_pool as _raw_get_pool
from backend.memory.radar import _in_memory_opportunities
from backend.models_radar import OpportunityStatus

logger = logging.getLogger("compass.memory.radar_close")

_db_pool_available: bool = True
_last_db_failure_time: float = 0.0
_DB_RETRY_INTERVAL_SEC: float = 5.0


async def get_pool() -> Optional[asyncpg.Pool]:
    """Return database pool with cooldown retry instead of permanent latch."""
    global _db_pool_available, _last_db_failure_time
    import time

    now = time.monotonic()
    if not _db_pool_available:
        if now - _last_db_failure_time < _DB_RETRY_INTERVAL_SEC:
            return None
        _db_pool_available = True
    try:
        pool = await asyncio.wait_for(_raw_get_pool(), timeout=15.0)
        if pool is not None:
            _db_pool_available = True
            return pool
        else:
            _db_pool_available = False
            _last_db_failure_time = now
            return None
    except Exception as e:
        _db_pool_available = False
        _last_db_failure_time = now
        logger.info(
            f"Database connection pool unavailable ({e}); using radar in-memory storage mode (retry in {_DB_RETRY_INTERVAL_SEC}s)."
        )
        return None


async def close_opportunities_by_canonical_urls(
    urls: set[str] | Set[str],
    source_type: str,
    evidence: str,
) -> int:
    """
    Close opportunities whose canonical_url is in urls, that have an opportunity_sources row
    with that source_type, and whose status is not already closed/cancelled.

    Sets:
      current_status = 'CLOSED_CONFIRMED'
      verification_evidence = evidence
      last_verified_at = now

    Returns the number of opportunities changed.
    """
    if not urls:
        return 0

    url_list = [u for u in urls if u and isinstance(u, str)]
    if not url_list:
        return 0

    now_dt = datetime.now(timezone.utc)
    pool = await get_pool()

    if not pool:
        # In-memory storage fallback
        url_set = set(url_list)
        changed = 0
        for opp in _in_memory_opportunities.values():
            if not isinstance(opp, dict):
                continue
            canon = opp.get("canonical_url")
            if not canon or canon not in url_set:
                continue

            curr_status = opp.get("current_status")
            if curr_status in (
                OpportunityStatus.CLOSED_CONFIRMED,
                OpportunityStatus.CANCELLED_CONFIRMED,
                "CLOSED_CONFIRMED",
                "CANCELLED_CONFIRMED",
            ):
                continue

            sources = opp.get("sources") or []
            has_source = any(
                isinstance(s, dict) and s.get("source_type") == source_type
                for s in sources
            ) or opp.get("source_type") == source_type

            if not has_source:
                continue

            opp["current_status"] = OpportunityStatus.CLOSED_CONFIRMED
            opp["verification_evidence"] = evidence
            opp["last_verified_at"] = now_dt
            opp["updated_at"] = now_dt
            changed += 1
        return changed

    query = """
    UPDATE opportunities
    SET current_status = 'CLOSED_CONFIRMED',
        verification_evidence = $2,
        last_verified_at = now(),
        updated_at = now()
    WHERE canonical_url = ANY($1::text[])
      AND current_status NOT IN ('CLOSED_CONFIRMED', 'CANCELLED_CONFIRMED')
      AND id IN (
          SELECT opportunity_id
          FROM opportunity_sources
          WHERE source_type = $3
      );
    """
    async with pool.acquire() as conn:
        status = await conn.execute(query, url_list, evidence, source_type)
        try:
            return int(status.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0
