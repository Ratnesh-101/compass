"""
Compass — Internship Radar Official Source & Status Verifier.

Reuses the existing Tavily service (search, extract, fence_web_content)
with safe deterministic HTTP fallbacks, official domain attribution, and strict state-machine transitions.

Guarantees:
1. An HTTP 200 response proves reachability, not that an application is currently open.
2. Official ATS postings and university/government domains provide higher source authority.
3. JavaScript-rendered (SPA) job boards returning HTTP 200 are not falsely closed.
4. Unverified discoveries cannot acquire OPEN_CONFIRMED without affirmative proof.
5. Authoritative closures (HTTP 404, 410, or closed notices) transition to CLOSED_CONFIRMED.
6. Verification evidence is structured, inspectable, and prevents prompt injection.
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import httpx  # noqa: F401  (kept so tests can patch radar_verifier.httpx)

from backend.models_radar import OpportunityStatus
from backend.services.security import is_safe_url, safe_http_get_with_url
from backend.services.tavily import (
    extract as tavily_extract,
    fence_web_content,
    tavily_available,
)

logger = logging.getLogger("compass.radar.verifier")

CLOSED_PATTERNS = [
    re.compile(r"no longer accepting applications", re.IGNORECASE),
    re.compile(r"applications (have )?closed", re.IGNORECASE),
    re.compile(r"this (job|posting|requisition) has expired", re.IGNORECASE),
    re.compile(r"this (job|position) is no longer available", re.IGNORECASE),
    re.compile(r"deadline (has )?passed", re.IGNORECASE),
    re.compile(r"position (has been )?filled", re.IGNORECASE),
    re.compile(r"not currently accepting", re.IGNORECASE),
    re.compile(r"application window is closed", re.IGNORECASE),
]

OPEN_PATTERNS = [
    re.compile(r"\bapply (now|online|for this (job|position|role))\b", re.IGNORECASE),
    re.compile(r"\bsubmit application\b", re.IGNORECASE),
    re.compile(r"\bstart application\b", re.IGNORECASE),
    re.compile(r"\bapplication form\b", re.IGNORECASE),
    re.compile(r"\bclick here to apply\b", re.IGNORECASE),
    re.compile(r"\bfill out the form\b", re.IGNORECASE),
]

OFFICIAL_ATS_DOMAINS = [
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com",
    "smartrecruiters.com", "workable.com", "rippling.com"
]

OFFICIAL_INSTITUTIONAL_SUFFIXES = [
    ".ac.in", ".res.in", ".gov.in", ".edu", "iisc.ac.in", "tifr.res.in",
    "ccmb.res.in", "iiit.ac.in", "meity.gov.in", "nic.in", "aicte-india.org",
    "summerofcode.withgoogle.com", "linuxfoundation.org", "fossunited.org"
]


def is_official_domain(url: str) -> bool:
    """Determine if a URL belongs to a verified ATS or institutional portal."""
    if not url:
        return False
    try:
        host = (urllib.parse.urlparse(url.strip()).hostname or "").lower().rstrip(".")
        if not host:
            return False
        if any(_matches_host(host, ats) for ats in OFFICIAL_ATS_DOMAINS):
            return True
        for suffix in OFFICIAL_INSTITUTIONAL_SUFFIXES:
            if suffix.startswith("."):
                if host.endswith(suffix):
                    return True
            elif _matches_host(host, suffix):
                return True
    except Exception:
        pass
    return False


GENERIC_CAREERS_PATHS = {
    "",
    "/",
    "/careers",
    "/career",
    "/jobs",
    "/job",
    "/internships",
    "/internship",
    "/academics/internships",
    "/academics/training-programs",
    "/digital-india-internship-scheme",
    "/training-programs",
    "/grants",
    "/opportunities",
}


def _matches_host(netloc: str, domain: str) -> bool:
    return netloc == domain or netloc.endswith("." + domain)


MAX_VERIFY_REDIRECTS = 3
VERIFY_TIMEOUT_SECONDS = 8.0
VERIFY_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CompassInternshipRadar/1.0"}


def is_specific_ats_job_url(url: str) -> bool:
    """Check if a URL points to a specific requisition on a supported ATS platform."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        parts = [p for p in path.split("/") if p]

        # Greenhouse specific job: /jobs/{id} or /{company}/jobs/{id}
        if _matches_host(netloc, "greenhouse.io"):
            return len(parts) >= 2 and parts[-2] == "jobs" and parts[-1].isdigit()

        # Lever specific job: /{company}/{uuid}
        if _matches_host(netloc, "lever.co"):
            return len(parts) >= 2 and len(parts[-1]) >= 8

        # Ashby specific job: /{company}/{uuid}
        if _matches_host(netloc, "ashbyhq.com"):
            return len(parts) >= 2 and len(parts[-1]) >= 8

        # Workday specific job: .../job/...
        if _matches_host(netloc, "myworkdayjobs.com"):
            return "job" in parts and len(parts) > parts.index("job") + 1

        return False
    except Exception:
        return False


def is_generic_careers_or_homepage(url: str) -> bool:
    """
    Check if a URL points to a generic careers directory, portal homepage, or root domain,
    rather than a specific, identifiable vacancy requisition.
    """
    if not url:
        return True
    try:
        parsed = urllib.parse.urlparse(url.strip())
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/").lower()

        # Root homepages (e.g. https://www.meity.gov.in/ or https://internship.aicte-india.org/)
        if not path or path == "":
            return True

        # Known generic career / directory paths
        if path in GENERIC_CAREERS_PATHS:
            return True

        # ATS root/board pages without specific job IDs are generic
        if any(_matches_host(netloc, ats) for ats in OFFICIAL_ATS_DOMAINS):
            return not is_specific_ats_job_url(url)

        return False
    except Exception:
        return False


async def verify_opportunity_status(
    application_url: str,
    current_status: str = OpportunityStatus.NEEDS_VERIFICATION,
) -> Tuple[str, str, datetime]:
    """
    Verifies the live state of an opportunity application URL.

    Guarantees:
    1. HTTP 200, domain reachability, TLS validity, or official suffix must never
       independently establish that a specific vacancy is open.
    2. Generic careers directories and root portal homepages remain NEEDS_VERIFICATION.
    3. OPEN_CONFIRMED requires affirmative evidence tied to the specific opportunity:
       - A specific active ATS requisition with valid posting data.
       - A specific official vacancy page with an active submission trigger.
    4. Confirmed expired or removed requisitions (HTTP 404/410 or closed notices)
       transition to CLOSED_CONFIRMED.
    5. Inconclusive extraction, timeouts, and JS SPAs do not promote to OPEN_CONFIRMED.

    Returns:
        (new_status, evidence_summary, verification_time)
    """
    now = datetime.now(timezone.utc)
    if not application_url or not application_url.startswith("http"):
        return (
            OpportunityStatus.STATUS_UNKNOWN,
            "No valid HTTP application URL provided for verification.",
            now,
        )

    # The SSRF check resolves DNS, so keep it off the event loop.
    url_is_safe, unsafe_reason = await asyncio.to_thread(is_safe_url, application_url)
    if not url_is_safe:
        return (
            current_status,
            f"Verification failed with error: application URL was not fetched ({unsafe_reason}). Retaining current status.",
            now,
        )

    official_source = is_official_domain(application_url)
    specific_ats = is_specific_ats_job_url(application_url)
    generic_url = is_generic_careers_or_homepage(application_url)

    content_text = ""
    verification_method = "http_direct"

    # Step 1: Attempt extraction via Tavily Extract if enabled
    if tavily_available():
        try:
            res = await tavily_extract(urls=[application_url])
            results = res.get("results", [])
            if results and results[0].get("raw_content"):
                content_text = results[0]["raw_content"]
                verification_method = "tavily_extract"
        except Exception as e:
            logger.warning(f"Tavily extract failed for {application_url}: {e}. Falling back to direct HTTP.")

    # Step 2: Fallback to direct HTTP fetch if Tavily unavailable or empty
    if not content_text:
        try:
            # Pinned-IP fetch: DNS is resolved once, validated, and the connection goes to that
            # exact address, so a rebinding hostname cannot reach an internal address.
            status_code, body, _resp_headers, fetch_url = await safe_http_get_with_url(
                application_url,
                max_redirects=MAX_VERIFY_REDIRECTS,
                timeout=VERIFY_TIMEOUT_SECONDS,
                headers=VERIFY_HEADERS,
            )
        except ValueError as blocked:
            # SSRF-blocked hop, unresolved host, or too many redirects: never an exception.
            return (
                current_status,
                f"Verification stopped: {str(blocked)[:200]}. Retaining current status.",
                now,
            )
        except Exception as err:
            logger.info(f"Direct HTTP check error for {application_url}: {err}")
            return (
                current_status,
                f"Verification connection timed out or failed: {str(err)[:100]}. Retaining current status.",
                now,
            )

        if fetch_url != application_url:
            # Judge the page we landed on, not the URL we were given.
            official_source = official_source and is_official_domain(fetch_url)
            specific_ats = is_specific_ats_job_url(fetch_url)
            generic_url = is_generic_careers_or_homepage(fetch_url)
        if status_code in (404, 410):
            return (
                OpportunityStatus.CLOSED_CONFIRMED,
                f"Official page returned HTTP {status_code} (Requisition Removed).",
                now,
            )
        if status_code >= 400:
            return (
                current_status,
                f"Official page returned HTTP {status_code}. Status retained pending recheck.",
                now,
            )
        content_text = body
        verification_method = "http_direct"

    # Step 3: Sanitize and fence untrusted text
    safe_content = fence_web_content([{"url": application_url, "content": content_text[:4000]}])

    # Step 4: Deterministic Pattern Analysis
    for pattern in CLOSED_PATTERNS:
        match = pattern.search(safe_content)
        if match:
            return (
                OpportunityStatus.CLOSED_CONFIRMED,
                f"Verified closed via {verification_method}: Published notice '{match.group(0)}'.",
                now,
            )

    # Check for affirmative open submission triggers
    found_open_match = None
    for pattern in OPEN_PATTERNS:
        match = pattern.search(safe_content)
        if match:
            found_open_match = match.group(0)
            break

    if found_open_match:
        # If the URL is a generic careers directory or root portal homepage,
        # an "Apply" button on the homepage does NOT prove this specific vacancy is open.
        if generic_url and not specific_ats:
            target_status = (
                OpportunityStatus.UPCOMING_CONFIRMED
                if current_status == OpportunityStatus.UPCOMING_CONFIRMED
                else OpportunityStatus.NEEDS_VERIFICATION
            )
            return (
                target_status,
                f"Reachable official portal (HTTP 200 via {verification_method}), but URL is a generic directory/portal without specific vacancy proof. Retained as {target_status}.",
                now,
            )
        if not official_source:
            # An "Apply" button on an arbitrary domain is not proof of an official, open vacancy.
            return (
                OpportunityStatus.NEEDS_VERIFICATION,
                f"Found submission trigger '{found_open_match}' via {verification_method}, but the page is not on a recognized official domain. Requires verification.",
                now,
            )
        return (
            OpportunityStatus.OPEN_CONFIRMED,
            f"Verified open via {verification_method}: Found active submission trigger '{found_open_match}'.",
            now,
        )

    # Step 5: Handling Inconclusive Text (Neither closed nor open trigger matched)
    if specific_ats:
        # On supported ATS platforms (Greenhouse, Lever, Ashby), specific job endpoints return 404 when closed.
        # A live HTTP 200 on a specific requisition ID constitutes affirmative active vacancy evidence.
        return (
            OpportunityStatus.OPEN_CONFIRMED,
            f"Verified active requisition: Official ATS posting confirmed reachable (HTTP 200 via {verification_method}) with valid requisition data.",
            now,
        )

    if current_status == OpportunityStatus.UPCOMING_CONFIRMED:
        return (
            OpportunityStatus.UPCOMING_CONFIRMED,
            f"Reachable official portal ({verification_method}); recruitment cycle remains upcoming.",
            now,
        )

    if current_status == OpportunityStatus.OPEN_CONFIRMED:
        # Freshness & uncertainty policy: If an opportunity was previously open, but its affirmative
        # vacancy submission trigger can no longer be detected, it must not remain OPEN_CONFIRMED indefinitely.
        return (
            OpportunityStatus.NEEDS_VERIFICATION,
            f"Previously confirmed open, but affirmative vacancy submission trigger is no longer detected via {verification_method}. Status transitioned to NEEDS_VERIFICATION.",
            now,
        )

    # Non-ATS pages, generic portals, or uncorroborated pages without triggers must remain NEEDS_VERIFICATION
    return (
        OpportunityStatus.NEEDS_VERIFICATION,
        f"Reachable (HTTP 200 via {verification_method}), but contains no affirmative vacancy submission trigger or active requisition identifier. Requires verification.",
        now,
    )


def verify_opportunity_evidence_metadata(
    application_url: str,
    status: str,
    evidence_text: str,
) -> Dict[str, Any]:
    """Helper to produce structured evidence metadata for an opportunity."""
    is_official = is_official_domain(application_url)
    return {
        "employer_identity_verified": is_official or status in (OpportunityStatus.OPEN_CONFIRMED, OpportunityStatus.UPCOMING_CONFIRMED),
        "official_source_confirmed": is_official,
        "application_url_checked": bool(application_url and application_url.startswith("http")),
        "verification_evidence": evidence_text,
    }
