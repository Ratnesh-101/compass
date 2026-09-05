"""
Compass — Skills Registry & Tool Definitions.

Central registry for all skills supported by Compass. Provides a standardized
pattern for registering tools for the router and dispatching execution in orchestrator.
"""

from typing import Any, Callable, Coroutine, Dict, List
import logging

logger = logging.getLogger("compass.skills")

# ---------------------------------------------------------------------------
# Tool Definitions (OpenAI-compatible function schemas for Nemotron-3 Nano)
# ---------------------------------------------------------------------------

ADD_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_task",
        "description": "Add a new task or action item to the user's structured task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title or action item description of the task",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Domain category",
                },
                "project": {
                    "type": "string",
                    "description": "Optional name of the project this task belongs to",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format (if specified or inferred)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Priority level of the task",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional context or details for the task",
                },
            },
            "required": ["title"],
        },
    },
}

QUERY_TASKS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_tasks",
        "description": "Query or list existing tasks and deadlines by domain, project, or status.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Filter by domain",
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project name",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done", "overdue"],
                    "description": "Filter by status",
                },
            },
        },
    },
}

QUERY_CODE_CONTEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_code_context",
        "description": "Semantic search over code snippets, architecture notes, and technical memory chunks.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or technical question",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (typically 'code' or 'hackathon')",
                },
            },
            "required": ["query"],
        },
    },
}

SUMMARIZE_DAY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "summarize_day",
        "description": "Generate a daily summary or standup report across all projects and open tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to summarize in YYYY-MM-DD format, defaults to today",
                },
            },
        },
    },
}

QUERY_COURSEWORK_TASKS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_coursework_tasks",
        "description": "Query academic coursework tasks, lab submissions, and reports (e.g. CS 61C RISC-V).",
        "parameters": {
            "type": "object",
            "properties": {
                "course": {"type": "string", "description": "Optional course name or code (e.g. CS 61C)"},
                "status": {"type": "string", "enum": ["open", "overdue", "done"], "description": "Filter by status"}
            }
        }
    }
}

GET_HACKATHON_DEADLINES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_hackathon_deadlines",
        "description": "Retrieve active hackathon project deliverables, deadlines, and benchmark submissions.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Hackathon project name"}
            }
        }
    }
}

LOG_CODE_SNIPPET_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "log_code_snippet",
        "description": "Store technical architecture notes, code snippets, or configuration in vector memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The code snippet or technical summary"},
                "project": {"type": "string", "description": "Target project"},
                "tags": {"type": "string", "description": "Comma-separated tags"}
            },
            "required": ["content"]
        }
    }
}

# Registered tools exposed to the Nemotron router
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    ADD_TASK_TOOL,
    QUERY_TASKS_TOOL,
    QUERY_COURSEWORK_TASKS_TOOL,
    GET_HACKATHON_DEADLINES_TOOL,
    LOG_CODE_SNIPPET_TOOL,
    QUERY_CODE_CONTEXT_TOOL,
    SUMMARIZE_DAY_TOOL,
]


# ---------------------------------------------------------------------------
# Skill Registry Map (skill_name -> handler function)
# ---------------------------------------------------------------------------
SkillHandler = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
SKILL_REGISTRY: Dict[str, SkillHandler] = {}


def register_skill(name: str):
    """Decorator to register a skill handler function into SKILL_REGISTRY."""
    def decorator(fn: SkillHandler):
        SKILL_REGISTRY[name] = fn
        return fn
    return decorator


# ---------------------------------------------------------------------------
# Default Skill Implementations (Bridging while Rhythm completes skills)
# ---------------------------------------------------------------------------

@register_skill("query_tasks")
async def handle_query_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query tasks table via structured.list_tasks and format summary."""
    from backend.memory import structured
    domain = args.get("domain")
    status = args.get("status")

    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain=domain, status=status)

    count = len(tasks)
    d_str = f" in {domain.upper()}" if domain else ""
    s_str = f" with status '{status}'" if status else ""
    summary = f"Found {count} task(s){d_str}{s_str}."
    return {
        "response": summary,
        "data": {"tasks": tasks, "count": count},
    }


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

    try:
        async with pool.acquire() as conn:
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
                resp = await client.chat.completions.create(
                    model=settings.SKILL_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a senior technical coding assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=384,
                )
                p_tok = resp.usage.prompt_tokens if resp.usage else len(prompt.split()) * 2
                c_tok = resp.usage.completion_tokens if resp.usage else 100
                record_usage(settings.SKILL_MODEL, p_tok, c_tok)
                raw_content = resp.choices[0].message.content
                summary = raw_content.strip() if raw_content else f"Retrieved {count} relevant memory chunk(s) for query: '{query}'."
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
            resp = await client.chat.completions.create(
                model=settings.SYNTHESIS_MODEL,
                messages=[
                    {"role": "system", "content": "You provide prioritized, executive daily standup summaries."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=256,
            )
            p_tok = resp.usage.prompt_tokens if resp.usage else len(prompt.split()) * 2
            c_tok = resp.usage.completion_tokens if resp.usage else 80
            record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)
            raw_content = resp.choices[0].message.content
            summary = raw_content.strip() if raw_content else f"Daily summary: {len(tasks)} total open task(s)."
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


@register_skill("query_coursework_tasks")
async def handle_query_coursework_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query coursework tasks such as CS 61C labs, reports, and homework."""
    from backend.memory import structured
    status = args.get("status")
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain="coursework", status=status)
    count = len(tasks)
    summary = f"📚 Coursework: Found {count} task(s) including RISC-V reports and Logisim labs."
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


@register_skill("get_hackathon_deadlines")
async def handle_get_hackathon_deadlines(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Retrieve urgent hackathon deliverables and demo benchmark deadlines."""
    from backend.memory import structured
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain="hackathon")
    count = len(tasks)
    summary = f"🚀 Hackathon: {count} active deliverables for Nebius Token Factory benchmark."
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


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


async def dispatch_skill(skill_name: str, args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Dispatch execution to registered skill handler or return fallback response."""
    if skill_name in SKILL_REGISTRY:
        return await SKILL_REGISTRY[skill_name](args, pool)
    raise ValueError(f"Skill '{skill_name}' is not registered in SKILL_REGISTRY.")

