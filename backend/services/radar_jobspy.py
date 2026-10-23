"""
Compass — JobSpy Internship Discovery Skill & Adapter.

Read-only, bounded skill that queries public job boards (LinkedIn, Indeed, Glassdoor, ZipRecruiter)
using JobSpy.
Includes:
- 24-hour recency classification (VERIFIED_WITHIN_24H vs APPROXIMATE vs UNKNOWN).
- Normalized opportunity dictionary schema matching Radar inventory.
- URL canonicalization and deduplication.
- Structured execution summary and observability.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.models_radar import EmployerType, OpportunityStatus
from backend.services.radar_ats_adapters import is_india_or_remote, is_internship_role
from backend.services.radar_sources import canonicalize_url, infer_category, infer_employer_type

logger = logging.getLogger("compass.services.radar_jobspy")

MAX_JOBSPY_WORKERS = 2

# Dedicated bounded worker pool (max_workers=2) prevents uncontrolled thread accumulation
# when underlying scraper HTTP operations hang or exceed per-source timeouts.
_jobspy_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_JOBSPY_WORKERS,
    thread_name_prefix="compass_jobspy_worker",
)
_active_jobspy_workers = 0
_jobspy_worker_lock = threading.Lock()


class JobSpySaturationError(RuntimeError):
    """Raised when executor worker capacity is saturated to prevent silent queueing."""
    pass


# Default bounded search parameters for autonomous and scheduled runs
DEFAULT_SEARCH_TERMS = [
    "software engineering intern",
    "ai engineer intern",
    "machine learning intern",
    "data science intern",
    "research intern",
]

DEFAULT_SITES = ["indeed", "linkedin", "glassdoor", "zip_recruiter"]


def classify_posting_recency(
    date_posted: Any,
    now: Optional[datetime] = None,
    source_clock_skew_tolerance_hours: float = 0.0,
) -> Dict[str, Any]:
    """
    Classifies posting date with strict 24.0-hour window and timestamp precision auditing.
    - is_verified_24h (bool): True ONLY IF exact timestamp is confirmed with 0.0 <= age_hours <= 24.0
    - recency_tier: 'VERIFIED_WITHIN_24H' | 'APPROXIMATE_RECENCY' | 'UNKNOWN'
    - timestamp_precision: 'EXACT_TIMESTAMP' | 'DATE_ONLY' | 'APPROXIMATE' | 'NONE'
    - normalized_date: date object if determinable
    - posting_datetime_utc: ISO string if exact timestamp available
    - age_hours: float age in hours if exact timestamp available
    - evidence: string explaining the classification
    """
    if date_posted is None:
        return {
            "is_verified_24h": False,
            "recency_tier": "UNKNOWN",
            "timestamp_precision": "NONE",
            "normalized_date": None,
            "posting_datetime_utc": None,
            "age_hours": None,
            "evidence": "Source provided no posting timestamp",
        }

    now_utc = now if now is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    today_utc = now_utc.date()

    parsed_dt: Optional[datetime] = None
    parsed_date: Optional[date] = None
    is_exact_timestamp = False

    if isinstance(date_posted, datetime):
        is_exact_timestamp = True
        if date_posted.tzinfo is None:
            parsed_dt = date_posted.replace(tzinfo=timezone.utc)
        else:
            parsed_dt = date_posted.astimezone(timezone.utc)
        parsed_date = parsed_dt.date()
    elif isinstance(date_posted, date):
        # Python date without hour/min precision
        is_exact_timestamp = False
        parsed_date = date_posted
    elif isinstance(date_posted, str):
        date_str = date_posted.strip()
        has_time_indicator = "T" in date_str or (":" in date_str and " " in date_str)
        try:
            dt_candidate = datetime.fromisoformat(date_str)
            if has_time_indicator:
                is_exact_timestamp = True
                if dt_candidate.tzinfo is None:
                    parsed_dt = dt_candidate.replace(tzinfo=timezone.utc)
                else:
                    parsed_dt = dt_candidate.astimezone(timezone.utc)
                parsed_date = parsed_dt.date()
            else:
                parsed_date = dt_candidate.date()
                is_exact_timestamp = False
        except Exception:
            try:
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                is_exact_timestamp = False
            except Exception:
                pass

    if not parsed_date:
        return {
            "is_verified_24h": False,
            "recency_tier": "UNKNOWN",
            "timestamp_precision": "NONE",
            "normalized_date": None,
            "posting_datetime_utc": None,
            "age_hours": None,
            "evidence": f"Unparseable date value: {date_posted}",
        }

    # Reject future dates beyond small clock drift (e.g. 1 day for date-only)
    if not is_exact_timestamp:
        if parsed_date > today_utc + timedelta(days=1):
            return {
                "is_verified_24h": False,
                "recency_tier": "UNKNOWN",
                "timestamp_precision": "DATE_ONLY",
                "normalized_date": None,
                "posting_datetime_utc": None,
                "age_hours": None,
                "evidence": f"Plausibility failure: future date {parsed_date}",
            }
        # Calendar date only cannot verify exact 24-hour window
        return {
            "is_verified_24h": False,
            "recency_tier": "APPROXIMATE_RECENCY",
            "timestamp_precision": "DATE_ONLY",
            "normalized_date": parsed_date,
            "posting_datetime_utc": None,
            "age_hours": None,
            "evidence": f"Source supplied date-only ({parsed_date}) without time precision; cannot verify within strict 24.0-hour window",
        }

    # Handle exact timestamp
    age_hours = (now_utc - parsed_dt).total_seconds() / 3600.0

    # Strict plausibility: timestamps in the future are classified as UNKNOWN
    # unless an explicit, validated source clock offset tolerance is configured.
    if age_hours < 0.0:
        if source_clock_skew_tolerance_hours > 0.0 and age_hours >= -source_clock_skew_tolerance_hours:
            return {
                "is_verified_24h": True,
                "recency_tier": "VERIFIED_WITHIN_24H",
                "timestamp_precision": "EXACT_TIMESTAMP",
                "normalized_date": parsed_date,
                "posting_datetime_utc": parsed_dt.isoformat(),
                "age_hours": 0.0,
                "evidence": f"Permitted under validated source clock skew tolerance ({source_clock_skew_tolerance_hours * 60:.1f}m); normalized age 0.0h (source: {parsed_dt.isoformat()})",
            }
        else:
            return {
                "is_verified_24h": False,
                "recency_tier": "UNKNOWN",
                "timestamp_precision": "EXACT_TIMESTAMP",
                "normalized_date": None,
                "posting_datetime_utc": parsed_dt.isoformat(),
                "age_hours": round(age_hours, 3),
                "evidence": f"Plausibility failure: future timestamp {parsed_dt.isoformat()} ({abs(age_hours)*60:.1f}m in future; no validated source clock offset)",
            }

    # Strict boundary: 0.0 <= age_hours <= 24.0
    if age_hours <= 24.0:
        return {
            "is_verified_24h": True,
            "recency_tier": "VERIFIED_WITHIN_24H",
            "timestamp_precision": "EXACT_TIMESTAMP",
            "normalized_date": parsed_date,
            "posting_datetime_utc": parsed_dt.isoformat(),
            "age_hours": round(age_hours, 3),
            "evidence": f"Confirmed posted {age_hours:.2f} hours ago (source: {parsed_dt.isoformat()})",
        }
    else:
        return {
            "is_verified_24h": False,
            "recency_tier": "APPROXIMATE_RECENCY",
            "timestamp_precision": "EXACT_TIMESTAMP",
            "normalized_date": parsed_date,
            "posting_datetime_utc": parsed_dt.isoformat(),
            "age_hours": round(age_hours, 3),
            "evidence": f"Posted {age_hours:.2f} hours ago (>24.0h strict boundary; source: {parsed_dt.isoformat()})",
        }


def format_compensation(
    min_amt: Any,
    max_amt: Any,
    currency: Optional[str] = "USD",
    interval: Optional[str] = "yearly",
) -> Optional[str]:
    """Validates salary range, currency, and pay period before formatting.
    Guards against NaN, Inf, empty, or negative values.
    """
    import math

    def _clean_amount(val: Any) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            if math.isnan(val) or math.isinf(val) or val <= 0:
                return None
            return float(val)
        if isinstance(val, str):
            s = val.strip().lower()
            if s in ("", "nan", "none", "null", "undefined"):
                return None
            try:
                f = float(s.replace(",", ""))
                if math.isnan(f) or math.isinf(f) or f <= 0:
                    return None
                return f
            except ValueError:
                return None
        return None

    clean_min = _clean_amount(min_amt)
    clean_max = _clean_amount(max_amt)

    if clean_min is None and clean_max is None:
        return None

    curr_str = str(currency or "").strip().upper()
    if not curr_str or curr_str.lower() in ("nan", "none", "null", "undefined"):
        curr_str = "USD"

    int_str = str(interval or "").strip().lower()
    if not int_str or int_str in ("nan", "none", "null", "undefined"):
        int_str = "year"
    elif int_str in ("yearly", "year", "annual", "annually"):
        int_str = "year"
    elif int_str in ("monthly", "month"):
        int_str = "month"
    elif int_str in ("hourly", "hour"):
        int_str = "hr"

    if clean_min is not None and clean_max is not None:
        if clean_min == clean_max:
            return f"{curr_str} {clean_min:,.0f} / {int_str}"
        low = min(clean_min, clean_max)
        high = max(clean_min, clean_max)
        return f"{curr_str} {low:,.0f} - {high:,.0f} / {int_str}"
    elif clean_min is not None:
        return f"{curr_str} {clean_min:,.0f} / {int_str}"
    elif clean_max is not None:
        return f"Up to {curr_str} {clean_max:,.0f} / {int_str}"
    return None


def normalize_jobspy_opportunity(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalizes a single JobSpy dataframe record into Compass Radar schema.
    Returns None if missing critical fields or not internship relevant.
    """
    title = str(row.get("title") or "").strip()
    company = str(row.get("company") or "").strip()
    raw_url = str(row.get("job_url_direct") or row.get("job_url") or "").strip()

    if not title or not company or not raw_url:
        return None

    # Guard against NaN/None strings from DataFrame conversion
    if any(s.lower() in ("nan", "none", "null", "undefined") for s in (title, company, raw_url)):
        return None

    # Check internship keyword relevance
    desc = str(row.get("description") or "").strip()
    if desc.lower() in ("nan", "none", "null", "undefined"):
        desc = ""
    job_type = str(row.get("job_type") or "")
    if not is_internship_role(title, desc, job_type):
        return None

    site = str(row.get("site") or "jobspy").lower().replace(" ", "_")
    location = str(row.get("location") or "").strip()
    if not location or location.lower() in ("nan", "none", "null", "undefined"):
        location = "Flexible"
    is_remote = bool(row.get("is_remote", False)) or "remote" in location.lower()
    work_arr = "remote" if is_remote else ("hybrid" if "hybrid" in location.lower() else "onsite")

    canon_url = canonicalize_url(raw_url, role_title=title)
    if not canon_url:
        canon_url = raw_url

    cat = infer_category(title)
    emp_type = infer_employer_type(company, cat, source_name=f"jobspy_{site}")

    recency_meta = classify_posting_recency(row.get("date_posted"))
    is_verified_24h = recency_meta["is_verified_24h"]
    posted_date = recency_meta["normalized_date"]
    first_seen_at = datetime.now(timezone.utc).isoformat()

    evidence_str = (
        f"Discovered via JobSpy ({site.capitalize()}). "
        f"Precision: {recency_meta['timestamp_precision']}. "
        f"Recency: {recency_meta['recency_tier']} ({recency_meta['evidence']}). "
        f"Direct posting: {raw_url[:80]}"
    )

    # Validated compensation parsing
    compensation_str = format_compensation(
        row.get("min_amount"),
        row.get("max_amount"),
        row.get("currency"),
        row.get("interval"),
    )

    # Extract required skills if present
    skills_raw = row.get("skills")
    required_skills = []
    if isinstance(skills_raw, list):
        required_skills = [
            str(s).strip()
            for s in skills_raw
            if str(s).strip() and str(s).strip().lower() not in ("nan", "none", "null", "undefined")
        ]
    elif isinstance(skills_raw, str) and skills_raw:
        required_skills = [
            s.strip()
            for s in skills_raw.split(",")
            if s.strip() and s.strip().lower() not in ("nan", "none", "null", "undefined")
        ]

    deg_types = []
    text_check = f"{title} {desc}".lower()
    if "phd" in text_check or "doctoral" in text_check:
        deg_types = ["PhD", "Doctoral"]
    elif "master" in text_check or "ms " in text_check or "m.tech" in text_check:
        deg_types = ["Masters", "MS", "M.Tech"]

    precision_val = "exact" if recency_meta["timestamp_precision"] == "EXACT_TIMESTAMP" else ("date_only" if recency_meta["timestamp_precision"] == "DATE_ONLY" else "unknown")

    india_eligible = is_india_or_remote(location, is_remote=False)

    return {
        "company_name": company,
        "role_title": title,
        "employer_type": emp_type,
        "opportunity_type": "internship",
        "category": cat,
        "location": location,
        "work_arrangement": work_arr,
        "country": "India" if "india" in location.lower() else ("USA" if "usa" in location.lower() or "united states" in location.lower() else "Global"),
        "is_india_eligible": india_eligible,
        "compensation": compensation_str,
        "official_application_url": raw_url,
        "canonical_url": canon_url,
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": posted_date or date.today(),
        "description": desc[:1500] if desc else f"{title} at {company}. Discovered on {site.capitalize()}.",
        "verification_evidence": evidence_str,
        "employer_identity_verified": False,
        "official_source_confirmed": False,
        "application_url_checked": False,
        "source_name": f"JobSpy ({site.capitalize()})",
        "source_type": f"jobspy_{site}",
        "source_url": raw_url,
        "source_authority": "tier_2",
        "is_official_source": False,
        "recency_tier": recency_meta["recency_tier"],
        "is_verified_within_24h": is_verified_24h,
        "timestamp_precision": recency_meta["timestamp_precision"],
        "posted_at": recency_meta.get("posting_datetime_utc"),
        "posted_at_precision": precision_val,
        "posting_datetime_utc": recency_meta.get("posting_datetime_utc"),
        "posting_age_hours": recency_meta.get("age_hours"),
        "first_seen_at": first_seen_at,
        "requirements": {
            "required_skills": required_skills[:8],
            "eligible_countries": ["India"] if india_eligible else [],
            "eligible_degree_types": deg_types,
        },
    }


async def discover_jobspy_opportunities(
    sites: Optional[List[str]] = None,
    search_terms: Optional[List[str]] = None,
    location: str = "Remote",
    results_wanted: int = 15,
    hours_old: int = 24,
    country_indeed: str = "usa",
    per_source_timeout_seconds: float = 25.0,
    total_timeout_seconds: float = 60.0,
) -> Dict[str, Any]:
    """
    Executes a bounded JobSpy search run across requested sites.
    Returns structured observability result including counts, per-source status, and opportunities.
    Guarantees thread-bounded execution via _jobspy_executor and dual timeout bounds (per-source and overall).
    """
    global _active_jobspy_workers
    run_id = f"jobspy_run_{uuid.uuid4().hex[:12]}"
    started_at = datetime.now(timezone.utc).isoformat()

    active_sites = sites or DEFAULT_SITES
    active_terms = search_terms or DEFAULT_SEARCH_TERMS[:2]

    summary: Dict[str, Any] = {
        "run_id": run_id,
        "source": "jobspy",
        "started_at": started_at,
        "completed_at": None,
        "status": "pending",
        "sources_attempted": len(active_sites),
        "sources_succeeded": 0,
        "sources_failed": 0,
        "empty_sources": 0,
        "raw_results": 0,
        "normalized_results": 0,
        "internship_matches": 0,
        "verified_within_24h": 0,
        "approximate_recency": 0,
        "unknown_posting_time": 0,
        "new_unique_opportunities": 0,
        "existing_opportunities_updated": 0,
        "duplicates_removed": 0,
        "rejected_by_reason": {
            "non_internship": 0,
            "missing_fields": 0,
            "invalid_url": 0,
        },
        "per_source_status": {},
        "errors": [],
        "opportunities": [],
    }

    try:
        from jobspy import scrape_jobs
    except ImportError as e:
        logger.error(f"JobSpy library not importable: {e}")
        summary["status"] = "failed"
        summary["errors"].append(f"ImportError: {str(e)}")
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        return summary

    loop = asyncio.get_running_loop()
    start_monotonic = loop.time()

    # Scrape each site independently so one site's error does not discard others
    seen_canonical = set()

    for site in active_sites:
        if loop.time() - start_monotonic >= total_timeout_seconds:
            logger.warning(f"JobSpy run {run_id} hit total timeout limit ({total_timeout_seconds}s); skipping remaining sites")
            summary["errors"].append({
                "site": site,
                "term": "all",
                "error": f"TotalTimeoutError: overall run exceeded {total_timeout_seconds}s limit",
                "error_type": "TIMEOUT",
            })
            summary["per_source_status"][site.lower().strip()] = {
                "status": "timeout",
                "error": f"TotalTimeoutError: overall run exceeded {total_timeout_seconds}s limit",
                "error_type": "TIMEOUT",
            }
            summary["sources_failed"] += 1
            continue

        site_clean = site.lower().strip()
        for term in active_terms:
            if loop.time() - start_monotonic >= total_timeout_seconds:
                break
            try:
                # Fast saturation check: reject immediately without silent queueing
                with _jobspy_worker_lock:
                    if _active_jobspy_workers >= MAX_JOBSPY_WORKERS:
                        raise JobSpySaturationError(
                            f"executor saturated: maximum concurrent workers ({MAX_JOBSPY_WORKERS}) busy"
                        )
                    _active_jobspy_workers += 1

                # Run the blocking JobSpy scraper in our dedicated bounded worker pool
                def _do_scrape(s_name=site_clean, s_term=term):
                    return scrape_jobs(
                        site_name=[s_name],
                        search_term=s_term,
                        location=location,
                        results_wanted=min(max(1, results_wanted), 20),
                        hours_old=hours_old,
                        country_indeed=country_indeed,
                        verbose=0,
                    )

                try:
                    df = await asyncio.wait_for(
                        loop.run_in_executor(_jobspy_executor, _do_scrape),
                        timeout=per_source_timeout_seconds,
                    )
                finally:
                    with _jobspy_worker_lock:
                        _active_jobspy_workers -= 1

                if df is not None and not df.empty:
                    summary["sources_succeeded"] += 1
                    raw_rows = df.to_dict(orient="records")
                    summary["raw_results"] += len(raw_rows)
                    summary["per_source_status"][site_clean] = {
                        "status": "success",
                        "raw_count": len(raw_rows),
                        "error": None,
                    }

                    for r in raw_rows:
                        # Validate internship
                        norm = normalize_jobspy_opportunity(r)
                        if not norm:
                            summary["rejected_by_reason"]["non_internship"] += 1
                            continue

                        summary["internship_matches"] += 1

                        canon = norm["canonical_url"]
                        if canon in seen_canonical:
                            summary["duplicates_removed"] += 1
                            continue
                        seen_canonical.add(canon)

                        summary["normalized_results"] += 1

                        if norm.get("is_verified_within_24h"):
                            summary["verified_within_24h"] += 1
                        elif norm.get("recency_tier") == "APPROXIMATE_RECENCY":
                            summary["approximate_recency"] += 1
                        else:
                            summary["unknown_posting_time"] += 1

                        summary["opportunities"].append(norm)
                else:
                    summary["sources_succeeded"] += 1
                    summary["empty_sources"] += 1
                    reason = "No listings returned by provider"
                    if site_clean == "zip_recruiter":
                        reason = "ZipRecruiter returned 0 listings (unsupported region for India or DOM changed)"
                    summary["per_source_status"][site_clean] = {
                        "status": "empty",
                        "raw_count": 0,
                        "reason": reason,
                    }

            except JobSpySaturationError as sat_err:
                summary["sources_failed"] += 1
                logger.warning(f"JobSpy source {site_clean} rejected on query '{term}': {sat_err}")
                summary["errors"].append({
                    "site": site_clean,
                    "term": term,
                    "error": str(sat_err),
                    "error_type": "EXECUTOR_SATURATED",
                })
                summary["per_source_status"][site_clean] = {
                    "status": "executor_saturated",
                    "error": str(sat_err),
                    "error_type": "EXECUTOR_SATURATED",
                }
            except asyncio.TimeoutError:
                summary["sources_failed"] += 1
                logger.warning(f"JobSpy source {site_clean} timed out after {per_source_timeout_seconds}s on query '{term}'")
                summary["errors"].append({
                    "site": site_clean,
                    "term": term,
                    "error": f"TimeoutError: execution exceeded {per_source_timeout_seconds}s limit",
                    "error_type": "TIMEOUT",
                })
                summary["per_source_status"][site_clean] = {
                    "status": "timeout",
                    "error": f"TimeoutError: execution exceeded {per_source_timeout_seconds}s limit",
                    "error_type": "TIMEOUT",
                }
            except Exception as site_err:
                summary["sources_failed"] += 1
                err_str = str(site_err)
                err_type = "BLOCKED_OR_RATE_LIMITED" if ("429" in err_str or "block" in err_str.lower() or "captcha" in err_str.lower()) else "SCRAPE_ERROR"
                logger.warning(f"JobSpy source {site_clean} failed ({err_type}) on query '{term}': {site_err}")
                summary["errors"].append({
                    "site": site_clean,
                    "term": term,
                    "error": err_str,
                    "error_type": err_type,
                })
                summary["per_source_status"][site_clean] = {
                    "status": "rate_limited" if "429" in err_str else "failed",
                    "error": err_str,
                    "error_type": err_type,
                }

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    if summary["raw_results"] == 0 or (summary["sources_succeeded"] == 0 and summary["sources_failed"] > 0):
        summary["status"] = "degraded"
        logger.warning(
            f"JobSpy run {run_id} degraded: all sources returned 0 results or failed. "
            f"(succeeded={summary['sources_succeeded']}, failed={summary['sources_failed']}, raw=0)"
        )
    elif summary["sources_succeeded"] > 0 and summary["sources_failed"] == 0:
        summary["status"] = "success"
    elif summary["sources_succeeded"] > 0 and summary["sources_failed"] > 0:
        summary["status"] = "partial"
    else:
        summary["status"] = "degraded"

    logger.info(
        f"JobSpy run {run_id} finished: status={summary['status']}, "
        f"raw={summary['raw_results']}, matches={summary['internship_matches']}, "
        f"24h_verified={summary['verified_within_24h']}, unique={len(summary['opportunities'])}"
    )

    return summary
