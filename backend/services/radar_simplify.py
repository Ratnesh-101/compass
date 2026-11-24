"""
Compass — Internship Radar: SimplifyJobs student-internship dataset adapter.

Reads the public, community-maintained ``listings.json`` (data only, no code is fetched or run) and
normalises computer-science related internships (software, AI/ML/data, hardware) into the same
dict shape the radar sync already ingests for JobSpy.

Honesty rules:
1. Listings enter as NEEDS_VERIFICATION. Only ``verify_opportunity_status`` may promote one to
   OPEN_CONFIRMED (see ``verify_candidates``); the dataset's own "active" flag is not verification.
2. ``date_posted`` is a real epoch timestamp, so it is stored with precision "exact".
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from backend.memory import radar as radar_memory
from backend.memory.radar import update_opportunity_verification
from backend.memory.radar_close import select_delisted_for_check
from backend.models_radar import EmployerType, OpportunityStatus
from backend.services.radar_sources import canonicalize_url, infer_category, infer_employer_type
from backend.services.radar_verifier import is_fetch_failure, verify_opportunity_status

logger = logging.getLogger("compass.radar.simplify")

SIMPLIFY_LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
)
SOURCE_NAME = "SimplifyJobs/Summer2027-Internships"
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_LISTINGS_PER_SYNC = 2000

SIMPLIFY_DELISTED_EVIDENCE = "Simplify no longer lists this as active; the employer page is being checked."
LEGACY_CLOSE_EVIDENCE = "No longer listed as active in SimplifyJobs/Summer2027-Internships"
MIN_DATASET_ROWS = 5000
MIN_ACTIVE_CSE = 1000
MAX_DEMOTE_FRACTION = 0.10
MIN_DEMOTE_CAP = 50
SETTLE_BATCH = 150
SETTLE_BUDGET_SECONDS = 60.0

# Computer-science related categories. Product, quant and other tracks are left out on purpose.
CSE_CATEGORIES = {
    "software", "software engineering", "ai/ml/data", "data science, ai & machine learning", "hardware",
}


def assess_dataset(
    total_rows: int,
    active_count: int,
    inactive_urls: set,
    active_canonicals: set,
) -> Tuple[bool, str]:
    """Validate dataset sanity against row and active thresholds."""
    if total_rows < MIN_DATASET_ROWS:
        return (False, f"total_rows ({total_rows}) < MIN_DATASET_ROWS ({MIN_DATASET_ROWS})")
    if active_count < MIN_ACTIVE_CSE:
        return (False, f"active_count ({active_count}) < MIN_ACTIVE_CSE ({MIN_ACTIVE_CSE})")
    if len(inactive_urls) == 0 and active_count == 0:
        return (False, "inactive set is empty and active_count is 0")
    return (True, "")


def plan_demotion(
    candidate_urls: set,
    active_canonicals: set,
    tracked_open: int,
    matching_open: int,
) -> Tuple[Set[str], str]:
    """Calculate candidate demotions bounded by the safety cap."""
    to_demote = candidate_urls - active_canonicals
    cap = max(MIN_DEMOTE_CAP, int(tracked_open * MAX_DEMOTE_FRACTION))
    if matching_open > cap:
        return (set(), f"would demote {matching_open} listings, more than the safety cap of {cap}")
    return (to_demote, "")


def _is_india(locations: List[str]) -> bool:
    return any("india" in (loc or "").lower() for loc in locations)


def normalize_simplify_listing(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a radar opportunity dict for one dataset row, or None when it should be skipped."""
    if not item.get("active") or item.get("is_visible") is False:
        return None
    if str(item.get("category") or "").strip().lower() not in CSE_CATEGORIES:
        return None
    url = str(item.get("url") or "").strip()
    company = str(item.get("company_name") or "").strip()
    title = str(item.get("title") or "").strip()
    if not (url.startswith("http") and company and title):
        return None

    locations = [str(x) for x in (item.get("locations") or [])]
    location = "; ".join(locations[:3]) or "Flexible"
    low = location.lower()
    posted_ts = item.get("date_posted")
    posted_dt = datetime.fromtimestamp(posted_ts, tz=timezone.utc) if isinstance(posted_ts, (int, float)) else None
    if posted_dt and posted_dt > datetime.now(timezone.utc):
        posted_dt = None  # implausible future timestamp: store nothing rather than a wrong time
    cat = infer_category(title)
    return {
        "company_name": company,
        "role_title": title,
        "employer_type": infer_employer_type(company, cat, source_name="simplify") or EmployerType.ENTERPRISE,
        "opportunity_type": "internship",
        "category": cat,
        "location": location,
        "work_arrangement": "remote" if "remote" in low else ("hybrid" if "hybrid" in low else "onsite"),
        "country": "India" if _is_india(locations) else ("USA" if "usa" in low or ", " in location else "Global"),
        "is_india_eligible": _is_india(locations),
        "official_application_url": url,
        "canonical_url": canonicalize_url(url, role_title=title) or url,
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": posted_dt.date() if posted_dt else date.today(),
        "description": f"{title} at {company}. Terms: {', '.join(item.get('terms') or []) or 'not stated'}.",
        "verification_evidence": f"Listed as active in {SOURCE_NAME}; not yet checked against the employer's page.",
        "employer_identity_verified": False,
        "official_source_confirmed": False,
        "application_url_checked": False,
        "source_name": SOURCE_NAME,
        "source_type": "simplify_listings",
        "source_url": url,
        "source_authority": "tier_2",
        "posted_at": posted_dt.isoformat() if posted_dt else None,
        "posted_at_precision": "exact" if posted_dt else "unknown",
        "posting_datetime_utc": posted_dt.isoformat() if posted_dt else None,
        "requirements": {"required_skills": [], "eligible_countries": [], "eligible_degree_types": list(item.get("degrees") or [])},
    }


def split_simplify_dataset(
    rows: Any,
    limit: int = MAX_LISTINGS_PER_SYNC,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """
    Split Simplify dataset rows into active opportunities and inactive canonical URLs.
    - active_opps: CSE categories, newest first, deduped, limited to ``limit``.
    - inactive_canonical_urls: set of canonical URLs of CSE-category rows whose active is false or is_visible is false.
    """
    if not isinstance(rows, list):
        return [], set()

    dict_rows = [r for r in rows if isinstance(r, dict)]
    dict_rows.sort(key=lambda r: r.get("date_updated") or r.get("date_posted") or 0, reverse=True)

    active_opps: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    inactive_canonical_urls: Set[str] = set()

    for r in dict_rows:
        cat = str(r.get("category") or "").strip().lower()
        if cat not in CSE_CATEGORIES:
            continue

        if not r.get("active") or r.get("is_visible") is False:
            url = str(r.get("url") or "").strip()
            title = str(r.get("title") or "").strip()
            if url.startswith("http"):
                canon = canonicalize_url(url, role_title=title) or url
                if canon:
                    inactive_canonical_urls.add(canon)
            continue

        if len(active_opps) < limit:
            norm = normalize_simplify_listing(r)
            if not norm or norm["canonical_url"] in seen:
                continue
            seen.add(norm["canonical_url"])
            active_opps.append(norm)

    return active_opps, inactive_canonical_urls


async def fetch_simplify_dataset_checked(
    limit: int = MAX_LISTINGS_PER_SYNC,
) -> Tuple[List[Dict[str, Any]], Set[str], int]:
    """Download the dataset, validate JSON shape, and return (active_opps, inactive_canonical_urls, total_rows)."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(SIMPLIFY_LISTINGS_URL)
        resp.raise_for_status()
        if len(resp.content) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Simplify listings file is larger than expected; refusing to parse it")
        rows = resp.json()

    if not isinstance(rows, list):
        raise ValueError("unexpected Simplify file layout")

    total_rows = len(rows)
    if total_rows == 0:
        raise ValueError("unexpected Simplify file layout")

    valid_dict_count = sum(
        1 for r in rows
        if isinstance(r, dict) and "url" in r and "company_name" in r and "title" in r
    )
    if (valid_dict_count / total_rows) < 0.90:
        raise ValueError("unexpected Simplify file layout")

    active_opps, inactive_urls = split_simplify_dataset(rows, limit=limit)
    return active_opps, inactive_urls, total_rows


async def fetch_simplify_dataset(
    limit: int = MAX_LISTINGS_PER_SYNC,
) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Download the dataset and return (active_opps, inactive_canonical_urls)."""
    active_opps, inactive_urls, _ = await fetch_simplify_dataset_checked(limit=limit)
    return active_opps, inactive_urls


async def fetch_simplify_opportunities(limit: int = MAX_LISTINGS_PER_SYNC) -> List[Dict[str, Any]]:
    """Download the dataset and return up to ``limit`` newest CSE listings, de-duplicated by URL."""
    active_opps, _ = await fetch_simplify_dataset(limit=limit)
    return active_opps


async def verify_candidates(
    opps: List[Dict[str, Any]],
    max_checks: int = 700,
    concurrency: int = 16,
    budget_seconds: float = 150.0,
) -> int:
    """Run the real verifier on listings; promote only what it confirms. Returns the OPEN_CONFIRMED count."""
    from backend.services.radar_verifier import is_specific_ats_job_url, verify_opportunity_status

    def _is_ats(opp: Any) -> bool:
        try:
            url = (
                opp.get("official_application_url")
                if isinstance(opp, dict)
                else getattr(opp, "official_application_url", None)
            )
            return bool(is_specific_ats_job_url(str(url or "")))
        except Exception:
            return False

    ordered = sorted(opps, key=lambda opp: 0 if _is_ats(opp) else 1)
    to_check = ordered[:max_checks]

    deadline = time.monotonic() + budget_seconds
    sem = asyncio.Semaphore(concurrency)
    confirmed = 0

    async def _one(opp: Dict[str, Any]) -> None:
        nonlocal confirmed
        try:
            if time.monotonic() > deadline:
                return
            async with sem:
                try:
                    url = (
                        opp.get("official_application_url", "")
                        if isinstance(opp, dict)
                        else getattr(opp, "official_application_url", "")
                    )
                    curr_status = (
                        opp.get("current_status", OpportunityStatus.NEEDS_VERIFICATION)
                        if isinstance(opp, dict)
                        else getattr(opp, "current_status", OpportunityStatus.NEEDS_VERIFICATION)
                    )
                    status, evidence, checked_at = await asyncio.wait_for(
                        verify_opportunity_status(str(url or ""), curr_status), timeout=25
                    )
                except Exception as exc:  # network failure leaves the listing untouched
                    title = opp.get("role_title") if isinstance(opp, dict) else getattr(opp, "role_title", "unknown")
                    logger.debug("verify failed for %s: %s", title, exc)
                    return
            if status in (OpportunityStatus.OPEN_CONFIRMED, OpportunityStatus.CLOSED_CONFIRMED):
                opp["current_status"] = status
                opp["verification_evidence"] = evidence
                opp["application_url_checked"] = True
                opp["last_verified_at"] = checked_at
                if status == OpportunityStatus.OPEN_CONFIRMED:
                    confirmed += 1
        except Exception as exc:
            title = opp.get("role_title") if isinstance(opp, dict) else getattr(opp, "role_title", "unknown")
            logger.debug("candidate processing failed for %s: %s", title, exc)

    await asyncio.gather(*[_one(o) for o in to_check], return_exceptions=True)
    return confirmed


async def settle_delisted_listings(
    limit: int = SETTLE_BATCH,
    budget_seconds: float = SETTLE_BUDGET_SECONDS,
    verify: Any = verify_opportunity_status,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Verify delisted listings against employer pages and settle their statuses.

    Selects up to `limit` delisted rows in NEEDS_VERIFICATION.
    Transitions CLOSED_CONFIRMED (HTTP 404/410/closed) or OPEN_CONFIRMED (still open).
    Leaves fetch failures and exceptions untouched. Never raises.
    """
    summary = {
        "checked": 0,
        "closed": 0,
        "reopened": 0,
        "unchanged": 0,
        "errors": 0,
    }
    deadline = time.monotonic() + budget_seconds
    try:
        rows = await select_delisted_for_check(
            "simplify_listings",
            (SIMPLIFY_DELISTED_EVIDENCE, "Simplify lists this as active again"),
            limit,
        )
    except Exception as exc:
        logger.warning("Failed to select delisted listings for settlement: %s", exc)
        summary["errors"] += 1
        return summary

    for row in rows:
        if time.monotonic() >= deadline:
            break
        app_url = row.get("application_url")
        opp_id = row.get("id")
        if not app_url or opp_id is None:
            summary["unchanged"] += 1
            continue

        summary["checked"] += 1
        time_left = deadline - time.monotonic()
        if time_left <= 0:
            break
        call_timeout = min(20.0, time_left)

        try:
            status, evidence, verified_at = await asyncio.wait_for(
                verify(str(app_url), "NEEDS_VERIFICATION"),
                timeout=call_timeout,
            )
        except Exception as exc:
            logger.debug("Settlement verification failed for %s (%s): %s", opp_id, app_url, exc)
            summary["errors"] += 1
            continue

        if is_fetch_failure(evidence):
            summary["unchanged"] += 1
            continue

        if status in (OpportunityStatus.CLOSED_CONFIRMED, "CLOSED_CONFIRMED"):
            if not dry_run:
                try:
                    await radar_memory.update_opportunity_verification(
                        opportunity_id=opp_id,
                        current_status="CLOSED_CONFIRMED",
                        verification_evidence=evidence,
                        last_verified_at=verified_at,
                    )
                except Exception as db_exc:
                    logger.warning("Failed to update closed verification for %s: %s", opp_id, db_exc)
                    summary["errors"] += 1
                    continue
            summary["closed"] += 1
        elif status in (OpportunityStatus.OPEN_CONFIRMED, "OPEN_CONFIRMED"):
            if not dry_run:
                try:
                    await radar_memory.update_opportunity_verification(
                        opportunity_id=opp_id,
                        current_status="OPEN_CONFIRMED",
                        verification_evidence=evidence,
                        last_verified_at=verified_at,
                    )
                except Exception as db_exc:
                    logger.warning("Failed to update reopened verification for %s: %s", opp_id, db_exc)
                    summary["errors"] += 1
                    continue
            summary["reopened"] += 1
        else:
            summary["unchanged"] += 1

    return summary
