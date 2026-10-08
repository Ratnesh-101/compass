"""
Compass — Specialist Multi-Agent System.

Exposes specialized domain agents (Coursework, Research, Calendar, Memory)
coordinated by a SpecialistDispatcher.

Specialist agents perform narrow domain analysis, retrieve relevant domain context,
and generate specialized expert responses tailored to their specific domain.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("compass.agents.specialist")


# ---------------------------------------------------------------------------
# Structured Request / Response Schemas
# ---------------------------------------------------------------------------

class SpecialistRequest(BaseModel):
    """Structured request sent to Specialist Multi-Agent System."""

    capability: Literal["coursework", "research", "calendar", "memory", "auto-dispatcher", "auto"]
    user_goal: str
    relevant_context: Optional[Dict[str, Any]] = None
    allowed_tools: Optional[List[str]] = None


class SpecialistResult(BaseModel):
    """Structured response returned from Specialist Multi-Agent System."""

    capability: str
    status: Literal["success", "unavailable", "error"] = "success"
    summary: str
    findings: Dict[str, Any] = Field(default_factory=dict)
    proposed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    requires_confirmation: bool = False


# ---------------------------------------------------------------------------
# Specialist Response LLM Synthesis Helper
# ---------------------------------------------------------------------------

async def _synthesize_specialist_response(
    capability: str,
    user_goal: str,
    raw_findings: Dict[str, Any],
    fallback_summary: str,
) -> str:
    """Synthesize a domain-expert response for the given capability and findings using LLM."""
    try:
        from openai import AsyncOpenAI
        from backend.config import get_settings

        settings = get_settings()
        if not settings.NEBIUS_API_KEY:
            return fallback_summary

        spec_prompts = {
            "calendar": (
                "You are Compass's Calendar & Scheduling Specialist Agent. "
                "Your sole expertise is schedule management, upcoming deadlines, calendar availability, conflict detection, and workload feasibility. "
                "Use the provided workspace context (active tasks, deadlines, busy windows, availability) to answer the user's specific query directly, accurately, and thoroughly. "
                "Explicitly detail specific task titles, due dates, priorities, or time slots relevant to their question. "
                "Never reply with raw error strings like 'task_id is required' or raw unformatted data dumps. "
                "Format your response with clear Markdown formatting."
            ),
            "coursework": (
                "You are Compass's Academic & Coursework Specialist Agent. "
                "Your sole expertise is academic assignments, lab notes, exams, hardware synthesis reports, and CS 61C coursework context. "
                "Use the retrieved coursework context, tasks, and lab notes to answer the user's question with educational clarity and precision."
            ),
            "research": (
                "You are Compass's Research Specialist Agent. "
                "Your sole expertise is real-time web search, hackathon rules, Devpost guidelines, technical verification, and external documentation. "
                "Use the retrieved web search results, hackathon tasks, and workspace context to answer the user's research query directly, accurately, and thoroughly."
            ),
            "memory": (
                "You are Compass's Memory & Context Specialist Agent. "
                "Your sole expertise is long-term memory recall, 768-dim Matryoshka vector embeddings, past session decisions, and code architecture context. "
                "Use the retrieved vector memory chunks and task backlog history to answer the user's question, citing specific facts and context."
            ),
        }

        system_prompt = spec_prompts.get(
            capability,
            f"You are Compass's {capability.title()} Specialist Agent. Answer the user's query specifically using the retrieved domain context."
        )

        findings_str = json.dumps(raw_findings, default=str)[:3500]
        user_prompt = (
            f"USER QUERY: {user_goal}\n\n"
            f"RETRIEVED DOMAIN FINDINGS & CONTEXT:\n{findings_str}\n\n"
            f"Please provide a comprehensive, domain-expert response addressing the user's question directly."
        )

        client = AsyncOpenAI(
            api_key=settings.NEBIUS_API_KEY,
            base_url=settings.NEBIUS_BASE_URL,
            timeout=25.0,
        )
        resp = await client.chat.completions.create(
            model=settings.ROUTER_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1000,
            temperature=0.5,
        )
        content = resp.choices[0].message.content if resp.choices else ""
        if content and content.strip():
            return content.strip()
    except Exception as e:
        logger.warning(f"[_synthesize_specialist_response] LLM call failed for {capability}: {e}")

    return fallback_summary


# ---------------------------------------------------------------------------
# 1. Coursework Specialist Agent
# ---------------------------------------------------------------------------

async def run_coursework_specialist(
    request: SpecialistRequest, pool: Any = None
) -> SpecialistResult:
    """Specialist Agent for academic coursework, lab notes, and assignment tracking."""
    from backend.skills import (
        handle_query_coursework_tasks,
        handle_query_coursework_notes,
    )

    goal = request.user_goal.strip()
    findings: Dict[str, Any] = {}
    summary_parts: List[str] = []

    # 1. Query coursework tasks
    try:
        task_res = await handle_query_coursework_tasks({"course": goal}, pool)
        findings["coursework_tasks"] = task_res.get("data", {})
        if task_res.get("response"):
            summary_parts.append(task_res["response"])
    except Exception as e:
        logger.warning(f"[CourseworkSpecialist] Task query failed: {e}")

    # 2. Query coursework notes / lab context
    try:
        notes_res = await handle_query_coursework_notes({"query": goal}, pool)
        findings["coursework_notes"] = notes_res.get("data", {})
        if notes_res.get("response") and (not summary_parts or notes_res["response"] != summary_parts[-1]):
            summary_parts.append(notes_res["response"])
    except Exception as e:
        logger.warning(f"[CourseworkSpecialist] Notes query failed: {e}")

    fallback_summary = "\n".join(summary_parts) if summary_parts else f"Coursework analysis completed for '{goal}'."
    synthesized_summary = await _synthesize_specialist_response("coursework", goal, findings, fallback_summary)

    return SpecialistResult(
        capability="coursework",
        status="success",
        summary=synthesized_summary,
        findings=findings,
        proposed_actions=[],
        requires_confirmation=False,
    )


# ---------------------------------------------------------------------------
# 2. Research Specialist Agent
# ---------------------------------------------------------------------------

async def run_research_specialist(
    request: SpecialistRequest, pool: Any = None
) -> SpecialistResult:
    """Specialist Agent for real-time web search, deadline verification, and URL research."""
    from backend.skills import handle_search_web

    goal = request.user_goal.strip()
    findings: Dict[str, Any] = {}
    summary_parts: List[str] = []

    # 1. Gather database task / deadline context related to research/hackathons
    try:
        if pool:
            async with pool.acquire() as conn:
                task_rows = await conn.fetch(
                    """
                    SELECT title, domain, due_date, status, priority, notes
                    FROM tasks
                    WHERE domain IN ('hackathon', 'general', 'code')
                    ORDER BY due_date ASC NULLS LAST
                    LIMIT 10
                    """
                )
                findings["tracked_deliverables"] = [
                    {
                        "title": r["title"],
                        "domain": r["domain"],
                        "due_date": str(r["due_date"]) if r["due_date"] else "Unscheduled",
                        "status": r["status"],
                        "priority": r["priority"],
                        "notes": r["notes"],
                    }
                    for r in task_rows
                ]
    except Exception as e:
        logger.warning(f"[ResearchSpecialist] Database task fetch failed: {e}")

    # 2. Perform real web search via Tavily
    try:
        web_res = await handle_search_web({"query": goal}, pool)
        if isinstance(web_res, dict):
            findings["web_results"] = web_res.get("data", {})
            if web_res.get("response"):
                summary_parts.append(web_res["response"])
    except Exception as e:
        logger.warning(f"[ResearchSpecialist] Web search failed: {e}")

    fallback_summary = "\n".join(summary_parts) if summary_parts else f"Research web query completed for '{goal}'."
    synthesized_summary = await _synthesize_specialist_response("research", goal, findings, fallback_summary)

    return SpecialistResult(
        capability="research",
        status="success",
        summary=synthesized_summary,
        findings=findings,
        proposed_actions=[],
        requires_confirmation=False,
    )


# ---------------------------------------------------------------------------
# 3. Calendar / Scheduling Specialist Agent
# ---------------------------------------------------------------------------

async def run_calendar_specialist(
    request: SpecialistRequest, pool: Any = None
) -> SpecialistResult:
    """Specialist Agent for calendar availability, schedule conflicts, deadlines, and time-blocking."""
    from backend.skills import (
        handle_get_calendar_availability,
        handle_detect_schedule_conflicts,
        handle_assess_feasibility,
    )

    goal = request.user_goal.strip()
    findings: Dict[str, Any] = {}
    summary_parts: List[str] = []

    # 1. Fetch active tasks and deadlines directly from database
    try:
        if pool:
            async with pool.acquire() as conn:
                task_rows = await conn.fetch(
                    """
                    SELECT id, title, domain, due_date, status, priority, duration_minutes, notes
                    FROM tasks
                    WHERE status != 'completed'
                    ORDER BY due_date ASC NULLS LAST, priority DESC
                    LIMIT 15
                    """
                )
                findings["active_deadlines_and_tasks"] = [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "domain": r["domain"],
                        "due_date": str(r["due_date"]) if r["due_date"] else "Unscheduled",
                        "status": r["status"],
                        "priority": r["priority"],
                        "duration_minutes": r["duration_minutes"] or 60,
                        "notes": r["notes"],
                    }
                    for r in task_rows
                ]
    except Exception as e:
        logger.warning(f"[CalendarSpecialist] Active task fetch failed: {e}")

    # 2. Feasibility & Workload Analysis if query implies capacity / triage
    is_feasibility_query = any(k in goal.lower() for k in [
        "feasible", "feasibility", "capacity", "overload", "hours per day",
        "workload", "triage", "can i finish", "enough time", "burnout"
    ])
    if is_feasibility_query:
        try:
            feas_res = await handle_assess_feasibility({"days": 7, "hours_per_day": 4.0}, pool)
            findings["feasibility_assessment"] = feas_res.get("data", {})
            if feas_res.get("response"):
                summary_parts.append(feas_res["response"])
        except Exception as e:
            logger.warning(f"[CalendarSpecialist] Feasibility assessment failed: {e}")

    # 3. Fetch calendar availability
    try:
        avail_res = await handle_get_calendar_availability({}, pool)
        findings["availability"] = avail_res.get("data", {})
        if avail_res.get("response") and not is_feasibility_query:
            summary_parts.append(avail_res["response"])
    except Exception as e:
        logger.warning(f"[CalendarSpecialist] Availability query failed: {e}")

    # 4. Detect schedule conflicts
    try:
        conf_res = await handle_detect_schedule_conflicts({}, pool)
        findings["conflicts"] = conf_res.get("data", {})
        if conf_res.get("response") and not summary_parts:
            summary_parts.append(conf_res["response"])
    except Exception as e:
        logger.warning(f"[CalendarSpecialist] Conflict check failed: {e}")

    fallback_summary = "\n".join(summary_parts) if summary_parts else f"Calendar & schedule analysis completed for '{goal}'."
    synthesized_summary = await _synthesize_specialist_response("calendar", goal, findings, fallback_summary)

    return SpecialistResult(
        capability="calendar",
        status="success",
        summary=synthesized_summary,
        findings=findings,
        proposed_actions=[],
        requires_confirmation=False,
    )


# ---------------------------------------------------------------------------
# 4. Memory / Context Specialist Agent
# ---------------------------------------------------------------------------

async def run_memory_specialist(
    request: SpecialistRequest, pool: Any = None
) -> SpecialistResult:
    """Specialist Agent for long-term memory retrieval, HNSW vector search, and summaries."""
    from backend.skills import (
        handle_query_code_context,
        handle_query_tasks,
    )

    goal = request.user_goal.strip()
    findings: Dict[str, Any] = {}
    summary_parts: List[str] = []

    # 1. Query semantic vector chunks (768-dim Matryoshka embeddings)
    try:
        vec_res = await handle_query_code_context({"query": goal}, pool)
        findings["vector_memory"] = vec_res.get("data", {})
        if vec_res.get("response"):
            summary_parts.append(vec_res["response"])
    except Exception as e:
        logger.warning(f"[MemorySpecialist] Vector memory query failed: {e}")

    # 2. Query task backlog
    try:
        tasks_res = await handle_query_tasks({}, pool)
        findings["task_backlog"] = tasks_res.get("data", {})
        if tasks_res.get("response") and not summary_parts:
            summary_parts.append(tasks_res["response"])
    except Exception as e:
        logger.warning(f"[MemorySpecialist] Task backlog query failed: {e}")

    fallback_summary = "\n".join(summary_parts) if summary_parts else f"Memory context search completed for '{goal}'."
    synthesized_summary = await _synthesize_specialist_response("memory", goal, findings, fallback_summary)

    return SpecialistResult(
        capability="memory",
        status="success",
        summary=synthesized_summary,
        findings=findings,
        proposed_actions=[],
        requires_confirmation=False,
    )


# ---------------------------------------------------------------------------
# 5. Specialist Multi-Agent Dispatcher
# ---------------------------------------------------------------------------

class SpecialistDispatcher:
    """Central router for delegating specialized tasks to domain agents."""

    @staticmethod
    async def dispatch(
        request: SpecialistRequest, pool: Any = None
    ) -> SpecialistResult:
        """Route SpecialistRequest to the appropriate specialist agent safely."""
        cap = request.capability.lower().strip()
        logger.info(f"[SpecialistDispatcher] Dispatching capability='{cap}' for goal='{request.user_goal[:60]}'")

        # Handle Auto Dispatcher intent routing
        if cap in ("auto", "auto-dispatcher", "autodispatcher", "dispatcher"):
            goal_lower = request.user_goal.lower()
            if any(k in goal_lower for k in ["course", "hw", "lab", "exam", "assignment", "cs 61c", "homework"]):
                cap = "coursework"
            elif any(k in goal_lower for k in ["research", "search", "rule", "web", "devpost", "verify", "deadline"]):
                cap = "research"
            elif any(k in goal_lower for k in ["calendar", "schedule", "free time", "slot", "meet", "conflict", "feasible", "capacity"]):
                cap = "calendar"
            else:
                cap = "memory"
            logger.info(f"[SpecialistDispatcher] Auto Dispatcher inferred capability='{cap}'")
            request = SpecialistRequest(
                capability=cap,  # type: ignore
                user_goal=request.user_goal,
                relevant_context=request.relevant_context,
                allowed_tools=request.allowed_tools,
            )

        task_created_header = ""
        from backend.router import is_task_mutation_request, _extract_task_creation_args
        from backend.orchestrator import _parse_iso_date
        from backend.memory import structured

        if pool and is_task_mutation_request(request.user_goal):
            try:
                task_args = _extract_task_creation_args(request.user_goal)
                p_due = _parse_iso_date(task_args.get("due_date"))
                async with pool.acquire() as conn:
                    created = await structured.create_task(
                        conn,
                        domain=task_args.get("domain", "general"),
                        title=task_args.get("title", request.user_goal),
                        due_date=p_due,
                        status=task_args.get("status", "open"),
                        priority=task_args.get("priority", "medium"),
                    )
                    if created:
                        task_created_header = (
                            f"✅ **Created deliverable**: **{created.get('title')}** "
                            f"(Domain: **{created.get('domain')}** | Due: **{created.get('due_date') or 'Unscheduled'}** | Priority: **{created.get('priority')}**)\n\n"
                        )
            except Exception as ex:
                logger.warning(f"[SpecialistDispatcher] Task creation execution failed: {ex}")

        try:
            if cap == "coursework":
                res = await run_coursework_specialist(request, pool=pool)
            elif cap == "research":
                res = await run_research_specialist(request, pool=pool)
            elif cap == "calendar":
                res = await run_calendar_specialist(request, pool=pool)
            elif cap == "memory":
                res = await run_memory_specialist(request, pool=pool)
            else:
                logger.warning(f"[SpecialistDispatcher] Unknown capability requested: {cap}")
                return SpecialistResult(
                    capability=cap,
                    status="unavailable",
                    summary=f"Specialist capability '{cap}' is currently unavailable.",
                    findings={},
                    proposed_actions=[],
                    requires_confirmation=False,
                )

            if task_created_header:
                res.summary = task_created_header + res.summary
            return res
        except Exception as e:
            logger.error(f"[SpecialistDispatcher] Specialist execution error for {cap}: {e}", exc_info=True)
            return SpecialistResult(
                capability=cap,
                status="error",
                summary=f"That capability is currently unavailable ({e}).",
                findings={},
                proposed_actions=[],
                requires_confirmation=False,
            )


# Clean functional entry point compatible with existing project interface patterns
async def run_specialist_task(
    capability: str,
    user_goal: str,
    relevant_context: Optional[Dict[str, Any]] = None,
    allowed_tools: Optional[List[str]] = None,
    pool: Any = None,
) -> Dict[str, Any]:
    """Canonical helper function for delegating a specialized task."""
    req_cap = (capability or "auto-dispatcher").lower().strip()
    if req_cap not in ("coursework", "research", "calendar", "memory", "auto-dispatcher", "auto"):
        req_cap = "auto-dispatcher"

    request = SpecialistRequest(
        capability=req_cap,  # type: ignore
        user_goal=user_goal,
        relevant_context=relevant_context,
        allowed_tools=allowed_tools,
    )
    result = await SpecialistDispatcher.dispatch(request, pool=pool)
    return result.model_dump()
