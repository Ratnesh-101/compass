"""
Compass — Tavily Deep Research & Agentic Investigation Service.

Provides:
  - Autonomous query decomposition (breaks complex requests into 2-3 targeted subqueries).
  - Strict query & credit budget enforcement.
  - In-memory TTL search caching.
  - Domain authority re-ranking.
  - Structured citation extraction ([1], [2], [3] with full provenance).
  - Synthesis report generation with untrusted content boundaries.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.services.tavily_authority import sort_and_enrich_sources

logger = logging.getLogger("compass.services.tavily_research")

# 15-minute in-memory cache for search queries: key -> (timestamp, result_dict)
_SEARCH_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 900.0  # 15 minutes


def _get_cache_key(query: str, search_depth: str, topic: str) -> str:
    norm = f"{query.strip().lower()}|{search_depth}|{topic}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def get_cached_search(query: str, search_depth: str = "basic", topic: str = "general") -> Optional[Dict[str, Any]]:
    """Retrieve search results from in-memory cache if not expired."""
    key = _get_cache_key(query, search_depth, topic)
    entry = _SEARCH_CACHE.get(key)
    if entry:
        ts, data = entry
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return data
        else:
            del _SEARCH_CACHE[key]
    return None


def store_cached_search(query: str, search_depth: str, topic: str, data: Dict[str, Any]) -> None:
    """Store search results into cache."""
    # Prune oldest if cache grows > 200 items
    if len(_SEARCH_CACHE) > 200:
        oldest_key = min(_SEARCH_CACHE.keys(), key=lambda k: _SEARCH_CACHE[k][0])
        del _SEARCH_CACHE[oldest_key]
    key = _get_cache_key(query, search_depth, topic)
    _SEARCH_CACHE[key] = (time.time(), data)


def decompose_query(topic: str, max_subqueries: int = 3) -> List[str]:
    """Decompose a complex research objective into 2-3 focused subqueries.

    Uses deterministic heuristics for speed, predictability, and zero extra token cost.
    """
    clean = topic.strip()
    if not clean:
        return []

    subqueries = [clean]
    lower = clean.lower()

    # Heuristic decomposition based on query intent
    if any(k in lower for k in ("vs", "versus", "compare", "comparison", "difference")):
        # Extract comparison parts: e.g. "X vs Y"
        for sep in (" versus ", " vs. ", " vs ", " compared to ", " compare to "):
            if sep in lower:
                idx = lower.find(sep)
                part1 = clean[:idx].strip()
                part2 = clean[idx + len(sep):].strip()
                if part1 and part2:
                    subqueries = [
                        f"{part1} overview features architecture",
                        f"{part2} overview features architecture",
                        f"{part1} vs {part2} tradeoffs comparison benchmarks",
                    ]
                    break
    elif any(k in lower for k in ("deploy", "hosting", "production", "infrastructure", "nebius")):
        subqueries = [
            f"{clean} official documentation",
            f"{clean} pricing limits requirements",
            f"{clean} architecture tutorial examples",
        ]
    elif any(k in lower for k in ("hackathon", "competition", "deadline", "submission", "rules")):
        subqueries = [
            f"{clean} official rules guidelines",
            f"{clean} submission deadline schedule dates",
            f"{clean} prizes judging criteria",
        ]
    elif len(clean.split()) > 7:
        # Long question: split key concepts
        words = clean.split()
        subqueries = [
            " ".join(words[: len(words) // 2]) + " documentation",
            " ".join(words[len(words) // 2 :]) + " best practices",
            clean,
        ]

    # Enforce strict budget limit
    return subqueries[:max_subqueries]


async def execute_deep_research(
    topic: str,
    max_subqueries: int = 3,
    search_depth: str = "basic",
    include_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Execute end-to-end deep research across decomposed subqueries with source authority scoring.

    Returns structured evidence, deduplicated sources, domain authority badges, and citations.
    """
    from backend.services import tavily as tavily_service

    if not tavily_service.tavily_available():
        raise RuntimeError("Tavily service is disabled or unconfigured")

    subqueries = decompose_query(topic, max_subqueries=max_subqueries)
    if not subqueries:
        subqueries = [topic]

    tasks = []
    cache_hits = 0
    start_t = time.perf_counter()

    async def _fetch_single(q: str) -> Dict[str, Any]:
        nonlocal cache_hits
        cached = get_cached_search(q, search_depth=search_depth, topic="general")
        if cached:
            cache_hits += 1
            return cached
        res = await tavily_service.search(
            query=q,
            max_results=3,
            search_depth=search_depth,
            include_domains=include_domains or [],
        )
        store_cached_search(q, search_depth, "general", res)
        return res

    results_by_subquery = await asyncio.gather(
        *[_fetch_single(sq) for sq in subqueries],
        return_exceptions=True,
    )

    all_raw_items: List[Dict[str, Any]] = []
    for item in results_by_subquery:
        if isinstance(item, dict):
            all_raw_items.extend(item.get("results", []))
        elif isinstance(item, Exception):
            logger.warning(f"Subquery search error in deep research: {item}")

    # Deduplicate by normalized URL
    seen_urls = set()
    deduped_items = []
    for r in all_raw_items:
        url = (r.get("url") or "").strip().lower()
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped_items.append(r)

    # Rank and enrich with Domain Authority
    ranked_items = sort_and_enrich_sources(deduped_items)

    # Build numbered structured citations
    citations = []
    for idx, item in enumerate(ranked_items[:6], start=1):
        citations.append({
            "id": idx,
            "marker": f"[{idx}]",
            "title": item.get("title") or "Untitled",
            "url": item.get("url") or "",
            "domain": item.get("domain") or "",
            "authority_tier": item.get("authority_tier"),
            "authority_badge": item.get("authority_badge"),
            "composite_score": item.get("composite_score"),
            "snippet": (item.get("content") or "")[:400].strip(),
        })

    elapsed_ms = int((time.perf_counter() - start_t) * 1000)

    # Build structured synthesis report
    report_lines = [
        f"### Deep Research Synthesis: *{topic}*",
        f"*Decomposed into {len(subqueries)} targeted subqueries across {len(citations)} authoritative sources ({elapsed_ms}ms)*\n",
        "#### Key Evidence & Findings:",
    ]

    for c in citations:
        report_lines.append(
            f"- **{c['marker']} {c['title']}** `{c['authority_badge']}`\n"
            f"  {c['snippet']}...\n"
            f"  *Source:* [{c['domain']}]({c['url']})"
        )

    report_lines.append("\n#### Verified Sources:")
    for c in citations:
        report_lines.append(f"{c['marker']} [{c['title']}]({c['url']}) — `{c['authority_badge']}`")

    formatted_report = "\n".join(report_lines)
    fenced_context = tavily_service.fence_web_content(ranked_items[:6])

    return {
        "topic": topic,
        "subqueries": subqueries,
        "citations": citations,
        "results_count": len(citations),
        "cache_hits": cache_hits,
        "elapsed_ms": elapsed_ms,
        "fenced_context": fenced_context,
        "formatted_report": formatted_report,
    }
