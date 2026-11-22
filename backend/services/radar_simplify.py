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
from typing import Any, Dict, List, Optional

import httpx

from backend.models_radar import EmployerType, OpportunityStatus
from backend.services.radar_sources import canonicalize_url, infer_category, infer_employer_type

logger = logging.getLogger("compass.radar.simplify")

SIMPLIFY_LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
)
SOURCE_NAME = "SimplifyJobs/Summer2027-Internships"
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024
MAX_LISTINGS_PER_SYNC = 1500
# Computer-science related categories. Product, quant and other tracks are left out on purpose.
CSE_CATEGORIES = {
    "software", "software engineering", "ai/ml/data", "data science, ai & machine learning", "hardware",
}


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


async def fetch_simplify_opportunities(limit: int = MAX_LISTINGS_PER_SYNC) -> List[Dict[str, Any]]:
    """Download the dataset and return up to ``limit`` newest CSE listings, de-duplicated by URL."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(SIMPLIFY_LISTINGS_URL)
        resp.raise_for_status()
        if len(resp.content) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Simplify listings file is larger than expected; refusing to parse it")
        rows = resp.json()
    if not isinstance(rows, list):
        return []
    rows = [r for r in rows if isinstance(r, dict)]
    rows.sort(key=lambda r: r.get("date_updated") or r.get("date_posted") or 0, reverse=True)
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in rows:
        norm = normalize_simplify_listing(r)
        if not norm or norm["canonical_url"] in seen:
            continue
        seen.add(norm["canonical_url"])
        out.append(norm)
        if len(out) >= limit:
            break
    return out


async def verify_candidates(
    opps: List[Dict[str, Any]],
    max_checks: int = 700,
    concurrency: int = 16,
    budget_seconds: float = 240.0,
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
