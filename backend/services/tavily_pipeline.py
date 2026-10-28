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
from fastapi import HTTPException

from backend.services import budget_context
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

# Raw search & extraction cache: query_key -> (timestamp, raw_results, url_to_raw_content, credits)
_RAW_SEARCH_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]], Any, int]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def format_display_quote(text: str) -> str:
    """Insert missing spaces between joined words (e.g. 'deadlineFriday' -> 'deadline Friday') for UI display."""
    if not text or not isinstance(text, str):
        return ""
    formatted = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    formatted = re.sub(r"([a-zA-Z])(202[4-9])", r"\1 \2", formatted)
    return re.sub(r"\s+", " ", formatted).strip()


def truncate_quote_cleanly(text: str, max_chars: int = 320) -> str:
    """Truncate text at sentence or word boundary with ellipsis if needed to avoid mid-word cutoff."""
    if not text or not isinstance(text, str):
        return ""
    clean = " ".join(text.split()).strip()
    if len(clean) <= max_chars:
        return clean
    # Try finding sentence boundary up to max_chars
    match = list(re.finditer(r"([.!?])\s+", clean[:max_chars]))
    if match:
        end_idx = match[-1].end(1)
        if end_idx >= 60:
            return clean[:end_idx].strip()
    # Otherwise truncate at word boundary
    truncated = clean[:max_chars].rsplit(" ", 1)[0].strip()
    truncated = re.sub(r"[,;:\s]+$", "", truncated)
    return truncated + "..."


def sanitize_verification_query(query: str) -> str:
    """Strip verification intent phrasing wrapper so research queries only contain the factual topic.

    Preserves subject words like 'Tavily' or 'verification' if they are part of the
    actual factual claim itself (e.g. 'Tavily free tier credits' or 'verification deadline').
    """
    if not query:
        return ""
    q = query.strip()

    # 1. Pure instruction queries with no factual claim return empty string
    pure_instruction_patterns = [
        r"(?i)^(?:please\s+)?(?:can\s+you\s+)?(?:verify|fact[- ]?check|check)\s+(?:this|that|it|the\s+claim(?:\s+you\s+just\s+made)?)(?:\s+(?:with|using)\s+tavily)?[\s.?!]*$",
        r"(?i)^(?:please\s+)?(?:can\s+you\s+)?(?:verify|fact[- ]?check|check)(?:\s+(?:with|using)\s+tavily)?[\s.?!]*$",
    ]
    if any(re.match(pat, q) for pat in pure_instruction_patterns):
        return ""

    # 2. Strip leading instruction wrapper phrases (preserve 'verification', only strip 'verify'/'check')
    patterns_start = [
        r"(?i)^(?:please\s+)?(?:can\s+you\s+)?(?:verify|fact[- ]?check|check)\s+(?:this|that|it|the\s+claim(?:\s+you\s+just\s+made)?)(?:\s+(?:with|using)\s+tavily)?(?:\s*[:,-]\s*|\s+that\s+|\s+about\s+|\s+for\s+|\s+)",
        r"(?i)^(?:please\s+)?(?:can\s+you\s+)?(?:verify|fact[- ]?check|check)\s+(?:with\s+tavily|using\s+tavily)(?:\s*[:,-]\s*|\s+that\s+|\s+about\s+|\s+for\s+|\s+)",
        r"(?i)^(?:verify|fact[- ]?check|check)\s+this(?:\s+deadline)?\s*[:,-]?\s*",
        r"(?i)^(?:please\s+)?(?:can\s+you\s+)?\b(?:verify|fact[- ]?check|check)\b(?:\s+(?:the|a|an))?(?:\s*[:,-]|\s+)\s*",
    ]
    for pat in patterns_start:
        new_q = re.sub(pat, "", q).strip()
        if new_q != q:
            q = new_q
            break

    # 3. Strip trailing instruction phrases like "with tavily" or "using tavily"
    patterns_end = [
        r"(?i)\s+(?:with\s+tavily|using\s+tavily)\.?$",
        r"(?i)\s+(?:using\s+the\s+tavily\s+api)\.?$",
    ]
    for pat in patterns_end:
        q = re.sub(pat, "", q).strip()

    clean = " ".join(q.split()).strip(" :.-")
    return clean


PARSER_VERSION = "v2_anchor_aware"


def make_cache_key(query: str) -> str:
    norm = f"{query.strip().lower()}|{PARSER_VERSION}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _raw_cache_key(query: str, domains: Optional[List[str]] = None) -> str:
    norm = f"{query.strip().lower()}:{sorted(domains or [])}|{PARSER_VERSION}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _cache_key(query: str, domains: Optional[List[str]], trusted_event_url: Optional[str] = None) -> str:
    return _raw_cache_key(query, domains)


def check_domain_independence(url1: str, url2: str) -> bool:
    """Check if two URLs belong to distinct root domains (e.g. devpost pages share root domain)."""
    import urllib.parse
    host1 = urllib.parse.urlsplit(url1).hostname or ""
    host2 = urllib.parse.urlsplit(url2).hostname or ""

    def root_domain(h: str) -> str:
        parts = h.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else h

    return root_domain(host1) != root_domain(host2)


async def decompose_query(query: str) -> List[str]:
    """Decompose research objective into 2-3 focused sub-queries."""
    clean = sanitize_verification_query(query).strip()
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
    capped_out: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Execute sub-queries concurrently with a semaphore, bounded by credit budget.

    When a per-run / daily / global Tavily budget stops a sub-query, its message is appended
    to ``capped_out`` (if given) so the caller can report a capped search instead of "no sources".
    """
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
            except (BudgetExceededError, HTTPException) as e:
                reason = e.detail if isinstance(e, HTTPException) else str(e)
                if isinstance(reason, dict):
                    reason = reason.get("message") or reason.get("code") or "budget exceeded"
                logger.warning("Subquery capped by budget for '%s': %s", q, reason)
                if capped_out is not None:
                    capped_out.append(str(reason))
                return []
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


def _parse_time_and_tz_detail(text: str) -> Tuple[int, int, Any, bool]:
    """Parse hour, minute, ZoneInfo, and boolean indicating whether time was explicitly present."""
    if not text or not isinstance(text, str):
        return 0, 0, ZoneInfo("UTC"), False
    text_clean = text.lower().strip()
    if "midnight" in text_clean:
        return 23, 59, ZoneInfo("UTC"), True

    tz_pattern = r"(?:pdt|pst|pt|pacific(?:\s+time)?|edt|est|et|eastern(?:\s+time)?|cdt|cst|ct|central(?:\s+time)?|mdt|mst|mt|mountain(?:\s+time)?|ist|utc|gmt)"
    pattern_strict = re.compile(
        rf"\b(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)?\s*({tz_pattern})?\b",
        re.IGNORECASE,
    )
    for cand in pattern_strict.finditer(text):
        h_r, m_r, ap_r, tz_r = cand.group(1), cand.group(2), cand.group(3), cand.group(4)
        if m_r or ap_r or tz_r:
            hour = int(h_r)
            if hour <= 24:
                minute = int(m_r or 0)
                ampm = (ap_r or "").lower()
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                tz_str = (tz_r or "").lower().strip()
                tz_map = {
                    ("pdt", "pst", "pt", "pacific", "pacific time"): "America/Los_Angeles",
                    ("edt", "est", "et", "eastern", "eastern time"): "America/New_York",
                    ("cdt", "cst", "ct", "central", "central time"): "America/Chicago",
                    ("mdt", "mst", "mt", "mountain", "mountain time"): "America/Denver",
                    ("ist", "india", "indian standard time"): "Asia/Kolkata",
                }
                tz_name = next((zone for keys, zone in tz_map.items() if tz_str in keys), "UTC")
                return hour, minute, ZoneInfo(tz_name), True

    return 0, 0, ZoneInfo("UTC"), False


def _parse_time_and_tz(text: str) -> Tuple[int, int, Any]:
    """Parse time and timezone from text using zoneinfo (America/Los_Angeles, America/New_York, Asia/Kolkata)."""
    h, m, tz, _ = _parse_time_and_tz_detail(text)
    return h, m, tz


def classify_deadline_label(before_text: str, after_text: str = "", window_text: str = "") -> str:
    """Classify date candidate into a semantic deadline label based on surrounding text context."""
    comb = f"{before_text} {after_text} {window_text}".lower()

    # 1. Registration checks
    if any(k in comb for k in (
        "registration close", "registration deadline", "register by",
        "registration ends", "registration period", "registration window",
        "register before", "registration closes", "registration opens", "registration open",
        "registration"
    )):
        return "registration"

    # 2. Judging checks
    if any(k in comb for k in ("judging period", "judging begins", "judging starts", "evaluation period", "judging", "evaluation")):
        return "judging"

    # 3. Winners / announcement checks
    if any(k in comb for k in ("winners announced", "results announced", "winner announcement", "winners", "winner")):
        return "winners"

    # 4. Event start checks
    if any(k in comb for k in (
        "hackathon kickoff", "kickoff", "starts on", "begins on", "opening date", "hackathon starts", "start date",
        "event starts", "event start", "starts", "begins", "opening", "opens"
    )):
        return "event_start"

    # 5. Event end / concluding checks (when not submission)
    if any(k in comb for k in ("hackathon ends", "concludes on", "closing date", "concluding", "wrap-up", "closing ceremony", "event ends")):
        return "event_end"

    # 6. Submission deadline checks
    if any(k in comb for k in (
        "submission deadline", "submissions close", "submission period end",
        "submit by", "submissions due", "submission closes", "deadline:", "due date", "due by",
        "submissions", "submission", "deadline", "due", "closes"
    )):
        return "submission"

    return "unclassified"


def determine_claim_deadline_type(claim_text: str) -> str:
    """Determine the semantic deadline category asserted by the user's claim."""
    if not claim_text:
        return "submission"
    c_low = claim_text.lower()
    if any(k in c_low for k in ("registration", "register")):
        return "registration"
    if any(k in c_low for k in ("start", "begins", "opening", "kickoff")):
        return "event_start"
    if any(k in c_low for k in ("judging", "evaluation")):
        return "judging"
    if any(k in c_low for k in ("winner", "winners", "results")):
        return "winners"
    if any(k in c_low for k in ("event ends", "concludes", "closing ceremony")):
        return "event_end"
    return "submission"


class ExplicitDateTime(datetime):
    """DateTime subclass preserving explicit has_time metadata for exact verification."""
    has_time: bool = False


def _parse_explicit_year_date(date_str: Optional[str], default_year: Optional[int] = None) -> Tuple[Optional[datetime], str]:
    """Parse date string extracting date candidate using semantic selection attached to deadline labels.

    Ignores dates attached to judging, winners announcement, changelog, or maintenance banners.
    For ranges ('start – end'), selects the END date only when the phrase is a submission period.
    If several deadline-labelled dates conflict, returns (None, 'conflicting').
    Returns (aware timezone datetime or None, 'explicit_in_quote' | 'year_inferred' | 'inferred' | 'conflicting').
    """
    if not date_str or not isinstance(date_str, str):
        return None, "inferred"

    year_match = re.search(r"\b((?:19|20)\d{2})\b", date_str)
    year = int(year_match.group(1)) if year_match else default_year
    if not year:
        return None, "inferred"
    year_provenance = "explicit_in_quote" if year_match else "year_inferred"

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
        parsed = parse_date_candidate(raw_m, default_year=year)
        if parsed:
            start_idx, end_idx = m.span()
            # Window for time and label inspection
            ctx_start = max(0, start_idx - 75)
            ctx_end = min(len(date_str), end_idx + 75)
            before_text = date_str[ctx_start:start_idx].lower()
            after_text = date_str[end_idx:ctx_end].lower()
            window_text = date_str[ctx_start:ctx_end].lower()

            ign_words = ("judging", "judge", "winner", "winners", "announc", "results", "changelog", "maintenance", "banner", "downtime")
            if any(ign in window_text for ign in ign_words):
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
            h_after, m_after, tz_after, found_after = _parse_time_and_tz_detail(date_str[end_idx:min(len(date_str), end_idx + 60)])
            has_explicit_time = False
            if found_after:
                hour, minute, tz = h_after, m_after, tz_after
                has_explicit_time = True
            else:
                h_before, m_before, tz_before, found_before = _parse_time_and_tz_detail(date_str[ctx_start:start_idx][-45:])
                if found_before:
                    hour, minute, tz = h_before, m_before, tz_before
                    has_explicit_time = True
                else:
                    hour, minute, tz = 0, 0, timezone.utc

            candidates.append((parsed, hour, minute, tz, score, raw_m, has_explicit_time))

    if candidates:
        high_score = max(c[4] for c in candidates)
        best_candidates = [c for c in candidates if c[4] == high_score]

        # Check for conflict among best deadline candidates
        distinct_dates = {c[0] for c in best_candidates}
        if len(distinct_dates) > 1:
            return None, "conflicting"

        chosen_date, hour, minute, tz, _, _, has_explicit_time = best_candidates[-1]
        dt = ExplicitDateTime(chosen_date.year, chosen_date.month, chosen_date.day, hour, minute, 0, tzinfo=tz)
        dt.has_time = has_explicit_time
        return dt, year_provenance

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

    if default_year:
        for fmt in (
            "%B %d",
            "%b %d",
            "%d %B",
            "%d %b",
        ):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                dt = dt.replace(year=default_year)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt, year_provenance
            except Exception:
                pass

    return None, year_provenance


def parse_time_utc(date_str: str, default_year: Optional[int] = None) -> Tuple[Optional[datetime], str]:
    """Parse string to UTC datetime using semantic parsing and timezone awareness."""
    dt, prov = _parse_explicit_year_date(date_str, default_year=default_year)
    if dt:
        return dt.astimezone(ZoneInfo("UTC")), prov
    return None, prov


def evaluate_deterministic_verdict(
    claims: List[Dict[str, Any]],
    raw_extracted_text: str,
    sources: List[Dict[str, Any]],
    target_entity: Optional[str] = None,
    source_text_map: Optional[Dict[str, str]] = None,
    target_claim: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Derive deterministic verdicts over structured extractions with label-aware entity binding, same-type comparison, and quote validation."""
    if not sources or not raw_extracted_text:
        return "NOT_FOUND", []

    VERIFY_STOPWORDS = {
        "verify", "verification", "check", "factcheck", "fact",
        "please", "with", "this", "that", "claim", "hackathon", "submission",
        "deadline", "rules", "schedule", "guide", "overview", "date", "dates",
        "time", "official", "2024", "2025", "2026", "global"
    }
    entity_keywords = []
    if target_entity:
        if target_entity.strip().lower() in ("tavily", "tavily ai", "tavily search"):
            entity_keywords = ["tavily"]
        else:
            entity_keywords = [
                w.lower()
                for w in re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", target_entity)
                if w.lower() not in VERIFY_STOPWORDS
            ]

    # Semantic label of the target claim
    claim_type = determine_claim_deadline_type(target_claim or "")
    target_claim_dt = None
    target_claim_has_time = False
    if target_claim:
        target_claim_dt, _ = _parse_explicit_year_date(target_claim)
        if target_claim_dt:
            t_h, t_m, t_tz, target_claim_has_time = _parse_time_and_tz_detail(target_claim)
            if target_claim_has_time:
                target_claim_dt = datetime(target_claim_dt.year, target_claim_dt.month, target_claim_dt.day, t_h, t_m, 0, tzinfo=t_tz)

    evidence_items: List[Dict[str, Any]] = []
    verdicts: List[str] = []
    url_tier_map = {s.get("url"): s.get("authority_tier", AuthorityTier.TIER_3_GENERAL.value) for s in sources}
    url_badge_map = {s.get("url"): s.get("authority_badge", "") for s in sources}
    normalized_raw = " ".join(raw_extracted_text.lower().split())
    seen_quotes: set[str] = set()
    now_utc = datetime.now(timezone.utc)

    for c in claims:
        claim_text = c.get("claim", "").strip()
        source_url = c.get("source_url", "").strip()
        quote = c.get("exact_quote", "").strip()
        raw_date = c.get("extracted_date")

        if claim_text.startswith("|") or len(claim_text.split()) < 4 or "|" in claim_text[:5]:
            continue

        marketing_keywords = (
            "join us", "sign up", "empowering", "pioneering", "revolutionize",
            "sponsored by", "all rights reserved", "subscribe", "terms of use",
            "cookie policy", "privacy policy", "exclusive rewards"
        )
        if any(mk in claim_text.lower() for mk in marketing_keywords):
            continue

        has_semantics = bool(
            re.search(
                r"\b(deadline|due|ends|closes|starts|opens|submission|submit|by|before|until|rule|requirement|eligibility|guideline|schedule|timeline|date|time|deliverable|format)\b",
                claim_text,
                re.IGNORECASE,
            )
            or raw_date
        )
        if not has_semantics or (quote and len(quote.split()) < 2):
            continue

        entity_matched = True
        if entity_keywords:
            text_check = f"{claim_text.lower()} {quote.lower()} {source_url.lower()}"
            entity_matched = any(kw in text_check for kw in entity_keywords)

        normalized_quote = " ".join(quote.lower().split())
        own_text = (source_text_map or {}).get(source_url, "")
        in_own_text = (
            bool(normalized_quote and normalized_quote in " ".join(own_text.lower().split()))
            if own_text
            else bool(normalized_quote and normalized_quote in normalized_raw)
        )

        is_independent = in_own_text and (quote not in seen_quotes)
        if in_own_text and quote:
            seen_quotes.add(quote)
        verbatim_match = in_own_text

        tier = url_tier_map.get(source_url, AuthorityTier.TIER_3_GENERAL.value)
        cand_text_for_time = f"{raw_date or ''} {claim_text or ''} {quote or ''}"
        parsed_dt, year_provenance = _parse_explicit_year_date(cand_text_for_time)
        item_has_time = getattr(parsed_dt, "has_time", False)
        if not item_has_time:
            item_h, item_m, item_tz, item_has_time = _parse_time_and_tz_detail(cand_text_for_time)
            if item_has_time and parsed_dt:
                parsed_dt = ExplicitDateTime(parsed_dt.year, parsed_dt.month, parsed_dt.day, item_h, item_m, 0, tzinfo=item_tz)
                parsed_dt.has_time = True

        # Label classification for evidence candidate
        item_label = classify_deadline_label(quote, claim_text, raw_date or "")
        is_same_type = (item_label == claim_type)

        is_verified_quote = (
            verbatim_match and entity_matched and is_independent and (parsed_dt is not None if raw_date else True)
        )

        if not entity_matched:
            verdict = "NOT_FOUND"
        elif not verbatim_match or not quote or not is_independent:
            verdict = "UNVERIFIED"
        elif raw_date and not parsed_dt:
            verdict = "CONFLICTING" if year_provenance == "conflicting" else "UNVERIFIED"
        elif year_provenance == "conflicting":
            verdict = "CONFLICTING"
        elif year_provenance == "inferred":
            verdict = "UNVERIFIED"
        elif _COUNTDOWN_PATTERN.search(claim_text) or _COUNTDOWN_PATTERN.search(quote):
            verdict = "UNVERIFIED"
        elif not is_same_type:
            # Different deadline category (e.g. registration date vs submission deadline).
            # Do NOT use it to contradict or verify this claim.
            verdict = "UNVERIFIED"
        elif target_claim_dt and parsed_dt:
            # Same type candidate! Compare date, time, timezone, and year.
            date_mismatch = (
                target_claim_dt.year != parsed_dt.year or
                target_claim_dt.month != parsed_dt.month or
                target_claim_dt.day != parsed_dt.day
            )
            if date_mismatch:
                if tier in (AuthorityTier.TIER_1_OFFICIAL.value, AuthorityTier.TIER_2_TECHNICAL.value):
                    verdict = "CONTRADICTED"
                else:
                    verdict = "UNVERIFIED"
            else:
                # Date matches! Check time and timezone if specified
                if target_claim_has_time and item_has_time:
                    target_utc = target_claim_dt.astimezone(timezone.utc)
                    parsed_utc = parsed_dt.astimezone(timezone.utc)
                    if (target_utc.hour != parsed_utc.hour or target_utc.minute != parsed_utc.minute):
                        verdict = "PARTIALLY_VERIFIED"
                    else:
                        verdict = "VERIFIED"
                else:
                    verdict = "VERIFIED"

                # Check runtime clock for passed deadline
                if parsed_dt.astimezone(timezone.utc) < now_utc:
                    if verdict == "VERIFIED":
                        verdict = "STALE"
        elif parsed_dt and parsed_dt.astimezone(timezone.utc) < now_utc:
            verdict = "STALE"
        elif tier == AuthorityTier.TIER_1_OFFICIAL.value:
            verdict = "VERIFIED"
        elif tier == AuthorityTier.TIER_2_TECHNICAL.value:
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
                has_independent_domains = any(
                    check_domain_independence(u1, u2)
                    for u1 in agreeing_sources
                    for u2 in agreeing_sources
                    if u1 != u2
                )
                verdict = "VERIFIED" if has_independent_domains else "PARTIALLY_VERIFIED"
            else:
                verdict = "UNVERIFIED"
        else:
            verdict = "UNVERIFIED"

        if verdict == "VERIFIED" and year_provenance == "year_inferred":
            verdict = "PARTIALLY_VERIFIED"

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
            "display_quote": format_display_quote(quote),
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
            "is_independent": is_independent,
            "entity_matched": entity_matched,
            "deadline_type": item_label,
            "is_same_type": is_same_type,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        })

    # Check for conflicting dates across distinct sources for SAME deadline type
    dates_by_source = {}
    for item in evidence_items:
        if item.get("deadline_type") == claim_type and item.get("authority_tier") in (AuthorityTier.TIER_1_OFFICIAL.value, AuthorityTier.TIER_2_TECHNICAL.value):
            parsed_date = item.get("parsed_date")
            source_url = item.get("source_url")
            if isinstance(parsed_date, str) and source_url:
                d = parsed_date[:10]
                dates_by_source[source_url] = d

    unique_dates = set(dates_by_source.values())
    has_conflict = len(dates_by_source) >= 2 and len(unique_dates) > 1

    if has_conflict:
        for idx, item in enumerate(evidence_items):
            if item.get("deadline_type") == claim_type and isinstance(item.get("parsed_date"), str):
                item["verdict"] = "CONFLICTING"
                verdicts[idx] = "CONFLICTING"

    # Overall pipeline verdict rule
    if not evidence_items:
        overall = "NOT_FOUND"
    elif any(v == "CONTRADICTED" for v in verdicts):
        overall = "CONTRADICTED"
    elif any(v == "CONFLICTING" for v in verdicts):
        overall = "CONFLICTING"
    elif any(v == "PARTIALLY_VERIFIED" for v in verdicts):
        overall = "PARTIALLY_VERIFIED"
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
    """Execute complete Tavily research pipeline with deterministic evidence ledger.

    Starts a per-run Tavily credit counter when the caller has not already bound one
    (e.g. background jobs), so a single research run can never exceed the per-run cap.
    """
    counter_token = budget_context.ensure_run_counter()
    try:
        return await _run_tavily_research(
            query,
            run_id=run_id,
            include_domains=include_domains,
            max_credits=max_credits,
            target_entity=target_entity,
            trusted_event_url=trusted_event_url,
        )
    finally:
        if counter_token is not None:
            budget_context.end_run_counter(counter_token)


async def _run_tavily_research(
    query: str,
    run_id: Optional[str] = None,
    include_domains: Optional[List[str]] = None,
    max_credits: int = 4,
    target_entity: Optional[str] = None,
    trusted_event_url: Optional[str] = None,
) -> Dict[str, Any]:
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

    # 1. Check RAW TTL Cache
    t0_cache = time.perf_counter()
    ckey = _raw_cache_key(query, include_domains)
    raw_results: List[Dict[str, Any]] = []
    url_to_raw_content: Dict[str, str] = {}
    total_credits = 0
    from_cache = False

    if ckey in _RAW_SEARCH_CACHE:
        cached_time, c_results, c_blocks, c_credits = _RAW_SEARCH_CACHE[ckey]
        if (now - cached_time) < _CACHE_TTL_SECONDS:
            raw_results = [dict(r) for r in c_results]
            if isinstance(c_blocks, dict):
                url_to_raw_content = dict(c_blocks)
            else:
                url_to_raw_content = {r.get("url", ""): blk for r, blk in zip(raw_results, c_blocks) if r.get("url")}
            total_credits = c_credits
            from_cache = True
            logger.info("Serving raw search/extraction from cache for query '%s'", query)
    stage_timings["cache_lookup_ms"] = round((time.perf_counter() - t0_cache) * 1000, 2)

    if not from_cache:
        t0 = time.perf_counter()
        sub_queries = await decompose_query(query)
        stage_timings["decomposition_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        t0 = time.perf_counter()
        capped_reasons: List[str] = []
        try:
            raw_results, search_credits = await execute_subqueries(
                sub_queries, include_domains=include_domains, max_credits=max_credits, capped_out=capped_reasons
            )
            total_credits += search_credits
        except Exception as e:
            logger.warning("execute_subqueries failed: %s", e)
            stage_timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
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

        if not raw_results and capped_reasons:
            stage_timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)
            return {
                "status": "unavailable",
                "verdict": "NOT_FOUND",
                "summary": f"Web search capped: {capped_reasons[0]}",
                "capped": True,
                "evidence_ledger": [],
                "sources": [],
                "credits": total_credits,
                "stage_timings": stage_timings,
            }

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

        # Extract top candidate URLs (prioritize top authoritative sources)
        t0 = time.perf_counter()
        pre_ranked = sort_and_enrich_sources(raw_results, trusted_event_url=trusted_event_url)
        extract_urls = [r["url"] for r in pre_ranked if r.get("url")][:3]
        if extract_urls:
            try:
                extract_resp = await asyncio.wait_for(
                    tavily_extract(extract_urls, extract_depth="basic"),
                    timeout=getattr(settings, "TAVILY_EXTRACT_TIMEOUT_S", 8.0),
                )
                res_list = extract_resp.get("results", []) or []
                total_credits += len(res_list)
                for item in res_list:
                    u = (item.get("url") or "").strip()
                    raw = item.get("raw_content") or item.get("content") or ""
                    if u and raw:
                        url_to_raw_content[u] = raw
            except Exception as e:
                logger.warning("Tavily extraction timed out or failed: %s; falling back to snippets", e)
        stage_timings["extraction_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # Cache raw search and extraction results
        _RAW_SEARCH_CACHE[ckey] = (now, raw_results, url_to_raw_content, total_credits)

    # 4. Apply authority tier and badges per request from caller's own trusted URLs (AFTER cache)
    t0 = time.perf_counter()
    enriched_sources = sort_and_enrich_sources(raw_results, trusted_event_url=trusted_event_url)
    top_sources = enriched_sources[:3]
    stage_timings["ranking_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # 5. Extract structured claims per source, isolated strictly to text fetched from its own URL
    t0 = time.perf_counter()
    claims: List[Dict[str, Any]] = []
    source_text_map: Dict[str, str] = {}
    for s in top_sources:
        s_url = (s.get("url") or "").strip()
        candidate_pool = [s.get("content", "")]
        for u, raw_txt in url_to_raw_content.items():
            if u == s_url or u.rstrip("/") == s_url.rstrip("/"):
                candidate_pool.append(raw_txt)
                break

        text_to_scan = "\n".join(p for p in candidate_pool if p)
        source_text_map[s_url] = text_to_scan

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
            s_low = st.lower()
            if any(ign in s_low for ign in ("judging", "winner", "announcement", "banner", "changelog", "maintenance")):
                return -1
            return next((sc for kw, sc in (("submission deadline", 5), ("deadline:", 5), ("submissions close", 5), ("submission period", 4), ("deadline", 3), ("due date", 3), ("closes", 2), ("ends", 2)) if kw in s_low), 0)

        deadline_sentences.sort(key=_deadline_priority, reverse=True)
        chosen = deadline_sentences[0] if deadline_sentences else (filtered_sentences[0] if filtered_sentences else None)

        if chosen:
            dt_match = re.search(r"\b(202[4-9])\b", chosen)
            exact_quote = truncate_quote_cleanly(chosen)
            if exact_quote and exact_quote[-1] in (",", ";", ":"):
                exact_quote = exact_quote[:-1].strip()

            claims.append({
                "claim": chosen,
                "source_url": s_url,
                "exact_quote": exact_quote,
                "extracted_date": chosen if dt_match else None,
            })
    stage_timings["claim_extraction_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    # 6. Evaluate deterministic verdicts with full-corpus and per-source verbatim quote validation
    t0 = time.perf_counter()
    full_extracted_corpus = "\n\n".join(url_to_raw_content.values())
    combined_corpus = (full_extracted_corpus + "\n\n" + " ".join(s.get("content", "") for s in top_sources)).strip()
    overall_verdict, evidence_ledger = evaluate_deterministic_verdict(
        claims,
        combined_corpus,
        top_sources,
        target_entity=target_entity or query,
        source_text_map=source_text_map,
        target_claim=query,
    )
    stage_timings["verdict_eval_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    for item in evidence_ledger:
        item["run_id"] = active_run_id
        item["credits"] = total_credits

    # 7. Persist evidence ledger (scheduled in background to prevent DB latency from blocking response)
    t0 = time.perf_counter()
    if getattr(settings, "ENVIRONMENT", "") == "test":
        try:
            await persist_evidence_ledger(active_run_id, evidence_ledger)
        except Exception as e:
            logger.warning("Could not persist evidence ledger: %s", e)
    else:
        try:
            asyncio.create_task(persist_evidence_ledger(active_run_id, evidence_ledger))
        except Exception as e:
            logger.warning("Could not schedule evidence persistence: %s", e)
    stage_timings["db_persistence_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    stage_timings["total_ms"] = round((time.perf_counter() - t_start) * 1000, 2)

    if overall_verdict == "VERIFIED":
        summary_msg = f"Authoritative source confirms the deadline claim. Evaluated {len(top_sources)} sources. Overall verdict: VERIFIED."
    elif overall_verdict == "PARTIALLY_VERIFIED":
        summary_msg = f"The date is confirmed by official sources, but the specified time or timezone differs. Evaluated {len(top_sources)} sources. Overall verdict: PARTIALLY_VERIFIED."
    elif overall_verdict == "CONTRADICTED":
        summary_msg = f"Authoritative evidence contradicts the stated claim. Evaluated {len(top_sources)} sources. Overall verdict: CONTRADICTED."
    elif overall_verdict == "CONFLICTING":
        summary_msg = f"Conflicting dates were found across independent sources for this deadline. Evaluated {len(top_sources)} sources. Overall verdict: CONFLICTING."
    elif overall_verdict == "STALE":
        summary_msg = f"The verified deadline has already passed as of today's date. Evaluated {len(top_sources)} sources. Overall verdict: STALE."
    else:
        summary_msg = f"Unable to independently verify the claim from authoritative sources. Evaluated {len(top_sources)} sources. Overall verdict: UNVERIFIED."

    result = {
        "status": "ok",
        "verdict": overall_verdict,
        "run_id": active_run_id,
        "cached": from_cache,
        "summary": summary_msg,
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
