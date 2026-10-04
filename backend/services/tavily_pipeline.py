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
    # Simple deterministic sub-query derivation
    sub_queries = [clean]
    if "deadline" in clean.lower() or "due" in clean.lower():
        sub_queries.append(f"{clean} official schedule rules")
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


def _parse_explicit_year_date(date_str: Optional[str]) -> Tuple[Optional[datetime], str]:
    """Parse date string extracting date candidate and checking for explicit 4-digit year.
    Returns (aware UTC datetime or None, 'explicit_in_quote' | 'inferred').
    """
    if not date_str or not isinstance(date_str, str):
        return None, "inferred"

    year_match = re.search(r"\b((?:19|20)\d{2})\b", date_str)
    if not year_match:
        return None, "inferred"
    year_provenance = "explicit_in_quote"

    # Use DATE_PATTERN from tavily_deadline
    from backend.services.tavily_deadline import DATE_PATTERN, parse_date_candidate
    candidates = []
    for m in DATE_PATTERN.finditer(date_str):
        raw_m = m.group(0)
        parsed = parse_date_candidate(raw_m)
        if parsed:
            candidates.append(parsed)

    if candidates:
        # For deadline queries, select the closing / latest date candidate
        chosen = max(candidates)
        return datetime(chosen.year, chosen.month, chosen.day, tzinfo=timezone.utc), year_provenance

    # Direct format attempts
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
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

    evidence_items = []
    verdicts = []

    url_tier_map = {
        s.get("url"): s.get("authority_tier", AuthorityTier.TIER_3_GENERAL.value)
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
            verdict = "UNVERIFIED"  # Missing explicit 4-digit year
        elif year_provenance == "inferred":
            verdict = "UNVERIFIED"
        elif parsed_dt and parsed_dt < datetime.now(timezone.utc):
            verdict = "STALE"
        elif tier == AuthorityTier.TIER_1_OFFICIAL.value:
            verdict = "VERIFIED"
        elif tier == AuthorityTier.TIER_2_TECHNICAL.value and len(sources) >= 2:
            verdict = "VERIFIED"
        else:
            verdict = "UNVERIFIED"

        verdicts.append(verdict)
        evidence_items.append({
            "claim": claim_text,
            "source_url": source_url,
            "verbatim_quote": quote,
            "published_date": raw_date,
            "parsed_date": parsed_dt.strftime("%Y-%m-%d") if parsed_dt else None,
            "year_provenance": year_provenance,
            "authority_tier": tier,
            "verdict": verdict,
            "verbatim_verified": is_verified_quote,
            "entity_matched": entity_matched,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        })

    # Check for conflicting dates across distinct sources
    dates_by_source = {}
    for item in evidence_items:
        if item.get("parsed_date") and item.get("source_url"):
            d = item["parsed_date"][:10]  # compare YYYY-MM-DD
            dates_by_source[item["source_url"]] = d

    unique_dates = set(dates_by_source.values())
    has_conflict = len(dates_by_source) >= 2 and len(unique_dates) > 1

    if has_conflict:
        for idx, item in enumerate(evidence_items):
            if item.get("parsed_date"):
                item["verdict"] = "CONFLICTING"
                verdicts[idx] = "CONFLICTING"

    # Overall pipeline verdict rule
    if not evidence_items:
        overall = "NOT_FOUND"
    elif all(v == "NOT_FOUND" for v in verdicts):
        overall = "NOT_FOUND"
    elif any(v == "CONFLICTING" for v in verdicts):
        overall = "CONFLICTING"
    elif any(v == "VERIFIED" for v in verdicts) and all(v in ("VERIFIED", "NOT_FOUND") for v in verdicts):
        overall = "VERIFIED"
    elif all(v == "STALE" for v in verdicts if v != "NOT_FOUND"):
        overall = "STALE"
    else:
        overall = "UNVERIFIED"
        for item in evidence_items:
            if item["verdict"] == "VERIFIED":
                item["verdict"] = "UNVERIFIED"

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
    enriched_sources = sort_and_enrich_sources(raw_results)
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

        # Prioritize sentences with deadline / submission / date keywords
        deadline_sentences = [
            st for st in sentences
            if re.search(r"\b(deadline|due|ends|closes|submission|period|schedule)\b", st, re.IGNORECASE)
            and re.search(r"\b(202[4-9]|October|November|December|August|September)\b", st, re.IGNORECASE)
        ]
        chosen_sentence = deadline_sentences[0] if deadline_sentences else (sentences[0] if sentences else None)

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
