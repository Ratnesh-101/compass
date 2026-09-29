"""
Compass — Context, Memory, and Synthesis Handlers.
"""

from typing import Any, Dict, Optional, Tuple
import logging

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.context")


def _extract_completion_result(
    resp: Any,
    default_prompt: str,
    default_prompt_tokens: Optional[int] = None,
    default_completion_tokens: int = 100,
) -> Tuple[Optional[str], int, int]:
    """Extract content, prompt_tokens, and completion_tokens safely from ChatCompletion response."""
    usage: Any = getattr(resp, "usage", None)
    fallback_p_tok = default_prompt_tokens or (len(default_prompt.split()) * 2)
    p_tok = getattr(usage, "prompt_tokens", None) or fallback_p_tok
    c_tok = getattr(usage, "completion_tokens", None) or default_completion_tokens

    choices = getattr(resp, "choices", None)
    first_choice = choices[0] if choices else None
    msg = getattr(first_choice, "message", None) if first_choice else None
    content = getattr(msg, "content", None) if msg else None
    return content, p_tok, c_tok


@register_skill("query_code_context")
async def handle_query_code_context(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query memory_chunks using vector.search_chunks and synthesize response via SKILL_MODEL."""
    from backend.memory import vector
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    query = args.get("query", "")
    domain = args.get("domain", "code")
    user_id = args.get("user_id")

    try:
        async with pool.acquire() as conn:
            if user_id:
                try:
                    chunks = await vector.search_chunks(conn, query=query, domain=domain, limit=3, user_id=user_id)
                except TypeError:
                    chunks = await vector.search_chunks(conn, query=query, domain=domain, limit=3)
            else:
                chunks = await vector.search_chunks(conn, query=query, domain=domain, limit=3)
        count = len(chunks)

        # Synthesize technical response using SKILL_MODEL (nvidia/nemotron-3-super-120b-a12b)
        if chunks and settings.NEBIUS_API_KEY:
            try:
                context_text = "\n\n".join(f"[Snippet #{c['id']}]:\n{c['content']}" for c in chunks)
                client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=15.0)
                prompt = (
                    f"Answer the user's question using the retrieved code context below.\n\n"
                    f"Context:\n{context_text}\n\n"
                    f"Question: {query}"
                )
                resp: Any = await client.chat.completions.create(
                    model=settings.SKILL_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a senior technical coding assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=384,
                    stream=False,
                )
                raw_content, p_tok, c_tok = _extract_completion_result(resp, prompt, default_completion_tokens=100)
                record_usage(settings.SKILL_MODEL, p_tok, c_tok)
                if raw_content is not None and raw_content.strip():
                    summary = raw_content.strip()
                else:
                    summary = f"Retrieved {count} relevant memory chunk(s) for query: '{query}'."
                return {
                    "response": summary,
                    "data": {"chunks": chunks, "count": count, "model": settings.SKILL_MODEL},
                }
            except Exception as llm_err:
                logger.warning(f"SKILL_MODEL synthesis failed: {llm_err}")

        summary = f"Retrieved {count} relevant memory chunk(s) for query: '{query}'."
        return {
            "response": summary,
            "data": {"chunks": chunks, "count": count},
        }
    except Exception as e:
        return {
            "response": f"Code context search encountered: {e}",
            "data": {"chunks": [], "error": str(e)},
        }


@register_skill("log_code_context")
async def handle_log_code_context(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Store code snippet/context in memory_chunks via vector.store_chunk."""
    from backend.memory import vector
    content = args.get("content", "")
    domain = args.get("domain", "code")
    tags = args.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    try:
        async with pool.acquire() as conn:
            chunk = await vector.store_chunk(conn, content=content, domain=domain, tags=tags)
        return {
            "response": f"Logged code memory to {domain.upper()} domain with 768-dim vector.",
            "data": chunk,
        }
    except Exception as e:
        return {
            "response": f"Could not log code memory: {e}",
            "data": {"error": str(e)},
        }


@register_skill("log_code_snippet")
async def handle_log_code_snippet(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Log code snippets and technical context into pgvector with 768-dim embeddings."""
    from backend.memory import vector, structured
    content = args.get("content", "")
    project_name = args.get("project")
    tags = args.get("tags", "")
    tag_list = [t.strip() for t in tags.split(",")] if isinstance(tags, str) and tags else []

    async with pool.acquire() as conn:
        project_id = None
        if project_name:
            proj = await structured.get_or_create_project(conn, project_name, "code")
            project_id = proj.get("id")
        chunk = await vector.store_chunk(conn, content=content, domain="code", project_id=project_id, tags=tag_list)
    return {"response": "💻 Logged code context with 768-dim embedding in Neon HNSW index.", "data": chunk}


@register_skill("summarize_day")
async def handle_summarize_day(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Return executive daily standup summary using SYNTHESIS_MODEL across domains."""
    from backend.memory import structured
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, status="open")

    by_domain: Dict[str, int] = {}
    for t in tasks:
        d = t.get("domain", "general")
        by_domain[d] = by_domain.get(d, 0) + 1

    # Synthesize daily briefing using SYNTHESIS_MODEL (nvidia/Nemotron-3-Ultra-550b-a55b)
    if tasks and settings.NEBIUS_API_KEY:
        try:
            task_list_str = "\n".join(
                f"- [{t['domain'].upper()}] {t['title']} (Due: {t.get('due_date') or 'No date'}, Priority: {t.get('priority', 'medium')})"
                for t in tasks[:15]
            )
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=15.0)
            prompt = (
                "Synthesize the following active tasks into a concise, high-impact 2-3 sentence daily briefing. "
                "Highlight the nearest deadlines across hackathon, coursework, and code:\n\n"
                f"{task_list_str}"
            )
            resp: Any = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=[
                    {"role": "system", "content": "You provide prioritized, executive daily standup summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=256,
                stream=False,
            )
            raw_content, p_tok, c_tok = _extract_completion_result(resp, prompt, default_completion_tokens=80)
            record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)
            if raw_content is not None and raw_content.strip():
                summary = raw_content.strip()
            else:
                summary = f"Daily summary: {len(tasks)} total open task(s)."
            return {
                "response": summary,
                "data": {"open_tasks_by_domain": by_domain, "total": len(tasks), "model": settings.SYNTHESIS_MODEL},
            }
        except Exception as llm_err:
            logger.warning(f"SYNTHESIS_MODEL daily summary failed: {llm_err}")

    parts = [f"{d.upper()}: {c}" for d, c in by_domain.items()]
    summary = f"Daily summary: {len(tasks)} total open task(s) ({', '.join(parts) if parts else 'None'})."
    return {
        "response": summary,
        "data": {"open_tasks_by_domain": by_domain, "total": len(tasks)},
    }


@register_skill("query_coursework_notes")
async def handle_query_coursework_notes(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Search coursework notes using vector memory search specifically filtered to domain='coursework'."""
    cw_args = dict(args)
    cw_args["domain"] = "coursework"
    if not cw_args.get("query"):
        for alt_key in ("course", "topic", "notes", "subject"):
            if cw_args.get(alt_key):
                cw_args["query"] = str(cw_args[alt_key])
                break
    return await handle_query_code_context(cw_args, pool)


@register_skill("summarize_across_domains")
async def handle_summarize_across_domains(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Escalates to Nemotron-3 Ultra (550B) over pre-aggregated multi-domain context for roadmap synthesis."""
    from backend.memory import structured
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, status="open")
        projects = await structured.list_projects(conn)
        try:
            code_chunks = await conn.fetch(
                "SELECT id, content, tags FROM memory_chunks WHERE domain = 'code' ORDER BY id DESC LIMIT 5"
            )
        except Exception:
            code_chunks = []
        try:
            cw_chunks = await conn.fetch(
                "SELECT id, content, tags FROM memory_chunks WHERE domain = 'coursework' ORDER BY id DESC LIMIT 5"
            )
        except Exception:
            cw_chunks = []

    by_domain: Dict[str, int] = {}
    for t in tasks:
        d = t.get("domain", "general")
        by_domain[d] = by_domain.get(d, 0) + 1

    tasks_context = "\n".join(
        f"- [{t['domain'].upper()}] {t['title']} (Due: {t.get('due_date') or 'No date'}, Priority: {t.get('priority', 'medium')})"
        for t in tasks[:15]
    ) or "No active tasks."

    code_context = "\n".join(
        f"- [Snippet #{c['id']}]: {c['content'][:150]}..."
        for c in code_chunks
    ) or "No recent code snippets."

    cw_context = "\n".join(
        f"- [Note #{c['id']}]: {c['content'][:150]}..."
        for c in cw_chunks
    ) or "No recent coursework notes."

    p_names = ", ".join(f"{p['name']} ({p.get('domain', 'general')})" for p in projects[:10]) or "None"

    combined_context = (
        f"### 1. Tracked Projects\n{p_names}\n\n"
        f"### 2. Active Tasks by Domain\n{tasks_context}\n\n"
        f"### 3. Technical Code Context\n{code_context}\n\n"
        f"### 4. Coursework Notes\n{cw_context}"
    )

    if settings.NEBIUS_API_KEY:
        try:
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=15.0)
            prompt = (
                "You are an executive multi-domain roadmap planner powered by Nemotron-3 Ultra (550B). "
                "Synthesize the following cross-domain state into an integrated executive roadmap. "
                "Explicitly call out dependencies between hackathon deadlines, coursework exams/labs, and code implementation.\n\n"
                f"{combined_context}"
            )
            resp: Any = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=[
                    {"role": "system", "content": "You provide comprehensive, multi-domain executive roadmap briefings."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=384,
                stream=False,
            )
            raw_content, p_tok, c_tok = _extract_completion_result(resp, prompt, default_completion_tokens=120)
            record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)
            if raw_content is not None and raw_content.strip():
                summary = raw_content.strip()
            else:
                summary = f"Multi-domain roadmap: {len(tasks)} tasks across {len(by_domain)} domains, {len(code_chunks)} code chunks, {len(cw_chunks)} coursework notes."
            return {
                "response": summary,
                "data": {
                    "open_tasks_by_domain": by_domain,
                    "total_tasks": len(tasks),
                    "code_chunks_count": len(code_chunks),
                    "coursework_chunks_count": len(cw_chunks),
                    "projects_count": len(projects),
                    "model": settings.SYNTHESIS_MODEL,
                },
            }
        except Exception as llm_err:
            logger.warning(f"SYNTHESIS_MODEL cross-domain summary failed: {llm_err}")

    parts = [f"{d.upper()}: {c}" for d, c in by_domain.items()]
    summary = (
        f"🧭 Cross-Domain Roadmap Synthesis: {len(tasks)} active tasks ({', '.join(parts) if parts else 'none'}), "
        f"{len(code_chunks)} technical code snippets, and {len(cw_chunks)} academic coursework notes indexed across {len(projects)} projects."
    )
    return {
        "response": summary,
        "data": {
            "open_tasks_by_domain": by_domain,
            "total_tasks": len(tasks),
            "code_chunks_count": len(code_chunks),
            "coursework_chunks_count": len(cw_chunks),
            "projects_count": len(projects),
            "model": settings.SYNTHESIS_MODEL,
        },
    }


@register_skill("chat")
async def handle_chat_skill(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Conversational fallback for greetings, questions, and non-actionable queries."""
    from backend.config import get_settings
    from backend.services.usage import record_usage
    from openai import AsyncOpenAI

    settings = get_settings()
    msg = args.get("message") or args.get("query") or "Hello! I am Compass, your persistent multi-domain AI assistant."

    if settings.NEBIUS_API_KEY and msg != "Hello! I am Compass, your persistent multi-domain AI assistant.":
        try:
            client = AsyncOpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL, timeout=10.0)
            resp: Any = await client.chat.completions.create(
                model=settings.ROUTER_MODEL,
                messages=[
                    {"role": "system", "content": "You are Compass, a smart multi-domain AI assistant managing Hackathon, Coursework, and Code. Be concise, friendly, and helpful."},
                    {"role": "user", "content": str(msg)}
                ],
                max_tokens=150,
                stream=False,
            )
            content, p_tok, c_tok = _extract_completion_result(resp, str(msg), default_completion_tokens=50)
            record_usage(settings.ROUTER_MODEL, p_tok, c_tok)
            if content and content.strip():
                return {"response": content.strip(), "data": {"type": "chat", "model": settings.ROUTER_MODEL}}
        except Exception as e:
            logger.debug(f"Chat skill LLM fallback: {e}")

    return {"response": str(msg), "data": {"type": "chat"}}
