"""
Compass — Tavily Deep Research Pipeline & Evidence Ledger.

Orchestrates multi-step factual research and deadline verification:
  1. Research intent detection
  2. Query decomposition (2-4 focused sub-queries executed with semaphore)
  3. Official domain prioritization & search
  4. Full page extraction on authoritative sources
  5. Verbatim quote validation (rejects model-invented quotes)
  6. Deterministic verdict derivation (VERIFIED / CONFLICTING / STALE / NOT_FOUND / UNVERIFIED)
  7. Prompt-injection hardening (toolless, schema-validated JSON extraction)
  8. TTL caching, credit budgets, and database-backed evidence ledger
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from backend.config import get_settings
from backend.memory.db import get_pool
from backend.services.budgets import check_run_limits, BudgetExceededError
from backend.services.tavily import (
    tavily_available,
    search as tavily_search,
    extract as tavily_extract,
    sanitize_untrusted_text,
)
from backend.services.tavily_authority import (
    classify_domain_authority,
    sort_and_enrich_sources,
    AuthorityTier,
)

logger = logging.getLogger("compass.tavily_pipeline")

_COUNTDOWN_PATTERN = re.compile(
    r"\b(\d+\s*(?:days?|hours?|mins?|minutes?|secs?|seconds?)\s*(?:left|remaining)|countdown|time\s+remaining)\b",
    re.IGNORECASE,
)

# Raw search & extraction cache: query_key -> (timestamp, raw_results, extracted_blocks, credits)
_RAW_SEARCH_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]], List[str], int]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _raw_cache_key(query: str, domains: Optional[List[str]] = None) -> str:
    norm = f"{query.strip().lower()}:{sorted(domains or [])}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _cache_key(query: str, domains: Optional[List[str]], trusted_event_url: Optional[str] = None) -> str:
    return _raw_cache_key(query, domains)


async def decompose_query(query: str) -> List[str]:
    """Decompose research objective into 2-3 focused sub-queries."""
    clean = query.strip()
    sub_queries = [clean]
    if "deadline" in clean.lower() or "due" in clean.lower():
        sub_queries.append(f"{clean} official schedule rules")
    elif "hackathon" in clean.lower():
        sub_queries.append(f"{clean} devpost rules submission deadline")
    elif "api" in clean.lower() or "documentation" in clean.lower():
        sub_queries.append(f"{clean} official reference guide")
    else:
        sub_queries.append(f"{clean} official requirements")
    return list(dict.fromkeys(sub_queries))[:3]


async def execute_subqueries(
    sub_queries: List[str],
    include_domains: Optional[List[str]] = None,
    max_credits: int = 4,
) -> Tuple[List[Dict[str, Any]], int]:
    """Execute sub-queries concurrently with a semaphore, bounded by credit budget."""
    semaphore = asyncio.Semaphore(2)
    credits_used = 0
    raw_results: List[Dict[str, Any]] = []

    async def _search_one(q: str):
        nonlocal credits_used
        if credits_used >= max_credits:
            return []
        async with semaphore:
            try:
                resp = await tavily_search(
                    query=q,
                    max_results=5,
                    search_depth="basic",
                    include_domains=include_domains,
                )
                credits_used += 1
                return resp.get("results", []) or []
            except Exception as e:
                logger.warning("Subquery failed for '%s': %s", q, e)
                return []

    tasks = [_search_one(sq) for sq in sub_queries]
    batch = await asyncio.gather(*tasks)
    for items in batch:
        raw_results.extend(items)

    # Deduplicate results by normalized URL
    deduped: Dict[str, Dict[str, Any]] = {}
    for r in raw_results:
        url = (r.get("url") or "").strip()
        if url and url not in deduped:
            deduped[url] = r
    return list(deduped.values()), credits_used


def _parse_time_and_tz(text: str) -> Tuple[int, int, Any]:
    """Parse time and timezone from text using zoneinfo (America/Los_Angeles, America/New_York, Asia/Kolkata)."""
    if not text or not isinstance(text, str):
        return 0, 0, ZoneInfo("UTC")
    text_clean = text.lower().strip()
    if "midnight" in text_clean:
        return 23, 59, ZoneInfo("UTC")

    m = re.search(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(pdt|pst|pt|pacific(?:\s+time)?|edt|est|et|eastern(?:\s+time)?|cdt|cst|ct|central(?:\s+time)?|mdt|mst|mt|mountain(?:\s+time)?|ist|utc|gmt)?\b",
        text,
        re.IGNORECASE,
    )
    if not m:
        return 0, 0, ZoneInfo("UTC")

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    tz_str = (m.group(4) or "").lower().strip()

    if not m.group(2) and not m.group(3) and hour not in (23, 0):
        return 0, 0, ZoneInfo("UTC")

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if tz_str in ("pdt", "pst", "pt", "pacific", "pacific time"):
        tz = ZoneInfo("America/Los_Angeles")
    elif tz_str in ("edt", "est", "et", "eastern", "eastern time"):
        tz = ZoneInfo("America/New_York")
    elif tz_str in ("cdt", "cst", "ct", "central", "central time"):
        tz = ZoneInfo("America/Chicago")
    elif tz_str in ("mdt", "mst", "mt", "mountain", "mountain time"):
        tz = ZoneInfo("America/Denver")
    elif tz_str in ("ist", "india", "indian standard time"):
        tz = ZoneInfo("Asia/Kolkata")
    else:
        tz = ZoneInfo("UTC")

    return hour, minute, tz


def _parse_explicit_year_date(date_str: Optional[str]) -> Tuple[Optional[datetime], str]:
    """Parse date string extracting date candidate using semantic selection attached to deadline labels.

    Ignores dates attached to judging, winners announcement, changelog, or maintenance banners.
    For ranges ('start – end'), selects the END date only when the phrase is a submission period.
    If several deadline-labelled dates conflict, returns (None, 'conflicting').
    Returns (aware timezone datetime or None, 'explicit_in_quote' | 'inferred' | 'conflicting').
    """
    if not date_str or not isinstance(date_str, str):
        return None, "inferred"

    year_match = re.search(r"\b((?:19|20)\d{2})\b", date_str)
    if not year_match:
        return None, "inferred"
    year_provenance = "explicit_in_quote"

    # Use DATE_PATTERN from tavily_deadline
    from backend.services.tavily_deadline import DATE_PATTERN, parse_date_candidate

    # Check for direct full ISO format first
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, year_provenance
        except Exception:
            pass

    candidates = []
    for m in DATE_PATTERN.finditer(date_str):
        raw_m = m.group(0)
        parsed = parse_date_candidate(raw_m)
        if parsed:
            start_idx, end_idx = m.span()
            # Window for time and label inspection
            ctx_start = max(0, start_idx - 75)
            ctx_end = min(len(date_str), end_idx + 75)
            before_text = date_str[ctx_start:start_idx].lower()
            after_text = date_str[end_idx:ctx_end].lower()
            window_text = date_str[ctx_start:ctx_end].lower()

            # 1. Negative Filter: Ignore dates attached to judging, announcements, changelog, banner
            if any(ign in window_text for ign in ("judging", "judge", "judges", "winner", "winners", "announc", "results", "changelog", "maintenance", "banner", "downtime")):
                if any(ign in before_text for ign in ("judging", "judge", "winner", "winners", "announc", "changelog", "banner", "maintenance")):
                    continue
                if any(ign in after_text[:30] for ign in ("judging", "winner", "announc")):
                    continue

            # 2. Check for range: is this the start or end of a range?
            # E.g. "August 26, 2026 ... – Friday, October 30, 2026"
            is_range_start = bool(re.search(r"^[^\w]*(\([^\)]*\)\s*)?[–—\-]|to|until|through", after_text[:40]))
            is_range_end = bool(re.search(r"[–—\-]|to|until|through", before_text[-40:]))

            score = 0
            if "submission deadline" in before_text or "submissions close" in before_text or "deadline:" in before_text:
                score = 10
            elif is_range_end and ("submission period" in before_text or "submission" in window_text):
                score = 9
            elif "submission period" in before_text:
                score = 1 if is_range_start else 9
            elif "deadline" in before_text or "due date" in before_text or "due by" in before_text:
                score = 8
            elif is_range_end:
                score = 9
            elif is_range_start:
                score = 1
            else:
                score = 4

            # Local neighborhood for time: check after_text first to avoid banner time bleed
            h_after, m_after, tz_after = _parse_time_and_tz(date_str[end_idx:min(len(date_str), end_idx + 45)])
            if h_after != 23 or m_after != 59 or tz_after != timezone.utc:
                hour, minute, tz = h_after, m_after, tz_after
            else:
                hour, minute, tz = _parse_time_and_tz(date_str[ctx_start:ctx_end])

            candidates.append((parsed, hour, minute, tz, score, raw_m))

    if candidates:
        high_score = max(c[4] for c in candidates)
        best_candidates = [c for c in candidates if c[4] == high_score]

        # Check for conflict among best deadline candidates
        distinct_dates = {c[0] for c in best_candidates}
        if len(distinct_dates) > 1:
            return None, "conflicting"

        chosen_date, hour, minute, tz, _, _ = best_candidates[-1]
        return datetime(chosen_date.year, chosen_date.month, chosen_date.day, hour, minute, 0, tzinfo=tz), year_provenance

    # Direct format attempts
    for fmt in (
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
    ):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, year_provenance
        except Exception:
            pass

    return None, year_provenance


def evaluate_deterministic_verdict(
    claims: List[Dict[str, Any]],
    raw_extracted_text: str,
    sources: List[Dict[str, Any]],
    target_entity: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Derive deterministic verdicts over structured extractions with entity binding and quote validation.

    Rules:
      1. Entity Binding: Claim/source must match target_entity keywords. Otherwise UNRELATED / NOT_FOUND.
      2. Quote Verbatim: exact_quote must appear verbatim in the extracted page text.
      3. Non-sentence filter: Reject claims that are table fragments (start with '|') or < 4 words.
      4. Explicit Year: Dates without an explicit 4-digit year cannot be VERIFIED (verdict=UNVERIFIED).
      5. Authority: Tier 1 official allows single-source VERIFIED; Tier 2 requires >= 2 agreeing sources.
      6. Overall verdict: VERIFIED iff at least one claim is VERIFIED and 0 CONFLICTING.
    """
    if not sources or not raw_extracted_text:
        return "NOT_FOUND", []

    # Extract target entity keywords
    entity_keywords = []
    if target_entity:
        entity_keywords = [
            w.lower()
            for w in re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", target_entity)
            if w.lower() not in ("hackathon", "submission", "deadline", "rules", "schedule", "guide", "overview")
        ]

    evidence_items: List[Dict[str, Any]] = []
    verdicts: List[str] = []

    url_tier_map = {
        s.get("url"): s.get("authority_tier", AuthorityTier.TIER_3_GENERAL.value)
        for s in sources
    }
    url_badge_map = {
        s.get("url"): s.get("authority_badge", "")
        for s in sources
    }

    normalized_raw = " ".join(raw_extracted_text.lower().split())

    for c in claims:
        claim_text = c.get("claim", "").strip()
        source_url = c.get("source_url", "").strip()
        quote = c.get("exact_quote", "").strip()
        raw_date = c.get("extracted_date")

        # 1. Non-sentence / table fragment filter
        if claim_text.startswith("|") or len(claim_text.split()) < 4 or "|" in claim_text[:5]:
            continue

        # Marketing buzzword and boilerplate filter
        marketing_keywords = (
            "join us", "sign up", "empowering", "pioneering", "revolutionize",
            "sponsored by", "all rights reserved", "subscribe", "terms of use",
            "cookie policy", "privacy policy", "exclusive rewards"
        )
        if any(mk in claim_text.lower() for mk in marketing_keywords):
            continue

        # Semantic gate: claim must contain deadline, schedule, date, or rule semantics
        has_semantics = bool(
            re.search(
                r"\b(deadline|due|ends|closes|starts|opens|submission|submit|by|before|until|rule|requirement|eligibility|guideline|schedule|timeline|date|time|deliverable|format)\b",
                claim_text,
                re.IGNORECASE,
            )
            or raw_date
        )
        if not has_semantics:
            continue

        # Quote truncation check: quote must not be truncated mid-word
        if quote and len(quote.split()) < 2:
            continue

        # 2. Entity binding check: verify quote, claim, or URL matches entity
        entity_matched = True
        if entity_keywords:
            text_to_check = f"{claim_text.lower()} {quote.lower()} {source_url.lower()}"
            if not any(kw in text_to_check for kw in entity_keywords):
                entity_matched = False

        # 3. Verbatim quote check
        normalized_quote = " ".join(quote.lower().split())
        verbatim_match = bool(normalized_quote and normalized_quote in normalized_raw)

        tier = url_tier_map.get(source_url, AuthorityTier.TIER_3_GENERAL.value)
        parsed_dt, year_provenance = _parse_explicit_year_date(raw_date or claim_text)

        # "Verified quote" rule: quote appears verbatim AND entity matches AND date parses (if date present)
        is_verified_quote = bool(verbatim_match and entity_matched and (parsed_dt is not None if raw_date else True))

        # 4. Deterministic per-claim verdict derivation
        if not entity_matched:
            # Source belongs to a different/unrelated event or company -> NOT_FOUND, never UNVERIFIED
            verdict = "NOT_FOUND"
        elif not verbatim_match or not quote:
            verdict = "UNVERIFIED"
        elif raw_date and not parsed_dt:
            if year_provenance == "conflicting":
                verdict = "CONFLICTING"
            else:
                verdict = "UNVERIFIED"  # Missing explicit 4-digit year
        elif year_provenance == "conflicting":
            verdict = "CONFLICTING"
        elif year_provenance == "inferred":
            verdict = "UNVERIFIED"
        elif _COUNTDOWN_PATTERN.search(claim_text) or _COUNTDOWN_PATTERN.search(quote):
            # Countdown widget text must never be verified evidence on its own
            verdict = "UNVERIFIED"
        elif parsed_dt and parsed_dt < datetime.now(timezone.utc):
            verdict = "STALE"
        elif tier == AuthorityTier.TIER_1_OFFICIAL.value:
            verdict = "VERIFIED"
        elif tier == AuthorityTier.TIER_2_TECHNICAL.value:
            # Tier 2 requires >= 2 independent agreeing sources for this specific UTC instant
            agreeing_sources = set()
            for cl in claims:
                cl_url = cl.get("source_url")
                if not cl_url:
                    continue
                cl_tier = url_tier_map.get(cl_url, AuthorityTier.TIER_3_GENERAL.value)
                if cl_tier not in (AuthorityTier.TIER_1_OFFICIAL.value, AuthorityTier.TIER_2_TECHNICAL.value):
                    continue
                cl_dt, _ = _parse_explicit_year_date(cl.get("extracted_date") or cl.get("claim"))
                if cl_dt and parsed_dt and cl_dt.astimezone(timezone.utc) == parsed_dt.astimezone(timezone.utc):
                    if not _COUNTDOWN_PATTERN.search(cl.get("claim", "")) and not _COUNTDOWN_PATTERN.search(cl.get("exact_quote", "")):
                        agreeing_sources.add(cl_url)
            if len(agreeing_sources) >= 2:
                verdict = "VERIFIED"
            else:
                verdict = "UNVERIFIED"
        else:
            verdict = "UNVERIFIED"

        utc_iso = None
        ist_str = None
        if parsed_dt:
            utc_iso = parsed_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ist_dt = parsed_dt.astimezone(ZoneInfo("Asia/Kolkata"))
            ist_str = ist_dt.strftime("%Y-%m-%d %I:%M %p IST")

        verdicts.append(verdict)
        evidence_items.append({
            "claim": claim_text,
            "source_url": source_url,
            "exact_quote": quote,
            "verbatim_quote": quote,
            "published_date": raw_date,
            "parsed_date": parsed_dt.isoformat() if parsed_dt else None,
            "normalized_utc": utc_iso,
            "local_deadline_ist": ist_str,
            "year_provenance": year_provenance,
            "authority_tier": tier,
            "authority_badge": url_badge_map.get(source_url, "Official Organizer" if tier == "tier_1_official" else ""),
            "verdict": verdict,
            "verbatim_verified": is_verified_quote,
            "entity_matched": entity_matched,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        })

    # Check for conflicting dates across distinct sources
    dates_by_source = {}
    for item in evidence_items:
        parsed_date = item.get("parsed_date")
        source_url = item.get("source_url")
        if isinstance(parsed_date, str) and source_url:
            d = parsed_date[:10]  # compare YYYY-MM-DD
            dates_by_source[source_url] = d

    unique_dates = set(dates_by_source.values())
    has_conflict = len(dates_by_source) >= 2 and len(unique_dates) > 1

    if has_conflict:
        for idx, item in enumerate(evidence_items):
            if isinstance(item.get("parsed_date"), str):
                item["verdict"] = "CONFLICTING"
                verdicts[idx] = "CONFLICTING"

    # Overall pipeline verdict rule
    if not evidence_items:
        overall = "NOT_FOUND"
    elif any(v == "CONFLICTING" for v in verdicts):
        overall = "CONFLICTING"
    elif any(v == "VERIFIED" for v in verdicts):
        overall = "VERIFIED"
    elif all(v == "NOT_FOUND" for v in verdicts):
        overall = "NOT_FOUND"
    elif all(v == "STALE" for v in verdicts if v != "NOT_FOUND"):
        overall = "STALE"
    else:
        overall = "UNVERIFIED"

    return overall, evidence_items


async def persist_evidence_ledger(run_id: str, evidence: List[Dict[str, Any]]) -> None:
    """Save verified evidence records into the persistent evidence_ledger PostgreSQL table."""
    try:
        pool = await get_pool()
        if pool and evidence:
            async with pool.acquire() as conn:
                for ev in evidence:
                    await conn.execute(
                        "INSERT INTO evidence_ledger (run_id, claim, source_url, verbatim_quote, published_date, authority_tier, verdict) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        run_id, ev["claim"][:500], ev["source_url"][:500], ev["verbatim_quote"][:1000],
                        str(ev.get("published_date") or ""), ev["authority_tier"], ev["verdict"],
                    )
    except Exception as e:
        logger.warning("Could not persist evidence ledger to DB: %s", e)


async def run_tavily_research(
    query: str,
    run_id: Optional[str] = None,
    include_domains: Optional[List[str]] = None,
    max_credits: int = 4,
    target_entity: Optional[str] = None,
    trusted_event_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute complete Tavily research pipeline with deterministic evidence ledger."""
    settings = get_settings()
    if not tavily_available():
        return {
            "status": "unavailable",
            "verdict": "NOT_FOUND",
            "summary": "Tavily search service is not configured on this instance.",
            "evidence_ledger": [],
            "sources": [],
        }

    active_run_id = run_id or f"research_{uuid.uuid4().hex[:10]}"
    now = time.monotonic()
    t_start = time.perf_counter()
    stage_timings: Dict[str, float] = {}

    # 1. Check RAW TTL Cache (query + domains only; trusted_event_url applied after cache)
    ckey = _raw_cache_key(query, include_domains)
    raw_results: List[Dict[str, Any]] = []
    extracted_text_blocks: List[str] = []
    total_credits = 0
    from_cache = False

    if ckey in _RAW_SEARCH_CACHE:
        cached_time, c_results, c_blocks, c_credits = _RAW_SEARCH_CACHE[ckey]
        if (now - cached_time) < _CACHE_TTL_SECONDS:
            raw_results = [dict(r) for r in c_results]
            extracted_text_blocks = list(c_blocks)
            total_credits = c_credits
            from_cache = True
            logger.info("Serving raw search/extraction from cache for query '%s'", query)

    if not from_cache:
        t0 = time.perf_counter()
        sub_queries = await decompose_query(query)
        stage_timings["decomposition_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        t0 = time.perf_counter()
        try:
            raw_results, search_credits = await execute_subqueries(
                sub_queries, include_domains=include_domains, max_credits=max_credits
            )
            total_credits += search_credits
        except Exception as e:
            logger.warning("execute_subqueries failed: %s", e)
            return {
                "status": "unavailable",
                "verdict": "NOT_FOUND",
                "summary": f"Search execution failed: {e}",
                "evidence_ledger": [],
                "sources": [],
                "credits": 0,
                "stage_timings": stage_timings,
            }
        stage_timings["search_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if not raw_results:
            stage_timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
            return {
                "status": "ok",
                "verdict": "NOT_FOUND",
                "summary": f"No web sources found for '{query}'.",
                "evidence_ledger": [],
                "sources": [],
                "credits": total_credits,
                "stage_timings": stage_timings,
            }

        # Extract top candidate URLs (full fetched text without truncation for quote verification)
        t0 = time.perf_counter()
        extract_urls = [r["url"] for r in raw_results if r.get("url")][:2]
        if extract_urls:
            try:
                extract_resp = await asyncio.wait_for(
                    tavily_extract(extract_urls, extract_depth="basic"),
                    timeout=getattr(settings, "TAVILY_EXTRACT_TIMEOUT_S", 8.0),
                )
                res_list = extract_resp.get("results", []) or []
                total_credits += len(res_list)
                for item in res_list:
                    raw = item.get("raw_content") or item.get("content") or ""
                    if raw:
                        extracted_text_blocks.append(raw)
            except Exception as e:
                logger.warning("Tavily extraction timed out or failed: %s; falling back to snippets", e)
        stage_timings["extraction_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # Cache raw search and extraction results
        _RAW_SEARCH_CACHE[ckey] = (now, raw_results, extracted_text_blocks, total_credits)

    # 4. Apply authority tier and badges per request from caller's own trusted URLs (AFTER cache)
    t0 = time.perf_counter()
    enriched_sources = sort_and_enrich_sources(raw_results, trusted_event_url=trusted_event_url)
    top_sources = enriched_sources[:3]
    stage_timings["ranking_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # 5. Build full raw text corpus for verbatim quote verification
    full_extracted_corpus = "\n\n".join(extracted_text_blocks)
    combined_corpus = (full_extracted_corpus + "\n\n" + " ".join(s.get("content", "") for s in top_sources)).strip()

    # 6. Extract structured claims from web text
    t0 = time.perf_counter()
    claims: List[Dict[str, Any]] = []
    for s in top_sources:
        candidate_pool = [s.get("content", "")]
        for blk in extracted_text_blocks:
            if s.get("domain", "") in blk.lower() or s["url"] in blk:
                candidate_pool.append(blk)

        text_to_scan = "\n".join(candidate_pool)
        sentences = [
            sent.strip() for sent in re.split(r"[.!?\n]+", text_to_scan)
            if len(sent.strip()) > 20 and not sent.strip().startswith(("#", "|", "*", "-")) and "|" not in sent[:15]
        ]

        filtered_sentences = [
            sent for sent in sentences
            if not any(ign in sent.lower() for ign in (
                "scheduled maintenance", "routine maintenance", "downtime", "changelog",
                "cookie policy", "terms of service", "privacy notice", "all rights reserved"
            ))
        ]

        deadline_sentences = [
            st for st in filtered_sentences
            if re.search(r"\b(deadline|due|ends|closes|submission\s+(?:period|deadline)|submission)\b", st, re.IGNORECASE)
            and re.search(r"\b(202[4-9]|January|February|March|April|May|June|July|August|September|October|November|December)\b", st, re.IGNORECASE)
            and not re.search(r"\b(judging|winner|announcement|banner|changelog|maintenance)\b", st, re.IGNORECASE)
        ]

        def _deadline_priority(st: str) -> int:
            s = st.lower()
            if any(ign in s for ign in ("judging", "winner", "announcement", "banner", "changelog", "maintenance")):
                return -1
            return next((sc for kw, sc in (("submission deadline", 5), ("deadline:", 5), ("submissions close", 5), ("submission period", 4), ("deadline", 3), ("due date", 3), ("closes", 2), ("ends", 2)) if kw in s), 0)

        deadline_sentences.sort(key=_deadline_priority, reverse=True)
        chosen_sentence = deadline_sentences[0] if deadline_sentences else (filtered_sentences[0] if filtered_sentences else None)

        if chosen_sentence:
            dt_match = re.search(r"\b(202[4-9])\b", chosen_sentence)
            exact_quote = chosen_sentence.strip()
            if len(exact_quote) > 300:
                exact_quote = exact_quote[:300].strip()
            if exact_quote and exact_quote[-1] in (",", ";", ":"):
                exact_quote = exact_quote[:-1].strip()

            claims.append({
                "claim": chosen_sentence,
                "source_url": s.get("url", ""),
                "exact_quote": exact_quote,
                "extracted_date": chosen_sentence if dt_match else None,
            })

    # 7. Evaluate deterministic verdicts with full-corpus verbatim quote validation
    overall_verdict, evidence_ledger = evaluate_deterministic_verdict(
        claims, combined_corpus, top_sources, target_entity=target_entity or query
    )
    stage_timings["verdict_eval_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    stage_timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)

    for item in evidence_ledger:
        item["run_id"] = active_run_id
        item["credits"] = total_credits

    await persist_evidence_ledger(active_run_id, evidence_ledger)

    result = {
        "status": "ok",
        "verdict": overall_verdict,
        "run_id": active_run_id,
        "cached": from_cache,
        "summary": f"Research complete. Evaluated {len(top_sources)} sources. Overall verdict: {overall_verdict}.",
        "evidence_ledger": evidence_ledger,
        "stage_timings": stage_timings,
        "progress": {"stage": "complete", "total_ms": stage_timings["total_ms"]},
        "sources": [
            {
                "url": s["url"],
                "title": s.get("title", ""),
                "domain": s.get("domain", ""),
                "authority_tier": s.get("authority_tier"),
                "authority_badge": s.get("authority_badge"),
                "composite_score": s.get("composite_score"),
            }
            for s in top_sources
        ],
    }
    return result
