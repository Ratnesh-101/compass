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


_OPEN_STATUSES = (
    OpportunityStatus.OPEN_CONFIRMED,
    OpportunityStatus.UPCOMING_CONFIRMED,
    OpportunityStatus.ANNOUNCED,
    "OPEN_CONFIRMED",
    "UPCOMING_CONFIRMED",
    "ANNOUNCED",
)


def _opp_has_source(opp: Dict[str, Any], source_type: str) -> bool:
    sources = opp.get("sources") or []
    return any(
        isinstance(s, dict) and s.get("source_type") == source_type
        for s in sources
    ) or opp.get("source_type") == source_type


async def count_open_by_source(source_type: str) -> int:
    """Number of opportunities that have an opportunity_sources row of that source_type
    and current_status IN ('OPEN_CONFIRMED', 'UPCOMING_CONFIRMED', 'ANNOUNCED').
    """
    pool = await get_pool()
    if not pool:
        count = 0
        for opp in _in_memory_opportunities.values():
            if not isinstance(opp, dict):
                continue
            if opp.get("current_status") not in _OPEN_STATUSES:
                continue
            if _opp_has_source(opp, source_type):
                count += 1
        return count

    query = """
    SELECT COUNT(*)
    FROM opportunities
    WHERE current_status IN ('OPEN_CONFIRMED', 'UPCOMING_CONFIRMED', 'ANNOUNCED')
      AND id IN (
          SELECT opportunity_id
          FROM opportunity_sources
          WHERE source_type = $1
      );
    """
    async with pool.acquire() as conn:
        val = await conn.fetchval(query, source_type)
        return int(val or 0)


async def count_open_matching(urls: set[str] | Set[str], source_type: str) -> int:
    """Of those open opportunities with source_type, how many have canonical_url in urls."""
    if not urls:
        return 0
    url_list = [u for u in urls if u and isinstance(u, str)]
    if not url_list:
        return 0

    pool = await get_pool()
    if not pool:
        url_set = set(url_list)
        count = 0
        for opp in _in_memory_opportunities.values():
            if not isinstance(opp, dict):
                continue
            canon = opp.get("canonical_url")
            if not canon or canon not in url_set:
                continue
            if opp.get("current_status") not in _OPEN_STATUSES:
                continue
            if _opp_has_source(opp, source_type):
                count += 1
        return count

    query = """
    SELECT COUNT(*)
    FROM opportunities
    WHERE canonical_url = ANY($1::text[])
      AND current_status IN ('OPEN_CONFIRMED', 'UPCOMING_CONFIRMED', 'ANNOUNCED')
      AND id IN (
          SELECT opportunity_id
          FROM opportunity_sources
          WHERE source_type = $2
      );
    """
    async with pool.acquire() as conn:
        val = await conn.fetchval(query, url_list, source_type)
        return int(val or 0)


async def demote_opportunities_by_canonical_urls(
    urls: set[str] | Set[str],
    source_type: str,
    evidence: str,
) -> int:
    """Demote open opportunities matching canonical URLs to NEEDS_VERIFICATION.

    Sets:
      current_status = 'NEEDS_VERIFICATION'
      verification_evidence = evidence
      updated_at = now
    (Leaves application_url_checked untouched).
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
        url_set = set(url_list)
        changed = 0
        for opp in _in_memory_opportunities.values():
            if not isinstance(opp, dict):
                continue
            canon = opp.get("canonical_url")
            if not canon or canon not in url_set:
                continue
            if opp.get("current_status") not in _OPEN_STATUSES:
                continue
            if not _opp_has_source(opp, source_type):
                continue
            opp["current_status"] = OpportunityStatus.NEEDS_VERIFICATION
            opp["verification_evidence"] = evidence
            opp["updated_at"] = now_dt
            changed += 1
        return changed

    query = """
    UPDATE opportunities
    SET current_status = 'NEEDS_VERIFICATION',
        verification_evidence = $2,
        updated_at = now()
    WHERE canonical_url = ANY($1::text[])
      AND current_status IN ('OPEN_CONFIRMED', 'UPCOMING_CONFIRMED', 'ANNOUNCED')
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


async def reopen_wrongly_closed(
    active_urls: set[str] | Set[str],
    source_type: str,
    evidence_markers: tuple,
) -> int:
    """Reopen listings that were wrongly closed by dataset-delisting rules back to NEEDS_VERIFICATION.

    Rows with current_status='CLOSED_CONFIRMED', source_type matching, canonical_url in active_urls,
    and verification_evidence starting with any marker in evidence_markers.
    Sets:
      current_status = 'NEEDS_VERIFICATION'
      verification_evidence = 'Simplify lists this as active again; the employer page is being checked.'
      updated_at = now
    Returns the number of opportunities reopened.
    """
    if not active_urls or not evidence_markers:
        return 0
    url_list = [u for u in active_urls if u and isinstance(u, str)]
    markers_list = [m for m in evidence_markers if m and isinstance(m, str)]
    if not url_list or not markers_list:
        return 0

    reopen_evidence = "Simplify lists this as active again; the employer page is being checked."
    now_dt = datetime.now(timezone.utc)
    pool = await get_pool()
    if not pool:
        url_set = set(url_list)
        changed = 0
        for opp in _in_memory_opportunities.values():
            if not isinstance(opp, dict):
                continue
            canon = opp.get("canonical_url")
            if not canon or canon not in url_set:
                continue
            curr_status = opp.get("current_status")
            if curr_status not in (OpportunityStatus.CLOSED_CONFIRMED, "CLOSED_CONFIRMED"):
                continue
            ev = opp.get("verification_evidence") or ""
            if not any(ev.startswith(m) for m in markers_list):
                continue
            if not _opp_has_source(opp, source_type):
                continue
            opp["current_status"] = OpportunityStatus.NEEDS_VERIFICATION
            opp["verification_evidence"] = reopen_evidence
            opp["updated_at"] = now_dt
            changed += 1
        return changed

    query = """
    UPDATE opportunities
    SET current_status = 'NEEDS_VERIFICATION',
        verification_evidence = $2,
        updated_at = now()
    WHERE canonical_url = ANY($1::text[])
      AND current_status = 'CLOSED_CONFIRMED'
      AND id IN (
          SELECT opportunity_id
          FROM opportunity_sources
          WHERE source_type = $3
      )
      AND EXISTS (
          SELECT 1 FROM unnest($4::text[]) AS m
          WHERE LEFT(opportunities.verification_evidence, char_length(m)) = m
      );
    """
    async with pool.acquire() as conn:
        status = await conn.execute(query, url_list, reopen_evidence, source_type, markers_list)
        try:
            return int(status.split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0


async def select_delisted_for_check(
    source_type: str,
    markers: tuple,
    limit: int,
) -> list[dict]:
    """Select rows in NEEDS_VERIFICATION with verification_evidence starting with any of the markers.

    Ordered by oldest updated_at first, up to limit.
    Returns list of dicts with keys: id, current_status, application_url, last_verified_at.
    """
    if limit <= 0 or not markers:
        return []
    markers_list = [m for m in markers if m and isinstance(m, str)]
    if not markers_list:
        return []

    pool = await get_pool()
    if not pool:
        matched: List[tuple[Any, Dict[str, Any]]] = []
        for k, opp in _in_memory_opportunities.items():
            if not isinstance(opp, dict):
                continue
            curr_status = opp.get("current_status")
            if curr_status not in (OpportunityStatus.NEEDS_VERIFICATION, "NEEDS_VERIFICATION"):
                continue
            ev = opp.get("verification_evidence") or ""
            if not any(ev.startswith(m) for m in markers_list):
                continue
            if not _opp_has_source(opp, source_type):
                continue
            matched.append((k, opp))

        def _sort_key(o: Dict[str, Any]) -> datetime:
            val = o.get("updated_at")
            if isinstance(val, datetime):
                return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            if isinstance(val, str):
                try:
                    dt = datetime.fromisoformat(val)
                    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            return datetime.min.replace(tzinfo=timezone.utc)

        matched.sort(key=lambda item: _sort_key(item[1]))
        return [
            {
                "id": opp.get("id") if opp.get("id") is not None else k,
                "current_status": opp.get("current_status"),
                "application_url": opp.get("official_application_url") or opp.get("canonical_url"),
                "last_verified_at": opp.get("last_verified_at"),
            }
            for k, opp in matched[:limit]
        ]

    query = """
    SELECT id, current_status, official_application_url, canonical_url, last_verified_at
    FROM opportunities
    WHERE current_status = 'NEEDS_VERIFICATION'
      AND id IN (
          SELECT opportunity_id
          FROM opportunity_sources
          WHERE source_type = $1
      )
      AND EXISTS (
          SELECT 1 FROM unnest($2::text[]) AS m
          WHERE LEFT(opportunities.verification_evidence, char_length(m)) = m
      )
    ORDER BY updated_at ASC NULLS FIRST, id ASC
    LIMIT $3;
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, source_type, markers_list, limit)
        return [
            {
                "id": row["id"],
                "current_status": row["current_status"],
                "application_url": row["official_application_url"] or row["canonical_url"],
                "last_verified_at": row["last_verified_at"],
            }
            for row in rows
        ]
