"""
Compass — Web Search and Ingestion Skills.

Handlers for live web searching, web page ingestion, and deadline verification using Tavily.
"""

from typing import Any, Dict
import logging

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
    citations = [
        {"title": r.get("title"), "url": r.get("url"), "score": r.get("score")}
        for r in results
    ]
    fenced = tavily_service.fence_web_content(results)
    top_url = citations[0]["url"] if citations else "none"
    summary = f"Found {len(results)} web result(s) for '{query}'. Top source: {top_url}"

    # Build markdown response for chat interface
    parts = [f"**Web Search Results for:** *{query}*"]
    for r in results[:3]:
        parts.append(f"• [{r.get('title', 'Untitled')}]({r.get('url', '')})\n  {r.get('content', '')[:500].strip()}...")
    formatted_response = "\n".join(parts) if results else summary

    return {
        "success": True,
        "data": {"results": results, "citations": citations, "source": "web"},
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
    """Compare a stored task's due date against live web sources to detect drift."""
    from backend.services import tavily as tavily_service
    from backend.memory import structured

    task_id = args.get("task_id")
    if not task_id:
        return {
            "success": False,
            "data": {},
            "summary": "task_id is required",
            "response": "task_id is required",
            "error": "task_id is required",
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

    query = f"{task_title} deadline submission date"
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
    summary = f"Checked '{task_title}' (stored due: {stored_due}) against {len(results)} live source(s)."

    return {
        "success": True,
        "data": {
            "task": dict(task),
            "results": results,
            "citations": [r.get("url") for r in results if r.get("url")],
            "source": "web",
        },
        "fenced_context": fenced,
        "summary": summary,
        "response": summary,
        "error": None,
    }
