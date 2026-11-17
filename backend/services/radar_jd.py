"""
Compass — Job description and employer apply-URL fetcher for Internship Radar (T-020 / N-016).

Public entry point for other modules (Prepare Application in the career code):

    await fetch_and_store_listing_details(opportunity_id: int, *, force: bool = False) -> dict

It fetches the listing page (Tavily Extract when enabled, otherwise a pinned-IP SSRF-safe GET), stores
the full description, the employer's own apply URL and any stated deadline on the opportunity, and
returns what it found. The fetched text is untrusted web content: it is stored as data and must be
fenced (backend.services.tavily.fence_web_content) before it goes into any model prompt.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.parse
from datetime import date
from typing import Any, Dict, List, Optional

from backend.memory import radar as radar_memory
from backend.services.radar_deadline import parse_application_deadline
from backend.services.radar_verifier import is_official_domain
from backend.services.security import is_safe_url, safe_http_get_with_url
from backend.services import tavily as tavily_service

logger = logging.getLogger("compass.radar.jd")

MAX_DESCRIPTION_CHARS = 12_000
MIN_READABLE_CHARS = 200
FETCH_TIMEOUT_SECONDS = 10.0
_AGGREGATOR_HOSTS = ("linkedin.", "indeed.", "glassdoor.", "ziprecruiter.", "google.", "facebook.", "twitter.", "x.com")

_MD_LINK_RE = re.compile(r"\[([^\]\n]{1,120})\]\((https?://[^)\s]+)\)")
_HTML_LINK_RE = re.compile(r"<a\b[^>]*?href=[\"'](https?://[^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)


def html_to_text(raw: str) -> str:
    """Readable text from HTML: drops scripts/styles/tags, keeps line breaks at block boundaries."""
    s = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", raw or "")
    s = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6]|/tr)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<li\b[^>]*>", "\n- ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    lines = [" ".join(line.split()) for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def _is_aggregator(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return any(h in host for h in _AGGREGATOR_HOSTS)


def extract_apply_url(content: str, current_url: Optional[str] = None) -> Optional[str]:
    """The employer's own "Apply" link found in page text or HTML, or None.

    Only links whose visible text mentions "apply" count. Job-board, social and search hosts are
    skipped. Official ATS / institutional domains win over other candidates.
    """
    candidates: List[str] = []
    for text, url in ((m.group(1), m.group(2)) for m in _MD_LINK_RE.finditer(content or "")):
        if re.search(r"\bapply\b", text, re.IGNORECASE):
            candidates.append(url)
    for m in _HTML_LINK_RE.finditer(content or ""):
        anchor = re.sub(r"<[^>]+>", " ", m.group(2))
        if re.search(r"\bapply\b", anchor, re.IGNORECASE):
            candidates.append(html.unescape(m.group(1)))
    usable = [u for u in candidates if not _is_aggregator(u) and u != current_url]
    for u in usable:
        if is_official_domain(u):
            return u
    return usable[0] if usable else None


async def _fetch_page_text(url: str) -> Dict[str, Any]:
    """{'text', 'raw', 'method'} or {} when nothing readable could be fetched."""
    safe, _reason = await asyncio.to_thread(is_safe_url, url)
    if not safe:
        return {}
    if tavily_service.tavily_available():
        try:
            res = await tavily_service.extract(urls=[url])
            results = res.get("results", []) or []
            raw = (results[0].get("raw_content") or "") if results else ""
            if raw.strip():
                return {"text": raw, "raw": raw, "method": "tavily_extract"}
        except Exception as err:  # budget exhausted, timeout, provider error: fall back to a direct GET
            logger.info("Tavily extract failed for listing page (%s); trying direct fetch", type(err).__name__)
    try:
        status, body, _headers, _final = await safe_http_get_with_url(url, max_redirects=3, timeout=FETCH_TIMEOUT_SECONDS)
    except Exception as err:
        logger.info("Direct fetch failed for listing page (%s)", type(err).__name__)
        return {}
    if status >= 400 or not body:
        return {}
    return {"text": html_to_text(body), "raw": body, "method": "http_direct"}


def _needs_fetch(description: Optional[str]) -> bool:
    d = (description or "").strip()
    if len(d) < 400:
        return True
    return bool(re.search(r"\b(Discovered (on|via)|Verified live opening on official)\b", d[:300]))


async def _persist(opp: Any, description: str, apply_url: Optional[str], deadline: Optional[date]) -> None:
    """Write through the existing idempotent upsert so no new SQL or schema is needed."""
    await radar_memory.upsert_opportunity(
        company_name=opp.company_name,
        role_title=opp.role_title,
        canonical_url=opp.canonical_url,
        official_application_url=apply_url or opp.official_application_url,
        current_status=opp.current_status,
        opportunity_type=opp.opportunity_type,
        employer_type=opp.employer_type or "enterprise",
        category=opp.category or "general",
        location=opp.location,
        work_arrangement=opp.work_arrangement or "unknown",
        country=opp.country,
        is_india_eligible=opp.is_india_eligible,
        compensation=opp.compensation,
        duration=opp.duration,
        confirmed_close_date=deadline,
        description=description,
        employer_identity_verified=opp.employer_identity_verified,
        official_source_confirmed=opp.official_source_confirmed,
        application_url_checked=opp.application_url_checked,
    )
    if await radar_memory.get_pool() is None:  # in-memory mode: the upsert's update branch skips these fields
        row = radar_memory._in_memory_opportunities.get(opp.id)
        if row is not None:
            row["description"] = description
            if deadline:
                row["confirmed_close_date"] = deadline
            if apply_url:
                row["official_application_url"] = apply_url


async def fetch_and_store_listing_details(
    opportunity_id: int, *, force: bool = False, opportunity: Optional[Any] = None
) -> Dict[str, Any]:
    """Fetch the listing page and store its full description, employer apply URL and deadline.

    Pass `opportunity` (an OpportunityOut already loaded by the caller) to skip the lookup.
    Returns a dict with keys: opportunity_id, fetched (bool), description (str | None),
    apply_url (str | None), confirmed_close_date (ISO str | None), method
    ('tavily_extract' | 'http_direct' | 'stored' | None), reason (str | None).
    Never raises: a failed fetch returns fetched=False and a plain reason, and writes nothing.
    """
    out: Dict[str, Any] = {
        "opportunity_id": opportunity_id, "fetched": False, "description": None, "apply_url": None,
        "confirmed_close_date": None, "method": None, "reason": None,
    }
    try:
        opp = opportunity or await radar_memory.get_opportunity_by_id(opportunity_id)
        if opp is None:
            out["reason"] = "Listing not found."
            return out
        if not force and not _needs_fetch(opp.description):
            out.update(
                description=opp.description, apply_url=opp.official_application_url,
                confirmed_close_date=opp.confirmed_close_date.isoformat() if opp.confirmed_close_date else None,
                method="stored",
            )
            return out

        url = opp.official_application_url or opp.canonical_url
        page = await _fetch_page_text(url) if url else {}
        text = sanitize(page.get("text", ""))
        if len(text) < MIN_READABLE_CHARS:
            out["reason"] = "Could not read the job page right now."
            return out

        description = text[:MAX_DESCRIPTION_CHARS]
        apply_url = extract_apply_url(page.get("raw", "") or text, url)
        if apply_url:
            safe, _ = await asyncio.to_thread(is_safe_url, apply_url)
            apply_url = apply_url if safe else None
        deadline = parse_application_deadline(description)
        await _persist(opp, description, apply_url, deadline)
        out.update(
            fetched=True, description=description, apply_url=apply_url or opp.official_application_url,
            confirmed_close_date=deadline.isoformat() if deadline else None, method=page.get("method"),
        )
        return out
    except Exception as err:
        logger.warning("Listing detail fetch failed for %s: %s", opportunity_id, type(err).__name__)
        out["reason"] = "Could not read the job page right now."
        return out


def sanitize(text: str) -> str:
    """Disarm prompt-framing tags in untrusted page text before it is stored."""
    return tavily_service.sanitize_untrusted_text(text or "").strip()
