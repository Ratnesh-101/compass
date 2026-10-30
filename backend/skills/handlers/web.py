"""
Compass — Web Search and Ingestion Skills.

Handlers for live web searching, web page ingestion, and deadline verification using Tavily.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, date
import logging
import re
from urllib.parse import urlparse

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.web")


@register_skill("search_web")
async def handle_search_web(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Search the live web using the centralized Tavily service.

    Returns citations, fenced context, and human-readable summary.
    """
    from backend.services import tavily as tavily_service

    query = (args.get("query") or "").strip()
    if not query:
        return {
            "success": False,
            "data": {},
            "summary": "Query cannot be empty",
            "response": "Please provide a search query.",
            "error": "Query cannot be empty",
        }

    if not tavily_service.tavily_available():
        return {
            "success": False,
            "data": {},
            "summary": "Web search is not configured on this instance",
            "response": "Web search is currently disabled or missing an API key.",
            "error": "Web search is not configured on this instance",
        }

    depth = args.get("depth") or args.get("search_depth") or "basic"
    try:
        resp = await tavily_service.search(query, search_depth=depth)
    except Exception as e:
        logger.warning(f"Tavily search failed: {e}")
        return {
            "success": False,
            "data": {},
            "summary": f"Web search failed: {e}",
            "response": f"Web search failed: {e}",
            "error": f"Web search failed: {e}",
        }

    results = resp.get("results", [])
    from backend.services.tavily_authority import sort_and_enrich_sources
    ranked_results = sort_and_enrich_sources(results) if results else results

    citations = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "score": r.get("score"),
            "domain": r.get("domain", ""),
            "authority_tier": r.get("authority_tier", "tier_3_general"),
            "authority_badge": r.get("authority_badge", "Web"),
            "composite_score": r.get("composite_score", r.get("score")),
        }
        for r in ranked_results
    ]
    fenced = tavily_service.fence_web_content(ranked_results)
    top_url = citations[0]["url"] if citations else "none"
    top_badge = citations[0].get("authority_badge", "Web") if citations else ""
    summary = f"Found {len(ranked_results)} web result(s) for '{query}'. Top source: {top_url} [{top_badge}]"

    # Build synthesized markdown response for chat interface
    is_deadline_query = bool(
        re.search(r"\b(deadline|due\s+date|submission\s+(?:date|deadline|period)|closes?|ends?|verify.*date|when\s+is.*due|hackathon)\b", query, re.IGNORECASE)
    )

    formatted_response = summary
    if is_deadline_query and ranked_results:
        candidates = []
        for r in ranked_results:
            content = r.get("content", "")
            url = r.get("url", "")
            title = r.get("title", "")
            badge = r.get("authority_badge", "Web")
            for line in content.split("\n"):
                clean_line = line.strip()
                if not clean_line or len(clean_line) < 15:
                    continue
                if re.search(r"\b(deadline|submission|due|closes|ends)\b", clean_line, re.I) and re.search(r"\b(202[4-9]|January|February|March|April|May|June|July|August|September|October|November|December|Oct|Nov|Dec)\b", clean_line, re.I):
                    candidates.append({
                        "line": clean_line,
                        "url": url,
                        "title": title,
                        "badge": badge,
                    })

        if candidates:
            # Prefer official rules / devpost / organizer sources
            best_cand = None
            for c in candidates:
                cand_url = c.get("url") or ""
                try:
                    parsed = urlparse(cand_url)
                    host = (parsed.hostname or "").lower()
                    path = (parsed.path or "").lower()
                    is_devpost = host == "devpost.com" or host.endswith(".devpost.com")
                    is_rules_or_updates = "rules" in path or "updates" in path
                except Exception:
                    is_devpost = False
                    is_rules_or_updates = False

                if is_rules_or_updates or is_devpost:
                    best_cand = c
                    break
            if not best_cand:
                best_cand = candidates[0]

            out_lines = [
                f"### 🎯 Verified Finding: {best_cand.get('title') or query}",
                "",
                f"> \"{best_cand['line']}\"",
                "",
                f"**Primary Official Source:** [{best_cand.get('title') or best_cand['url']}]({best_cand['url']}) `{best_cand['badge']}`",
                "",
            ]

            other_sources = [c for c in candidates if c["url"] != best_cand["url"]]
            if other_sources:
                out_lines.append("**Corroborating Evidence:**")
                seen_urls = {best_cand["url"]}
                for oc in other_sources:
                    if oc["url"] not in seen_urls:
                        seen_urls.add(oc["url"])
                        out_lines.append(f"- [{oc.get('title') or oc['url']}]({oc['url']}) `{oc['badge']}`: *\"{oc['line'][:150]}\"*")
                out_lines.append("")

            formatted_response = "\n".join(out_lines).strip()
        else:
            # Deadline query but no explicit dates extracted
            parts = [
                f"### Web Research: *{query}*",
                "",
                "No explicit deadline date could be conclusively verified from the official sources. Here are the most authoritative references found:",
                "",
            ]
            for r in ranked_results[:3]:
                badge = r.get("authority_badge", "Web")
                parts.append(f"• [{r.get('title', 'Untitled')}]({r.get('url', '')}) `{badge}`\n  {r.get('content', '')[:350].strip()}...")
            formatted_response = "\n".join(parts)
    elif ranked_results:
        parts = [f"**Web Search Results for:** *{query}*"]
        for r in ranked_results[:3]:
            badge = r.get("authority_badge", "Web")
            parts.append(f"• [{r.get('title', 'Untitled')}]({r.get('url', '')}) `{badge}`\n  {r.get('content', '')[:400].strip()}...")
        formatted_response = "\n".join(parts)

    return {
        "success": True,
        "data": {"results": ranked_results, "citations": citations, "source": "web"},
        "fenced_context": fenced,
        "summary": summary,
        "response": formatted_response,
        "error": None,
    }


@register_skill("ingest_url")
async def handle_ingest_url(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Extract and ingest a web page's contents into Compass long-term memory.

    Chunked, embedded via Qwen3 768-dim, and stored into memory_chunks table.
    Mutating action — must be confirm-gated by the agent loop.
    """
    from backend.services import tavily as tavily_service
    from backend.memory import vector, structured

    VALID_DOMAINS = {"hackathon", "coursework", "code", "general"}
    url = (args.get("url") or "").strip()
    domain = (args.get("domain") or "general").lower()

    if domain not in VALID_DOMAINS:
        return {
            "success": False,
            "data": {},
            "summary": f"Invalid domain '{domain}'. Must be one of: {', '.join(sorted(VALID_DOMAINS))}",
            "response": f"Invalid domain '{domain}'.",
            "error": f"Invalid domain '{domain}'",
        }

    if not url.startswith(("http://", "https://")):
        return {
            "success": False,
            "data": {},
            "summary": "URL must start with http:// or https://",
            "response": "URL must start with http:// or https://",
            "error": "URL must start with http:// or https://",
        }

    from backend.services.security import is_safe_url
    safe, reason = is_safe_url(url)
    if not safe:
        return {
            "success": False,
            "data": {},
            "summary": f"SSRF blocked: {reason}",
            "response": f"URL request rejected for security reasons: {reason}",
            "error": f"SSRF blocked: {reason}",
        }

    if not tavily_service.tavily_available():
        return {
            "success": False,
            "data": {},
            "summary": "Tavily service is not available on this instance",
            "response": "Tavily service is not configured.",
            "error": "Tavily service is not available",
        }

    try:
        resp = await tavily_service.extract([url], extract_depth="advanced")
    except Exception as e:
        logger.error(f"Tavily extract failed for {url}: {e}")
        return {
            "success": False,
            "data": {},
            "summary": f"Extraction failed: {e}",
            "response": f"Extraction failed: {e}",
            "error": f"Extraction failed: {e}",
        }

    ok = resp.get("results", [])
    if not ok:
        failed = resp.get("failed_results", [])
        return {
            "success": False,
            "data": {"failed": failed},
            "summary": f"Could not extract content from {url}",
            "response": f"Could not extract content from {url}",
            "error": f"Could not extract content from {url}",
        }

    raw = ok[0].get("raw_content") or ok[0].get("content") or ""
    flagged = tavily_service.scan_for_injection(raw)

    # Chunk text (~1200 chars with 200 char overlap, max 12 chunks)
    chunks = [raw[i : i + 1200] for i in range(0, len(raw), 1000)][:12]
    stored = 0

    async with pool.acquire() as conn:
        project_id = None
        if args.get("project"):
            proj = await structured.get_or_create_project(conn, args["project"], domain)
            project_id = proj["id"]

        tags = ["web", "tavily-extract"]
        if flagged:
            tags.append("injection-flagged")

        for ch in chunks:
            if not ch.strip():
                continue
            await vector.store_chunk(
                conn,
                domain=domain,
                content=ch,
                project_id=project_id,
                source=url,
                tags=tags,
            )
            stored += 1

    injection_note = " ⚠️ Page contained instruction-like text; stored as data only." if flagged else ""
    summary = f"Ingested {url} into {domain.upper()} memory as {stored} searchable chunk(s).{injection_note}"

    return {
        "success": True,
        "data": {
            "url": url,
            "chunks_stored": stored,
            "domain": domain,
            "injection_flagged": bool(flagged),
        },
        "summary": summary,
        "response": summary,
        "error": None,
    }


@register_skill("verify_deadline")
async def handle_verify_deadline(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Compare a stored task's due date against live web sources or verify a claim string."""
    from backend.services import tavily as tavily_service
    from backend.services.tavily_deadline import analyze_deadline_drift
    from backend.memory import structured

    task_id = args.get("task_id")
    claim_or_query = (args.get("claim") or args.get("query") or args.get("topic") or "").strip()

    if not task_id and claim_or_query:
        return await handle_verify_with_tavily(args, pool)

    if not task_id:
        return {
            "success": False,
            "data": {},
            "summary": "task_id or claim is required for verification",
            "response": "Please specify a task or claim to verify.",
            "error": "task_id or claim is required",
        }

    async with pool.acquire() as conn:
        task = await structured.get_task(conn, int(task_id))
    if not task:
        return {
            "success": False,
            "data": {},
            "summary": f"No task with id {task_id}",
            "response": f"No task with id {task_id}",
            "error": f"No task with id {task_id}",
        }

    task_title = task.get("title", "")
    stored_due = str(task.get("due_date") or "none")

    if not tavily_service.tavily_available():
        return {
            "success": False,
            "data": {"task": dict(task)},
            "summary": "Web search is not configured to verify deadline",
            "response": "Web search is not configured.",
            "error": "Web search is not configured",
        }

    from backend.services.deadline_query import build_deadline_query
    query = build_deadline_query(task_title, task.get("project_name"), task.get("domain"))
    try:
        resp = await tavily_service.search(query, search_depth="basic")
    except Exception as e:
        return {
            "success": False,
            "data": {"task": dict(task)},
            "summary": f"Web search failed during verification: {e}",
            "response": f"Web search failed during verification: {e}",
            "error": str(e),
        }

    results = resp.get("results", [])
    fenced = tavily_service.fence_web_content(results)
    drift_info = analyze_deadline_drift(stored_due, results)

    base_summary = f"Checked '{task_title}' (stored due: {stored_due}) against {len(results)} live source(s)."

    if drift_info["has_drift"]:
        drift_note = (
            f"\n⚠️ Schedule Drift Detected: Official source ({drift_info['source_url'] or 'web'}) "
            f"indicates deadline is {drift_info['live_date']} ({drift_info['direction']} by {abs(drift_info['drift_days'])} days)."
        )
        full_summary = f"{base_summary}{drift_note}"
    elif drift_info["drift_verdict"] == "CONFIRMED_ACCURATE":
        drift_note = f"\n✅ Confirmed Accurate: Stored deadline ({stored_due}) matches live official source."
        full_summary = f"{base_summary}{drift_note}"
    else:
        full_summary = base_summary

    return {
        "success": True,
        "data": {
            "task": dict(task),
            "results": results,
            "citations": [r.get("url") for r in results if r.get("url")],
            "drift_analysis": drift_info,
            "source": "web",
            "evidence": {
                "items": [
                    {
                        "claim": f"{task_title} deadline: {stored_due}",
                        "source_url": drift_info.get("source_url") or (results[0].get("url") if results else ""),
                        "display_quote": drift_info.get("evidence") or "",
                        "authority_tier": "tier_1_official" if drift_info.get("is_primary_source") else "tier_3_general",
                        "authority_badge": "Official Organizer" if drift_info.get("is_primary_source") else "Web",
                        "verdict": "VERIFIED" if drift_info.get("drift_verdict") == "CONFIRMED_ACCURATE" else ("CONFLICTING" if drift_info.get("has_drift") else "UNVERIFIED"),
                        "local_deadline_ist": drift_info.get("live_date"),
                    }
                ],
                "verdict": "VERIFIED" if drift_info.get("drift_verdict") == "CONFIRMED_ACCURATE" else ("CONFLICTING" if drift_info.get("has_drift") else "UNVERIFIED"),
                "summary": full_summary,
            },
        },
        "fenced_context": fenced,
        "summary": full_summary,
        "response": full_summary,
        "error": None,
    }


@register_skill("verify_with_tavily")
async def handle_verify_with_tavily(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Execute evidence-based claim or deadline verification using the complete Tavily pipeline."""
    from backend.services.tavily_pipeline import run_tavily_research
    from backend.router_helpers import is_tavily_verification_intent

    claim = (args.get("claim") or args.get("query") or args.get("topic") or "").strip()
    target_entity = (args.get("target_entity") or "").strip() or None
    target_message_id = args.get("target_message_id")

    # If the claim is itself an unresolved verification intent string, reject it
    if is_tavily_verification_intent(claim):
        claim = ""

    if not claim:
        return {
            "success": False,
            "data": {},
            "summary": "I couldn't find a specific claim or deadline to verify. Could you specify which statement or deadline you would like me to check?",
            "response": "I couldn't find a specific claim or deadline to verify. Could you specify which statement or deadline you would like me to check?",
            "error": "claim cannot be empty",
        }

    now_dt = datetime.now().astimezone()
    today_str = now_dt.strftime("%B %d, %Y (%Z)")

    try:
        pipeline_res = await run_tavily_research(
            query=claim,
            target_entity=target_entity,
        )
    except Exception as e:
        logger.error("Tavily verification failed: %s", e, exc_info=True)
        return {
            "success": False,
            "data": {
                "verdict": "UNVERIFIED",
                "evidence_ledger": [],
                "evidence": {
                    "target_message_id": target_message_id,
                    "claim_checked": claim,
                    "verdict": "UNVERIFIED",
                    "finding": f"Verification error: {e}",
                    "verified_at": today_str,
                    "sources": [],
                    "items": [],
                    "limitations": [f"Pipeline error: {e}"],
                    "summary": f"Verification error: {e}",
                },
            },
            "summary": f"Verification encountered an error: {e}",
            "response": f"⚠️ Could not complete Tavily verification: {e}. The claim remains **UNVERIFIED**.",
            "error": str(e),
        }

    overall_verdict = pipeline_res.get("verdict", "UNVERIFIED")
    evidence_ledger = pipeline_res.get("evidence_ledger", [])
    top_sources = pipeline_res.get("sources", [])
    summary_text = pipeline_res.get("summary", "")

    verdict_badge = overall_verdict.upper()
    if verdict_badge in ("CONFLICTING", "CONTRADICTED"):
        v_icon = "⚠️"
    elif verdict_badge == "VERIFIED":
        v_icon = "✅"
    elif verdict_badge == "PARTIALLY_VERIFIED":
        v_icon = "🟡"
    elif verdict_badge in ("STALE", "NOT_FOUND"):
        v_icon = "🕒"
    else:
        v_icon = "🔍"

    primary_tier = "Web"
    if evidence_ledger:
        primary_tier = evidence_ledger[0].get("authority_badge") or evidence_ledger[0].get("authority_tier") or "Official Organizer"
    elif top_sources:
        primary_tier = top_sources[0].get("authority_badge") or top_sources[0].get("authority_tier") or "General Web"

    formatted_response = (
        f"### 🔍 Tavily Verification: {v_icon} {verdict_badge}\n\n"
        f"**Claim Checked:** \"{claim}\"\n"
        f"**Verified on:** {today_str}\n"
        f"**Primary Source Authority:** [{primary_tier}]\n\n"
        f"**Finding:** {summary_text}"
    )

    sources_for_card = []
    seen_urls = set()
    for ev in evidence_ledger:
        url = ev.get("source_url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            sources_for_card.append({
                "title": ev.get("authority_badge") or ev.get("authority_tier") or "Official Source",
                "url": url,
                "authority": ev.get("authority_badge") or ev.get("authority_tier") or "Official Organizer",
                "evidence": ev.get("display_quote") or ev.get("exact_quote") or ev.get("verbatim_quote") or "",
                "published_at": ev.get("published_date") or None,
            })
    for s in top_sources:
        url = s.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            sources_for_card.append({
                "title": s.get("title") or url,
                "url": url,
                "authority": s.get("authority_badge") or s.get("authority_tier") or "General Web",
                "evidence": s.get("content", "")[:200] if s.get("content") else "",
                "published_at": None,
            })

    limitations = []
    if any(ev.get("local_deadline_ist") for ev in evidence_ledger):
        limitations.append("Local deadline normalized to IST.")
    if overall_verdict == "CONFLICTING":
        limitations.append("Conflicting deadline dates reported across independent web sources.")
    elif overall_verdict == "STALE":
        limitations.append("The verified deadline has already passed.")
    elif overall_verdict == "CONTRADICTED":
        limitations.append("Official evidence contradicts the previous claim date.")

    structured_evidence = {
        "target_message_id": target_message_id,
        "claim_checked": claim,
        "verdict": overall_verdict,
        "finding": summary_text,
        "verified_at": today_str,
        "sources": sources_for_card,
        "items": evidence_ledger,
        "limitations": limitations,
        "summary": summary_text,
    }

    return {
        "success": True,
        "data": {
            "verdict": overall_verdict,
            "evidence_ledger": evidence_ledger,
            "evidence": structured_evidence,
            "sources": top_sources,
            "citations": [s.get("url") for s in top_sources if s.get("url")],
        },
        "summary": summary_text,
        "response": formatted_response,
        "error": None,
    }


@register_skill("deep_research")
async def handle_deep_research(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Execute end-to-end deep research on a topic using query decomposition and domain authority ranking.

    Returns structured evidence, formatted report with numbered citations, and untrusted fenced context.
    """
    from backend.services.tavily_research import execute_deep_research

    topic = (args.get("topic") or args.get("query") or "").strip()
    if not topic:
        return {
            "success": False,
            "data": {},
            "summary": "Research topic cannot be empty",
            "response": "Please provide a research topic.",
            "error": "Topic cannot be empty",
        }

    max_subqueries = int(args.get("max_subqueries") or 3)
    search_depth = args.get("search_depth") or "basic"

    try:
        report_data = await execute_deep_research(
            topic=topic,
            max_subqueries=max_subqueries,
            search_depth=search_depth,
        )
    except Exception as e:
        logger.error(f"Deep research failed for '{topic}': {e}")
        return {
            "success": False,
            "data": {},
            "summary": f"Deep research failed: {e}",
            "response": f"Deep research failed: {e}",
            "error": str(e),
        }

    return {
        "success": True,
        "data": {
            "topic": report_data["topic"],
            "subqueries": report_data["subqueries"],
            "citations": report_data["citations"],
            "results_count": report_data["results_count"],
            "elapsed_ms": report_data["elapsed_ms"],
        },
        "fenced_context": report_data["fenced_context"],
        "summary": f"Completed deep research on '{topic}' ({len(report_data['citations'])} authoritative sources).",
        "response": report_data["formatted_report"],
        "error": None,
    }


@register_skill("save_verified_finding")
async def handle_save_verified_finding(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Save a verified research finding or fact into long-term vector memory.

    Stores structured knowledge chunks with citation provenance instead of noisy raw page dumps.
    """
    from backend.memory import vector, structured

    fact = (args.get("fact") or args.get("finding") or "").strip()
    if not fact:
        return {
            "success": False,
            "data": {},
            "summary": "Finding text cannot be empty",
            "response": "Please provide the finding or fact text to save.",
            "error": "Finding cannot be empty",
        }

    domain = (args.get("domain") or "general").lower()
    source_url = (args.get("source_url") or "tavily-research").strip()
    citation = args.get("citation") or ""

    stored_text = f"{fact}\n\nEvidence Source: {source_url}"
    if citation:
        stored_text += f" ({citation})"

    async with pool.acquire() as conn:
        project_id = None
        if args.get("project"):
            proj = await structured.get_or_create_project(conn, args["project"], domain)
            project_id = proj["id"]

        await vector.store_chunk(
            conn,
            domain=domain,
            content=stored_text,
            project_id=project_id,
            source=source_url,
            tags=["web", "tavily-verified", "research-finding"],
        )

    summary = f"Saved verified finding to {domain.upper()} memory with citation provenance."
    return {
        "success": True,
        "data": {
            "fact": fact,
            "source_url": source_url,
            "domain": domain,
        },
        "summary": summary,
        "response": summary,
        "error": None,
    }
