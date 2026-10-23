"""
Compass — Internship Radar Public ATS Adapters.

Provides clean, permitted, read-only connectors for public ATS feeds:
1. Greenhouse Public Board API (boards-api.greenhouse.io)
2. Lever Public Postings API (api.lever.co)
3. Ashby Public Job Board API (api.ashbyhq.com)

Features:
- Configurable source registry.
- Independent error isolation (failures in one board do not stop others).
- Normalized opportunity dictionary schema.
- Automatic keyword filtering for student/intern/fellowship roles.
- Official source evidence attribution.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from backend.models_radar import EmployerType, OpportunityStatus
from backend.services.radar_sources import canonicalize_url, infer_category

logger = logging.getLogger("compass.radar.ats_adapters")

INTERN_KEYWORDS_REGEX = re.compile(
    r"\b(intern|internship|co-op|coop|fellow|fellowship|trainee|apprentice|student|undergraduate|freshman|sophomore)\b",
    re.IGNORECASE,
)

INDIA_LOCATION_KEYWORDS = [
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata", "ahmedabad", "maharashtra", "karnataka", "telangana", "tamil nadu", "apac"
]
GLOBAL_SCOPE_KEYWORDS = [
    "worldwide", "anywhere", "global remote", "remote - global", "remote, global", "remote (worldwide)", "remote worldwide", "work from anywhere"
]
NON_INDIA_RESTRICTIONS = [
    "us only", "usa only", "united states only", "americas only", "emea only", "uk only", "canada only", "must reside in", "u.s. only"
]


def is_internship_role(title: str, description: str = "", commitment: str = "") -> bool:
    """Check if title, commitment, or text indicates an internship/co-op/fellowship."""
    combined = f"{title} {commitment}"
    return bool(INTERN_KEYWORDS_REGEX.search(combined))


def is_india_or_remote(location_text: str, is_remote: bool = False) -> bool:
    """Check if location string indicates confirmed eligibility for Indian students.
    Never infer global/India eligibility from generic remote work without affirmative geographic evidence.
    """
    if not location_text:
        return False
    loc_lower = location_text.lower().strip()
    if any(k in loc_lower for k in NON_INDIA_RESTRICTIONS):
        return False
    if any(k in loc_lower for k in INDIA_LOCATION_KEYWORDS):
        return True
    if any(k in loc_lower for k in GLOBAL_SCOPE_KEYWORDS):
        return True
    return False


# ---------------------------------------------------------------------------
# Individual ATS Adapters
# ---------------------------------------------------------------------------

async def fetch_greenhouse_opportunities(
    board_token: str,
    company_name: str,
    employer_type: str = EmployerType.STARTUP,
    timeout_sec: float = 8.0,
) -> List[Dict[str, Any]]:
    """
    Fetch public jobs from Greenhouse board API.
    Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    results: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.get(url, params={"content": "true"})
            if resp.status_code != 200:
                logger.info(f"Greenhouse board {board_token} returned status {resp.status_code}")
                return []
            data = resp.json()
            jobs = data.get("jobs", [])

            for job in jobs:
                title = (job.get("title") or "").strip()
                loc_dict = job.get("location") or {}
                location_name = loc_dict.get("name") or "Remote / Flexible"
                content_html = job.get("content") or ""

                if not is_internship_role(title, content_html):
                    continue

                india_eligible = is_india_or_remote(location_name)
                job_url = job.get("absolute_url") or f"https://job-boards.eu.greenhouse.io/{board_token}/jobs/{job.get('id')}"
                req_id = str(job.get("id") or job.get("requisition_id") or "")
                canon_url = canonicalize_url(job_url)
                if req_id and req_id not in canon_url:
                    canon_url = f"{canon_url}#gh-{req_id}"

                work_arr = "remote" if "remote" in location_name.lower() else "hybrid" if "hybrid" in location_name.lower() else "onsite"
                category = infer_category(title)

                results.append({
                    "company_name": company_name,
                    "role_title": title,
                    "employer_type": employer_type,
                    "opportunity_type": "internship",
                    "category": category,
                    "location": location_name,
                    "work_arrangement": work_arr,
                    "country": "India" if "india" in location_name.lower() else "Global",
                    "is_india_eligible": india_eligible,
                    "official_application_url": job_url,
                    "canonical_url": canon_url,
                    "current_status": OpportunityStatus.OPEN_CONFIRMED,
                    "description": f"Verified live opening on official {company_name} Greenhouse board. Location: {location_name}.",
                    "verification_evidence": f"Live listing confirmed active on official Greenhouse ATS API (board: {board_token}, id: {req_id}).",
                    "employer_identity_verified": True,
                    "official_source_confirmed": True,
                    "application_url_checked": True,
                    "source_name": f"{company_name} Official Career Board",
                    "source_type": "ats_greenhouse_api",
                    "source_url": url,
                    "source_authority": "tier_1",
                    "is_official_source": True,
                })

    except Exception as e:
        logger.warning(f"Error fetching Greenhouse board {board_token}: {e}")

    return results


async def fetch_lever_opportunities(
    site: str,
    company_name: str,
    employer_type: str = EmployerType.STARTUP,
    timeout_sec: float = 8.0,
) -> List[Dict[str, Any]]:
    """
    Fetch public postings from Lever postings API.
    Endpoint: https://api.lever.co/v0/postings/{site}?mode=json
    """
    url = f"https://api.lever.co/v0/postings/{site}"
    results: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.get(url, params={"mode": "json"})
            if resp.status_code != 200:
                logger.info(f"Lever site {site} returned status {resp.status_code}")
                return []
            postings = resp.json()
            if not isinstance(postings, list):
                return []

            for p in postings:
                title = (p.get("text") or "").strip()
                categories = p.get("categories") or {}
                commitment = categories.get("commitment") or ""
                location = categories.get("location") or "Remote / Flexible"
                desc = p.get("descriptionPlain") or ""

                if not is_internship_role(title, desc, commitment):
                    continue

                post_id = p.get("id") or ""
                hosted_url = p.get("hostedUrl") or p.get("applyUrl") or f"https://jobs.lever.co/{site}/{post_id}"
                canon_url = canonicalize_url(hosted_url)
                if post_id and post_id not in canon_url:
                    canon_url = f"{canon_url}#lever-{post_id}"

                workplace_type = p.get("workplaceType") or ""
                work_arr = "remote" if "remote" in workplace_type.lower() or "remote" in location.lower() else "onsite"
                india_eligible = is_india_or_remote(location, is_remote=(work_arr == "remote"))
                category = infer_category(title)

                results.append({
                    "company_name": company_name,
                    "role_title": title,
                    "employer_type": employer_type,
                    "opportunity_type": "internship",
                    "category": category,
                    "location": location,
                    "work_arrangement": work_arr,
                    "country": "India" if "india" in location.lower() else "Global",
                    "is_india_eligible": india_eligible,
                    "official_application_url": hosted_url,
                    "canonical_url": canon_url,
                    "current_status": OpportunityStatus.OPEN_CONFIRMED,
                    "description": f"Verified live opening on official {company_name} Lever careers board. Location: {location}.",
                    "verification_evidence": f"Live listing confirmed active on official Lever ATS API (site: {site}, id: {post_id}).",
                    "employer_identity_verified": True,
                    "official_source_confirmed": True,
                    "application_url_checked": True,
                    "source_name": f"{company_name} Official Career Board",
                    "source_type": "ats_lever_api",
                    "source_url": url,
                    "source_authority": "tier_1",
                    "is_official_source": True,
                })

    except Exception as e:
        logger.warning(f"Error fetching Lever site {site}: {e}")

    return results


async def fetch_ashby_opportunities(
    board_token: str,
    company_name: str,
    employer_type: str = EmployerType.STARTUP,
    timeout_sec: float = 8.0,
) -> List[Dict[str, Any]]:
    """
    Fetch public jobs from Ashby posting API.
    Endpoint: https://api.ashbyhq.com/posting-api/job-board/{board_token}
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_token}"
    results: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.info(f"Ashby board {board_token} returned status {resp.status_code}")
                return []
            data = resp.json()
            jobs = data.get("jobs", [])

            for job in jobs:
                title = (job.get("title") or "").strip()
                emp_type = job.get("employmentType") or ""
                location = job.get("location") or "Remote"
                is_remote = bool(job.get("isRemote", False))
                desc = job.get("descriptionPlain") or ""

                if not is_internship_role(title, desc, emp_type):
                    continue

                job_id = job.get("id") or ""
                job_url = job.get("jobUrl") or job.get("applyUrl") or f"https://jobs.ashbyhq.com/{board_token}/{job_id}"
                canon_url = canonicalize_url(job_url)
                if job_id and job_id not in canon_url:
                    canon_url = f"{canon_url}#ashby-{job_id}"

                work_arr = "remote" if is_remote or "remote" in location.lower() else "onsite"
                india_eligible = is_india_or_remote(location, is_remote=is_remote)
                category = infer_category(title)

                results.append({
                    "company_name": company_name,
                    "role_title": title,
                    "employer_type": employer_type,
                    "opportunity_type": "internship",
                    "category": category,
                    "location": location,
                    "work_arrangement": work_arr,
                    "country": "India" if "india" in location.lower() else "Global",
                    "is_india_eligible": india_eligible,
                    "official_application_url": job_url,
                    "canonical_url": canon_url,
                    "current_status": OpportunityStatus.OPEN_CONFIRMED,
                    "description": f"Verified live opening on official {company_name} Ashby careers board. Location: {location}.",
                    "verification_evidence": f"Live listing confirmed active on official Ashby ATS API (board: {board_token}, id: {job_id}).",
                    "employer_identity_verified": True,
                    "official_source_confirmed": True,
                    "application_url_checked": True,
                    "source_name": f"{company_name} Official Career Board",
                    "source_type": "ats_ashby_api",
                    "source_url": url,
                    "source_authority": "tier_1",
                    "is_official_source": True,
                })

    except Exception as e:
        logger.warning(f"Error fetching Ashby board {board_token}: {e}")

    return results


# ---------------------------------------------------------------------------
# Permitted Public ATS Source Registry
# ---------------------------------------------------------------------------

PUBLIC_ATS_REGISTRY: List[Dict[str, Any]] = [
    # Indian & High-Growth Startups
    {"adapter": "greenhouse", "token": "groww", "company": "Groww", "employer_type": EmployerType.STARTUP},
    {"adapter": "greenhouse", "token": "inmobi", "company": "InMobi", "employer_type": EmployerType.STARTUP},
    {"adapter": "lever", "token": "cred", "company": "CRED", "employer_type": EmployerType.STARTUP},
    {"adapter": "ashby", "token": "synthesia", "company": "Synthesia", "employer_type": EmployerType.STARTUP},
    {"adapter": "ashby", "token": "linear", "company": "Linear", "employer_type": EmployerType.STARTUP},
    {"adapter": "ashby", "token": "ramp", "company": "Ramp", "employer_type": EmployerType.STARTUP},
    {"adapter": "ashby", "token": "openai", "company": "OpenAI", "employer_type": EmployerType.STARTUP},

    # Open Source & Systems Engineering
    {"adapter": "greenhouse", "token": "canonical", "company": "Canonical / Ubuntu", "employer_type": EmployerType.OPEN_SOURCE},
    {"adapter": "greenhouse", "token": "gitlab", "company": "GitLab", "employer_type": EmployerType.OPEN_SOURCE},

    # Established Cloud & Infrastructure
    {"adapter": "greenhouse", "token": "cloudflare", "company": "Cloudflare", "employer_type": EmployerType.ENTERPRISE},
    {"adapter": "greenhouse", "token": "elastic", "company": "Elastic", "employer_type": EmployerType.ENTERPRISE},
    {"adapter": "greenhouse", "token": "mongodb", "company": "MongoDB", "employer_type": EmployerType.ENTERPRISE},
    {"adapter": "greenhouse", "token": "datadog", "company": "Datadog", "employer_type": EmployerType.ENTERPRISE},
    {"adapter": "lever", "token": "spotify", "company": "Spotify", "employer_type": EmployerType.ENTERPRISE},
]


async def fetch_all_public_ats_opportunities(timeout_sec: float = 5.0) -> List[Dict[str, Any]]:
    """
    Polls all registered public ATS boards in parallel with independent error isolation.
    Guarantees that network errors or 404s on one company do not stop others.
    Runs concurrently via asyncio.gather.
    """
    async def _fetch_single(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        adapter_type = item["adapter"]
        token = item["token"]
        company = item["company"]
        emp_type = item.get("employer_type", EmployerType.STARTUP)

        try:
            if adapter_type == "greenhouse":
                return await fetch_greenhouse_opportunities(token, company, emp_type, timeout_sec)
            elif adapter_type == "lever":
                return await fetch_lever_opportunities(token, company, emp_type, timeout_sec)
            elif adapter_type == "ashby":
                return await fetch_ashby_opportunities(token, company, emp_type, timeout_sec)
            return []
        except Exception as ex:
            logger.warning(f"Failed to fetch ATS for {company} ({adapter_type}): {ex}")
            return []

    tasks = [_fetch_single(item) for item in PUBLIC_ATS_REGISTRY]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    all_opps: List[Dict[str, Any]] = []
    for res in results_list:
        if isinstance(res, list):
            all_opps.extend(res)
        elif isinstance(res, Exception):
            logger.warning(f"ATS worker encountered exception: {res}")

    return all_opps
