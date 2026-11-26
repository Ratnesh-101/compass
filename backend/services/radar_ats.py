"""Compass — Public ATS Adapter for India internships (Greenhouse, Lever, Ashby)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.models_radar import EmployerType, OpportunityStatus
from backend.services.radar_ats_adapters import is_india_location
from backend.services.radar_ats_companies import ATS_COMPANIES
from backend.services.radar_sources import canonicalize_url, infer_category, infer_employer_type
from backend.services.security import safe_http_get

logger = logging.getLogger("compass.radar.ats")

_TITLE_INTERN_RE = re.compile(r"\b(?:internships?|interns?|trainees?)\b", re.IGNORECASE)

API_TEMPLATES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def _parse_datetime(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
        return dt if dt <= datetime.now(timezone.utc) else None
    if isinstance(raw, (int, float)):
        try:
            ts = float(raw) / 1000.0 if float(raw) > 1e11 else float(raw)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            return dt if dt <= datetime.now(timezone.utc) else None
        except Exception:
            return None
    if isinstance(raw, str) and raw.strip():
        cleaned = raw.strip()
        if cleaned.endswith(("Z", "z")):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt if dt <= datetime.now(timezone.utc) else None
        except Exception:
            return None
    return None


def _is_valid_http_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        p = urllib.parse.urlsplit(url.strip())
        return p.scheme.lower() in ("http", "https") and bool(p.hostname)
    except Exception:
        return False


def _build_opportunity(
    *,
    company_name: str,
    role_title: str,
    location_str: str,
    official_url: str,
    provider: str,
    posted_dt: Optional[datetime],
    source_url: str = "",
    workplace_hint: str = "",
) -> Dict[str, Any]:
    cat = infer_category(role_title)
    low = f"{location_str} {workplace_hint}".lower()
    work_arr = "remote" if "remote" in low else ("hybrid" if "hybrid" in low else "onsite")
    canon_url = canonicalize_url(official_url, role_title=role_title) or official_url
    emp_type = infer_employer_type(company_name, cat) or EmployerType.ENTERPRISE
    now = datetime.now(timezone.utc)

    return {
        "company_name": company_name,
        "role_title": role_title,
        "employer_type": emp_type,
        "opportunity_type": "internship",
        "category": cat,
        "location": location_str,
        "work_arrangement": work_arr,
        "country": "India",
        "is_india_eligible": True,
        "official_application_url": official_url,
        "canonical_url": canon_url,
        "current_status": OpportunityStatus.OPEN_CONFIRMED,
        "confirmed_open_date": posted_dt.date() if posted_dt else date.today(),
        "description": f"{role_title} at {company_name}. Location: {location_str}.",
        "verification_evidence": "Listed on the company job board API",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
        "last_verified_at": now,
        "source_name": f"{company_name} Official Career Board",
        "source_type": f"ats_{provider}_api",
        "source_url": source_url or official_url,
        "source_authority": "tier_1",
        "posted_at": posted_dt.isoformat() if posted_dt else None,
        "posted_at_precision": "exact" if posted_dt else "unknown",
        "posting_datetime_utc": posted_dt.isoformat() if posted_dt else None,
        "requirements": {"required_skills": [], "eligible_countries": ["India"], "eligible_degree_types": []},
    }


def parse_greenhouse(payload: Any, company: str, source_url: str = "") -> List[Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return []
    results: List[Dict[str, Any]] = []
    for job in payload["jobs"]:
        if not isinstance(job, dict):
            continue
        title = str(job.get("title") or "").strip()
        if not title or not _TITLE_INTERN_RE.search(title):
            continue
        loc = job.get("location")
        loc_str = str(loc.get("name") if isinstance(loc, dict) else (loc or "")).strip()
        if not is_india_location(loc_str):
            continue
        url = str(job.get("absolute_url") or "").strip()
        if not url and job.get("id"):
            url = f"https://boards.greenhouse.io/jobs/{job['id']}"
        if not _is_valid_http_url(url):
            continue
        results.append(
            _build_opportunity(
                company_name=company,
                role_title=title,
                location_str=loc_str,
                official_url=url,
                provider="greenhouse",
                posted_dt=_parse_datetime(job.get("updated_at")),
                source_url=source_url,
            )
        )
    return results


def parse_lever(payload: Any, company: str, source_url: str = "") -> List[Dict[str, Any]]:
    rows = payload if isinstance(payload, list) else (payload.get("postings") if isinstance(payload, dict) else None)
    if not isinstance(rows, list):
        return []
    results: List[Dict[str, Any]] = []
    for job in rows:
        if not isinstance(job, dict):
            continue
        title = str(job.get("text") or job.get("title") or "").strip()
        if not title or not _TITLE_INTERN_RE.search(title):
            continue
        cats = job.get("categories") or {}
        loc_str = str(cats.get("location") if isinstance(cats, dict) else (job.get("location") or "")).strip()
        if not is_india_location(loc_str):
            continue
        url = str(job.get("hostedUrl") or job.get("applyUrl") or "").strip()
        if not url and job.get("id"):
            url = f"https://jobs.lever.co/jobs/{job['id']}"
        if not _is_valid_http_url(url):
            continue
        results.append(
            _build_opportunity(
                company_name=company,
                role_title=title,
                location_str=loc_str,
                official_url=url,
                provider="lever",
                posted_dt=_parse_datetime(job.get("createdAt")),
                source_url=source_url,
                workplace_hint=str(job.get("workplaceType") or ""),
            )
        )
    return results


def parse_ashby(payload: Any, company: str, source_url: str = "") -> List[Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        return []
    results: List[Dict[str, Any]] = []
    for job in payload["jobs"]:
        if not isinstance(job, dict) or job.get("isListed") is False:
            continue
        title = str(job.get("title") or "").strip()
        if not title or not _TITLE_INTERN_RE.search(title):
            continue
        loc = job.get("location")
        loc_str = str(loc.get("name") if isinstance(loc, dict) else (loc or "")).strip()
        if not is_india_location(loc_str):
            continue
        url = str(job.get("jobUrl") or job.get("applyUrl") or "").strip()
        if not url and job.get("id"):
            url = f"https://jobs.ashbyhq.com/jobs/{job['id']}"
        if not _is_valid_http_url(url):
            continue
        results.append(
            _build_opportunity(
                company_name=company,
                role_title=title,
                location_str=loc_str,
                official_url=url,
                provider="ashby",
                posted_dt=_parse_datetime(job.get("publishedAt")),
                source_url=source_url,
                workplace_hint="remote" if job.get("isRemote") is True else "",
            )
        )
    return results


async def fetch_ats_opportunities(
    companies: Optional[List[Tuple[str, str, str]]] = None,
    concurrency: int = 8,
    per_request_timeout: float = 10.0,
    budget_seconds: float = 90.0,
) -> List[Dict[str, Any]]:
    """Fetch job boards across ATS companies. Concurrency 8, 10s per-req, 90s budget. Never raises."""
    target = companies if companies is not None else ATS_COMPANIES
    deadline = time.monotonic() + budget_seconds
    sem = asyncio.Semaphore(concurrency)

    async def _fetch_company(provider: str, slug: str, company_name: str) -> List[Dict[str, Any]]:
        rem = deadline - time.monotonic()
        if rem <= 0:
            return []
        tmpl = API_TEMPLATES.get(provider.lower().strip())
        if not tmpl:
            return []
        url = tmpl.format(slug=slug)
        timeout = min(per_request_timeout, max(0.5, rem))
        try:
            async with sem:
                rem_sem = deadline - time.monotonic()
                if rem_sem <= 0:
                    return []
                status_code, text, _ = await safe_http_get(url, timeout=min(timeout, rem_sem))
            if status_code != 200 or not text:
                return []
            data = json.loads(text)
            p = provider.lower().strip()
            if p == "greenhouse":
                return parse_greenhouse(data, company_name, source_url=url)
            elif p == "lever":
                return parse_lever(data, company_name, source_url=url)
            elif p == "ashby":
                return parse_ashby(data, company_name, source_url=url)
            return []
        except Exception as exc:
            logger.debug("Skipping company %s (%s): %s", company_name, slug, exc)
            return []

    results = await asyncio.gather(*[_fetch_company(p, s, c) for p, s, c in target], return_exceptions=True)
    all_opps: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for res in results:
        if isinstance(res, list):
            for opp in res:
                c = opp.get("canonical_url") or opp.get("official_application_url")
                if c and c not in seen:
                    seen.add(c)
                    all_opps.append(opp)
    return all_opps
