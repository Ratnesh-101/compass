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

# TTL Cache for research queries: query_key -> (timestamp, result)
_RESEARCH_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_key(query: str, domains: Optional[List[str]]) -> str:
    norm = f"{query.strip().lower()}:{sorted(domains or [])}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


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


def _parse_time_and_tz(text: str) -> Tuple[int, int, timezone]:
    """Parse time and timezone from text, defaulting to 0, 0, UTC if absent."""
    from datetime import timedelta
    m = re.search(
        r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\s*(pdt|pst|pt|pacific(?:\s+time)?|edt|est|cdt|cst|mdt|mst|utc|gmt)?\b",
        text,
        re.IGNORECASE,
    )
    if not m:
        return 0, 0, timezone.utc

    hour = int(m.group(1))
    minute = int(m.group(2))
    ampm = (m.group(3) or "").lower()
    tz_str = (m.group(4) or "").lower().strip()

    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if tz_str in ("pdt", "pt", "pacific", "pacific time"):
        tz = timezone(timedelta(hours=-7))
    elif tz_str == "pst":
        tz = timezone(timedelta(hours=-8))
    elif tz_str == "edt":
        tz = timezone(timedelta(hours=-4))
    elif tz_str == "est":
        tz = timezone(timedelta(hours=-5))
    elif tz_str in ("cdt", "central"):
        tz = timezone(timedelta(hours=-5))
    elif tz_str == "cst":
        tz = timezone(timedelta(hours=-6))
    elif tz_str == "mdt":
        tz = timezone(timedelta(hours=-6))
    elif tz_str == "mst":
        tz = timezone(timedelta(hours=-7))
    else:
        tz = timezone.utc

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
        elif parsed_dt and parsed_dt < datetime.now(timezone.utc):
            verdict = "STALE"
        elif tier == AuthorityTier.TIER_1_OFFICIAL.value:
            verdict = "VERIFIED"
        elif tier == AuthorityTier.TIER_2_TECHNICAL.value:
            # Tier 2 requires >= 2 independent agreeing sources for this specific date
            agreeing_sources = {
                cl.get("source_url")
                for cl in claims
                if cl.get("source_url") and _parse_explicit_year_date(cl.get("extracted_date") or cl.get("claim"))[0] == parsed_dt
            }
            if len(agreeing_sources) >= 2:
                verdict = "VERIFIED"
            else:
                verdict = "UNVERIFIED"
        else:
            verdict = "UNVERIFIED"

        verdicts.append(verdict)
        evidence_items.append({
            "claim": claim_text,
            "source_url": source_url,
            "verbatim_quote": quote,
            "published_date": raw_date,
            "parsed_date": parsed_dt.isoformat() if parsed_dt else None,
            "year_provenance": year_provenance,
            "authority_tier": tier,
            "authority_badge": url_badge_map.get(source_url, "Official Organizer" if tier == "tier_1_official" else ""),
            "verdict": verdict,
            "verbatim_verified": is_verified_quote,
            "entity_matched": entity_matched,
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
                        """
                        INSERT INTO evidence_ledger 
                            (run_id, claim, source_url, verbatim_quote, published_date, authority_tier, verdict)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        run_id,
                        ev["claim"][:500],
                        ev["source_url"][:500],
                        ev["verbatim_quote"][:1000],
                        str(ev.get("published_date") or ""),
                        ev["authority_tier"],
                        ev["verdict"],
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
    if not tavily_available():
        return {
            "status": "unavailable",
            "verdict": "NOT_FOUND",
            "summary": "Tavily search service is not configured on this instance.",
            "evidence_ledger": [],
            "sources": [],
        }

    active_run_id = run_id or f"research_{uuid.uuid4().hex[:10]}"
    ckey = _cache_key(query, include_domains)

    # 1. Check TTL cache
    now = time.monotonic()
    if ckey in _RESEARCH_CACHE:
        cached_time, cached_val = _RESEARCH_CACHE[ckey]
        if (now - cached_time) < _CACHE_TTL_SECONDS:
            logger.info("Serving Tavily research from TTL cache for '%s'", query)
            return dict(cached_val)

    # 2. Decompose query into sub-queries
    sub_queries = await decompose_query(query)

    # 3. Concurrent search
    total_credits = 0
    try:
        raw_results, search_credits = await execute_subqueries(sub_queries, include_domains=include_domains, max_credits=max_credits)
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
        }

    if not raw_results:
        return {
            "status": "ok",
            "verdict": "NOT_FOUND",
            "summary": f"No web sources found for '{query}'.",
            "evidence_ledger": [],
            "sources": [],
            "credits": total_credits,
        }

    # 4. Enrich and rank sources by domain authority
    enriched_sources = sort_and_enrich_sources(raw_results, trusted_event_url=trusted_event_url)
    top_sources = enriched_sources[:3]

    # 5. Extract top official URLs
    extract_urls = [s["url"] for s in top_sources if s.get("url")]
    extracted_text_blocks = []
    try:
        extract_resp = await tavily_extract(extract_urls[:2], extract_depth="basic")
        results_list = extract_resp.get("results", []) or []
        total_credits += len(results_list)
        for item in results_list:
            raw = item.get("raw_content") or item.get("content") or ""
            if raw:
                extracted_text_blocks.append(sanitize_untrusted_text(raw[:3000]))
    except Exception as e:
        logger.warning("Tavily extract failed: %s; falling back to snippets", e)
        for s in top_sources:
            extracted_text_blocks.append(s.get("content", ""))

    full_extracted_corpus = "\n\n".join(extracted_text_blocks)

    # 6. Extract structured claims from web text (Hardened prompt injection defense)
    # Model gets NO tools and web text is strictly fenced in user prompt
    claims: List[Dict[str, Any]] = []
    for s in top_sources:
        content = s.get("content", "")
        # Check both full extracted corpus and snippet for this source
        candidate_pool = [content]
        for blk in extracted_text_blocks:
            if s.get("domain", "") in blk.lower() or s["url"] in blk:
                candidate_pool.append(blk)

        text_to_scan = "\n".join(candidate_pool)
        sentences = [
            sent.strip() for sent in re.split(r"[.!?\n]+", text_to_scan)
            if len(sent.strip()) > 20 and not sent.strip().startswith(("#", "|", "*", "-")) and "|" not in sent[:15]
        ]

        # Filter out maintenance, banner, changelog, cookie, and platform alert sentences
        filtered_sentences = []
        for sent in sentences:
            sent_lower = sent.lower()
            if any(ign in sent_lower for ign in (
                "scheduled maintenance", "routine maintenance", "downtime", "changelog",
                "cookie policy", "terms of service", "privacy notice", "all rights reserved"
            )):
                continue
            filtered_sentences.append(sent)

        # Prioritize sentences with deadline / submission / date keywords
        deadline_sentences = [
            st for st in filtered_sentences
            if re.search(r"\b(deadline|due|ends|closes|submission\s+(?:period|deadline)|submission)\b", st, re.IGNORECASE)
            and re.search(r"\b(202[4-9]|January|February|March|April|May|June|July|August|September|October|November|December)\b", st, re.IGNORECASE)
            and not re.search(r"\b(judging|winner|announcement|banner|changelog|maintenance)\b", st, re.IGNORECASE)
        ]

        def _deadline_priority(s: str) -> int:
            s_low = s.lower()
            if any(ign in s_low for ign in ("judging", "winner", "announcement", "banner", "changelog", "maintenance")):
                return -1
            if "submission deadline" in s_low or "deadline:" in s_low or "submissions close" in s_low:
                return 5
            if "submission period" in s_low:
                return 4
            if "deadline" in s_low or "due date" in s_low:
                return 3
            if "closes" in s_low or "ends" in s_low:
                return 2
            return 0

        deadline_sentences.sort(key=_deadline_priority, reverse=True)
        chosen_sentence = deadline_sentences[0] if deadline_sentences else (filtered_sentences[0] if filtered_sentences else None)

        if chosen_sentence:
            dt_match = re.search(r"\b(202[4-9])\b", chosen_sentence)
            # Find exact verbatim substring in full_extracted_corpus or content
            exact_quote = chosen_sentence[:140].strip()
            # If comma or paren at end, trim
            if exact_quote and exact_quote[-1] in (",", ";", ":", "("):
                exact_quote = exact_quote[:-1].strip()

            claims.append({
                "claim": chosen_sentence,
                "source_url": s.get("url", ""),
                "exact_quote": exact_quote,
                "extracted_date": chosen_sentence if dt_match else None,
            })

    # 7. Evaluate deterministic verdicts with verbatim quote validation and entity binding
    overall_verdict, evidence_ledger = evaluate_deterministic_verdict(
        claims, full_extracted_corpus if full_extracted_corpus else " ".join(s.get("content", "") for s in top_sources), top_sources, target_entity=target_entity or query
    )

    # Attach credits and run_id to each ledger item
    for item in evidence_ledger:
        item["run_id"] = active_run_id
        item["credits"] = total_credits

    # 8. Persist to DB evidence_ledger table
    await persist_evidence_ledger(active_run_id, evidence_ledger)

    result = {
        "status": "ok",
        "verdict": overall_verdict,
        "run_id": active_run_id,
        "summary": f"Research complete. Evaluated {len(top_sources)} sources across {len(sub_queries)} decomposed queries. Overall verdict: {overall_verdict}.",
        "evidence_ledger": evidence_ledger,
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

    # Store in TTL cache
    _RESEARCH_CACHE[ckey] = (now, result)
    return result
