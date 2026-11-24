"""
Compass — Curated Opportunity Verification and Location Fixes.

Provides live verification for hand-curated listings to prevent stale open badges,
and corrective location auditing for Simplify imported rows.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.memory.radar import _in_memory_opportunities, get_pool
from backend.models_radar import OpportunityStatus
from backend.services.radar_ats_adapters import is_india_location
from backend.services.radar_profile_parse import derive_country
from backend.services.radar_verifier import (
    is_fetch_failure,
    verify_opportunity_status,
)

logger = logging.getLogger("compass.radar.curated_verify")


async def apply_verification_by_url(
    canonical_url: str,
    status: str,
    evidence: Optional[str] = None,
    verified_at: Optional[datetime] = None,
) -> int:
    """
    Apply verification result to stored row identified by canonical_url or official_application_url.
    Never touches CLOSED_CONFIRMED or CANCELLED rows.

    Returns the number of rows changed (0 or 1).
    """
    if not canonical_url:
        return 0

    status_val = status.value if hasattr(status, "value") else str(status)
    evidence_val = str(evidence) if evidence is not None else None

    if verified_at is None:
        eff_dt = datetime.now(timezone.utc)
    elif verified_at.tzinfo is None:
        eff_dt = verified_at.replace(tzinfo=timezone.utc)
    else:
        eff_dt = verified_at

    pool = await get_pool()
    if not pool:
        changed = 0
        for opp in _in_memory_opportunities.values():
            if not isinstance(opp, dict):
                continue
            c_url = opp.get("canonical_url")
            o_url = opp.get("official_application_url")
            if canonical_url not in (c_url, o_url):
                continue

            curr_status = opp.get("current_status")
            curr_val = curr_status.value if hasattr(curr_status, "value") else str(curr_status)
            if curr_val not in (
                "OPEN_CONFIRMED",
                "UPCOMING_CONFIRMED",
                "ANNOUNCED",
                "NEEDS_VERIFICATION",
            ):
                continue

            opp["current_status"] = status_val
            opp["verification_evidence"] = evidence_val
            opp["last_verified_at"] = eff_dt
            opp["updated_at"] = datetime.now(timezone.utc)
            changed += 1
        return changed

    query = """
    UPDATE opportunities
    SET current_status = $2,
        verification_evidence = $3,
        last_verified_at = $4,
        updated_at = now()
    WHERE (canonical_url = $1 OR official_application_url = $1)
      AND current_status IN ('OPEN_CONFIRMED', 'UPCOMING_CONFIRMED', 'ANNOUNCED', 'NEEDS_VERIFICATION')
    """
    try:
        async with pool.acquire() as conn:
            res = await conn.execute(query, canonical_url, status_val, evidence_val, eff_dt)
            try:
                return int(res.split()[-1])
            except (ValueError, IndexError, AttributeError):
                return 0
    except Exception as err:
        logger.warning(f"apply_verification_by_url failed for {canonical_url}: {err}")
        return 0


async def verify_curated_listings(
    items: list[dict],
    verify: Any = verify_opportunity_status,
    concurrency: int = 6,
    budget_seconds: float = 90.0,
    max_checks: Optional[int] = None,
) -> dict:
    """
    Verify hand-curated listings against live vacancy pages under concurrency and budget limits.
    Never raises.
    """
    summary: Dict[str, int] = {
        "checked": 0,
        "open": 0,
        "closed": 0,
        "needs_verification": 0,
        "unchanged": 0,
        "errors": 0,
    }
    if not items:
        return summary

    if max_checks is not None and max_checks > 0:
        items = items[:max_checks]

    try:
        start_time = time.monotonic()
        deadline = start_time + budget_seconds
        sem = asyncio.Semaphore(concurrency)

        async def _verify_item(item: dict) -> str:
            rem = deadline - time.monotonic()
            if rem <= 0:
                return "error"

            url = (
                item.get("official_application_url")
                or item.get("application_url")
                or item.get("canonical_url")
            )
            curr_status = item.get("current_status") or OpportunityStatus.OPEN_CONFIRMED
            target_url = (
                item.get("canonical_url")
                or item.get("official_application_url")
                or item.get("application_url")
            )

            if not url or not target_url:
                return "error"

            try:
                async with sem:
                    rem_sem = deadline - time.monotonic()
                    if rem_sem <= 0:
                        return "error"
                    call_timeout = min(20.0, max(0.1, rem_sem))
                    res = await asyncio.wait_for(verify(url, curr_status), timeout=call_timeout)
            except Exception as exc:
                logger.warning(f"Verification fetch error for {url}: {exc}")
                return "error"

            try:
                new_status, evidence, verified_at = res
            except Exception:
                return "error"

            if is_fetch_failure(evidence):
                return "error"

            if new_status in (OpportunityStatus.OPEN_CONFIRMED, "OPEN_CONFIRMED"):
                target_status = OpportunityStatus.OPEN_CONFIRMED
            elif new_status in (OpportunityStatus.CLOSED_CONFIRMED, "CLOSED_CONFIRMED"):
                target_status = OpportunityStatus.CLOSED_CONFIRMED
            elif new_status in (
                OpportunityStatus.NEEDS_VERIFICATION,
                OpportunityStatus.STATUS_UNKNOWN,
                "NEEDS_VERIFICATION",
                "STATUS_UNKNOWN",
            ):
                target_status = OpportunityStatus.NEEDS_VERIFICATION
            elif new_status in (OpportunityStatus.UPCOMING_CONFIRMED, "UPCOMING_CONFIRMED"):
                target_status = OpportunityStatus.UPCOMING_CONFIRMED
            else:
                target_status = new_status

            if target_status == OpportunityStatus.OPEN_CONFIRMED:
                verified_at = datetime.now(timezone.utc)
            elif verified_at is None:
                verified_at = datetime.now(timezone.utc)

            try:
                changed = await apply_verification_by_url(
                    target_url, target_status, evidence, verified_at
                )
                if (
                    changed == 0
                    and item.get("official_application_url")
                    and item.get("official_application_url") != target_url
                ):
                    changed = await apply_verification_by_url(
                        item["official_application_url"], target_status, evidence, verified_at
                    )
            except Exception as app_err:
                logger.warning(f"Failed to apply verification for {target_url}: {app_err}")
                return "error"

            if changed == 0:
                return "unchanged"
            if target_status == OpportunityStatus.OPEN_CONFIRMED:
                return "open"
            if target_status == OpportunityStatus.CLOSED_CONFIRMED:
                return "closed"
            if target_status == OpportunityStatus.NEEDS_VERIFICATION:
                return "needs_verification"
            return "unchanged"

        tasks = [asyncio.create_task(_verify_item(item)) for item in items]
        try:
            rem_budget = max(0.1, deadline - time.monotonic())
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=rem_budget,
            )
        except asyncio.TimeoutError:
            pass

        summary["checked"] = len(items)
        for t in tasks:
            if not t.done() or t.cancelled():
                summary["errors"] += 1
                continue
            try:
                r = t.result()
            except Exception:
                summary["errors"] += 1
                continue

            if r == "open":
                summary["open"] += 1
            elif r == "closed":
                summary["closed"] += 1
            elif r == "needs_verification":
                summary["needs_verification"] += 1
            elif r == "unchanged":
                summary["unchanged"] += 1
            else:
                summary["errors"] += 1

        logger.info(
            f"Curated listings verification finished: {summary['checked']} checked, "
            f"{summary['open']} open, {summary['closed']} closed, "
            f"{summary['needs_verification']} needs_verification, "
            f"{summary['unchanged']} unchanged, {summary['errors']} errors."
        )
        return summary
    except Exception as ex:
        logger.warning(f"verify_curated_listings failed: {ex}")
        summary["errors"] += len(items) - summary["checked"]
        return summary


async def fix_simplify_india_flags() -> int:
    """
    For opportunities from source 'simplify_listings' with is_india_eligible=True or country='India',
    recompute country and is_india_eligible using location adapters.
    Updates only rows whose flags change.

    Returns the number of rows changed. Never raises.
    """
    try:
        pool = await get_pool()
        if not pool:
            changed = 0
            for opp in _in_memory_opportunities.values():
                if not isinstance(opp, dict):
                    continue
                sources = opp.get("sources") or []
                has_source = any(
                    isinstance(s, dict) and s.get("source_type") == "simplify_listings"
                    for s in sources
                ) or opp.get("source_type") == "simplify_listings"
                if not has_source:
                    continue

                curr_country = opp.get("country")
                curr_eligible = opp.get("is_india_eligible")
                if not (curr_eligible is True or curr_country == "India"):
                    continue

                loc = opp.get("location")
                is_india = is_india_location(loc)
                country = derive_country(loc) or "Global"
                if not is_india and country == "India":
                    country = "Global"
                is_india_eligible = bool(is_india)

                if country != curr_country or bool(curr_eligible) != is_india_eligible:
                    opp["country"] = country
                    opp["is_india_eligible"] = is_india_eligible
                    opp["updated_at"] = datetime.now(timezone.utc)
                    changed += 1
            return changed

        select_query = """
        SELECT id, location, country, is_india_eligible
        FROM opportunities
        WHERE (is_india_eligible IS TRUE OR country = 'India')
          AND id IN (
              SELECT opportunity_id
              FROM opportunity_sources
              WHERE source_type = $1
          )
        """
        update_query = """
        UPDATE opportunities
        SET country = $2,
            is_india_eligible = $3,
            updated_at = now()
        WHERE id = $1
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(select_query, "simplify_listings")
            updates = []
            for row in rows:
                row_id = row["id"]
                loc = row["location"]
                curr_country = row["country"]
                curr_eligible = row["is_india_eligible"]

                is_india = is_india_location(loc)
                country = derive_country(loc) or "Global"
                if not is_india and country == "India":
                    country = "Global"
                is_india_eligible = bool(is_india)

                if country != curr_country or bool(curr_eligible) != is_india_eligible:
                    updates.append((row_id, country, is_india_eligible))

            for r_id, ctry, elig in updates:
                await conn.execute(update_query, r_id, ctry, elig)

            logger.info(f"fix_simplify_india_flags: updated {len(updates)} listings.")
            return len(updates)
    except Exception as err:
        logger.warning(f"fix_simplify_india_flags failed: {err}")
        return 0
