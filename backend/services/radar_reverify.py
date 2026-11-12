"""
Compass — Internship Radar Nightly Re-verification Service.

Re-verifies stale open (OPEN_CONFIRMED) internship opportunities.
Ensures listings that were previously verified as OPEN_CONFIRMED but have not been
re-confirmed within RECHECK_AFTER_DAYS (default: 14 days) are re-checked against
their authoritative live application URLs.

Honesty rules:
1. Never mark a listing OPEN_CONFIRMED unless the verifier returned OPEN_CONFIRMED.
2. On any error (network failure, timeout, parsing error), leave the row untouched.
   Do not bump its last_verified_at timestamp.
3. Never invent or infer close dates.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from backend.memory import radar as radar_memory
from backend.models_radar import OpportunityStatus
from backend.services.radar_verifier import verify_opportunity_status

logger = logging.getLogger("compass.radar.reverify")

RECHECK_AFTER_DAYS: int = 14
DEFAULT_BATCH_SIZE: int = 25
PER_CALL_TIMEOUT_SECONDS: float = 20.0
# Overall cap so a slow night cannot push the nightly job past its request timeout; unchecked rows wait for the next run.
TOTAL_BUDGET_SECONDS: float = 150.0


def _parse_datetime(val: Any) -> Optional[datetime]:
    """Parse date, datetime, timestamp, or ISO string into a timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(val, (int, float)):
        try:
            ts = val / 1000.0 if val > 1e11 else float(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned or cleaned.lower() in ("none", "null", "undefined", "nan", ""):
            return None
        iso_str = cleaned.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        try:
            d = date.fromisoformat(cleaned[:10])
            return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                d = datetime.strptime(cleaned[:10], fmt).date()
                return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
            except Exception:
                pass
    return None


async def select_stale_open_opportunities(
    limit: int = DEFAULT_BATCH_SIZE,
) -> List[Dict[str, Any]]:
    """
    Select OPEN_CONFIRMED opportunity rows whose last_verified_at is NULL or older than RECHECK_AFTER_DAYS.
    Oldest first, at most limit.
    Each returned dict has at least:
        id, current_status, last_verified_at, application_url (official_application_url or canonical_url).
    Works with asyncpg database pool and in-memory fallback.
    """
    if limit is not None and limit <= 0:
        return []

    eff_limit = limit if limit is not None else DEFAULT_BATCH_SIZE
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=RECHECK_AFTER_DAYS)

    pool = await radar_memory.get_pool()
    if pool is not None:
        query = """
        SELECT id, current_status, last_verified_at, official_application_url, canonical_url,
               company_name, role_title
        FROM opportunities
        WHERE current_status = 'OPEN_CONFIRMED'
          AND (last_verified_at IS NULL OR last_verified_at < $1)
        ORDER BY last_verified_at ASC NULLS FIRST, id ASC
        LIMIT $2
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, cutoff, eff_limit)
        results: List[Dict[str, Any]] = []
        for r in rows:
            row_dict = dict(r)
            official = (row_dict.get("official_application_url") or "").strip()
            canonical = (row_dict.get("canonical_url") or "").strip()
            row_dict["application_url"] = official or canonical
            results.append(row_dict)
        return results

    # In-memory storage fallback
    candidates: List[tuple[datetime, int, Dict[str, Any]]] = []
    for opp_id, opp in radar_memory._in_memory_opportunities.items():
        st = opp.get("current_status") if isinstance(opp, dict) else getattr(opp, "current_status", None)
        if st != OpportunityStatus.OPEN_CONFIRMED:
            continue

        raw_dt = opp.get("last_verified_at") if isinstance(opp, dict) else getattr(opp, "last_verified_at", None)
        parsed_dt = _parse_datetime(raw_dt)

        # Stale if NULL or older than RECHECK_AFTER_DAYS
        if parsed_dt is not None and parsed_dt >= cutoff:
            continue

        # Sort key: NULLs first (treated as earliest datetime), then oldest datetime, then id
        sort_dt = parsed_dt if parsed_dt is not None else datetime.min.replace(tzinfo=timezone.utc)

        eff_id = opp.get("id", opp_id) if isinstance(opp, dict) else getattr(opp, "id", opp_id)
        official = (opp.get("official_application_url") if isinstance(opp, dict) else getattr(opp, "official_application_url", "")) or ""
        canonical = (opp.get("canonical_url") if isinstance(opp, dict) else getattr(opp, "canonical_url", "")) or ""
        official_str = str(official).strip()
        canonical_str = str(canonical).strip()
        app_url = official_str or canonical_str

        row_dict: Dict[str, Any] = {
            "id": eff_id,
            "current_status": st,
            "last_verified_at": raw_dt,
            "application_url": app_url,
            "official_application_url": official,
            "canonical_url": canonical,
        }
        if isinstance(opp, dict):
            if "company_name" in opp:
                row_dict["company_name"] = opp["company_name"]
            if "role_title" in opp:
                row_dict["role_title"] = opp["role_title"]

        try:
            num_id = int(eff_id)
        except (ValueError, TypeError):
            num_id = 0

        candidates.append((sort_dt, num_id, row_dict))

    candidates.sort(key=lambda x: (x[0], x[1]))
    return [item[2] for item in candidates[:eff_limit]]


async def reverify_stale_opportunities(
    limit: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
    verify: Callable[..., Any] = verify_opportunity_status,
) -> Dict[str, Any]:
    """
    Sequentially re-verify stale OPEN_CONFIRMED opportunities.

    For each selected row:
      - Calls verify(application_url, current_status) with a 20s per-call timeout.
      - On success, persists status, evidence, and verified_at via radar_memory.update_opportunity_verification
        (unless dry_run=True).
      - If verified status is OPEN_CONFIRMED, increments still_open.
      - If verified status is changed (e.g. NEEDS_VERIFICATION or CLOSED_CONFIRMED), increments downgraded.
      - On timeout/exception, leaves row untouched (no DB writes, date unbumped) and increments errors.

    Never raises.
    Returns:
      {"checked": int, "still_open": int, "downgraded": int, "errors": int, "dry_run": bool}
    """
    checked = 0
    still_open = 0
    downgraded = 0
    errors = 0

    try:
        rows = await select_stale_open_opportunities(limit=limit)
    except Exception as err:
        logger.warning("Failed to select stale opportunities for reverification: %s", err)
        return {
            "checked": 0,
            "still_open": 0,
            "downgraded": 0,
            "errors": 1,
            "dry_run": dry_run,
        }

    started = time.monotonic()
    try:
        for row in rows:
            if time.monotonic() - started >= TOTAL_BUDGET_SECONDS:
                logger.info("Re-verification time budget reached; remaining rows wait for the next run.")
                break
            checked += 1
            opp_id = row.get("id")
            app_url = (
                row.get("application_url")
                or row.get("official_application_url")
                or row.get("canonical_url")
                or ""
            ).strip()
            curr_status = row.get("current_status") or OpportunityStatus.OPEN_CONFIRMED

            try:
                # Flexible invocation to support mocks with 1 or 2 arguments
                try:
                    call_res = verify(app_url, curr_status)
                except TypeError:
                    call_res = verify(app_url)

                if asyncio.iscoroutine(call_res) or asyncio.isfuture(call_res):
                    res = await asyncio.wait_for(call_res, timeout=PER_CALL_TIMEOUT_SECONDS)
                else:
                    res = call_res

                # Unpack (status, evidence, verified_at)
                if isinstance(res, (tuple, list)):
                    if len(res) >= 3:
                        new_status, evidence, verified_at = res[0], res[1], res[2]
                    elif len(res) == 2:
                        new_status, evidence = res[0], res[1]
                        verified_at = datetime.now(timezone.utc)
                    elif len(res) == 1:
                        new_status = res[0]
                        evidence = ""
                        verified_at = datetime.now(timezone.utc)
                    else:
                        new_status = OpportunityStatus.STATUS_UNKNOWN
                        evidence = str(res)
                        verified_at = datetime.now(timezone.utc)
                elif isinstance(res, str):
                    new_status = res
                    evidence = ""
                    verified_at = datetime.now(timezone.utc)
                else:
                    new_status = getattr(res, "status", None) or getattr(res, "current_status", None)
                    evidence = getattr(res, "evidence", "") or getattr(res, "verification_evidence", "")
                    verified_at = getattr(res, "verified_at", None) or getattr(res, "last_verified_at", None) or datetime.now(timezone.utc)

                if not new_status:
                    logger.warning("Verifier returned empty status for opportunity %s; leaving untouched.", opp_id)
                    errors += 1
                    continue

                if verified_at is None:
                    verified_at = datetime.now(timezone.utc)
                elif isinstance(verified_at, str):
                    parsed = _parse_datetime(verified_at)
                    verified_at = parsed or datetime.now(timezone.utc)
                elif isinstance(verified_at, date) and not isinstance(verified_at, datetime):
                    verified_at = datetime.combine(verified_at, datetime.min.time(), tzinfo=timezone.utc)
                elif isinstance(verified_at, datetime) and verified_at.tzinfo is None:
                    verified_at = verified_at.replace(tzinfo=timezone.utc)

                # Persist unless dry_run=True
                if not dry_run:
                    await radar_memory.update_opportunity_verification(
                        opportunity_id=opp_id,
                        current_status=str(new_status),
                        verification_evidence=str(evidence) if evidence is not None else None,
                        last_verified_at=verified_at,
                    )

                if str(new_status) == OpportunityStatus.OPEN_CONFIRMED:
                    still_open += 1
                else:
                    downgraded += 1

            except (asyncio.TimeoutError, Exception) as call_err:
                logger.warning(
                    "Re-verification error/timeout for opportunity %s (%s): %s",
                    opp_id,
                    app_url,
                    call_err,
                )
                errors += 1
    except Exception as loop_err:
        logger.error("Unexpected error in reverification loop: %s", loop_err, exc_info=True)
        errors += 1

    return {
        "checked": checked,
        "still_open": still_open,
        "downgraded": downgraded,
        "errors": errors,
        "dry_run": dry_run,
    }
