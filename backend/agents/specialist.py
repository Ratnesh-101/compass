"""
Compass — Specialist Multi-Agent System.

Exposes specialized domain agents (Coursework, Research, Calendar, Memory)
coordinated by a SpecialistDispatcher.

Specialist agents perform narrow domain analysis and return structured results
to the Main Agent (Northstar). Mutations are returned as proposed_actions
and MUST be gated by Northstar's confirmation mechanism before DB execution.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("compass.agents.specialist")


# ---------------------------------------------------------------------------
# Structured Request / Response Schemas
# ---------------------------------------------------------------------------

class SpecialistRequest(BaseModel):
    """Structured request sent from Northstar (Main Agent) to Specialist Multi-Agent System."""

    capability: Literal["coursework", "research", "calendar", "memory"]
    user_goal: str
    relevant_context: Optional[Dict[str, Any]] = None
    allowed_tools: Optional[List[str]] = None


class SpecialistResult(BaseModel):
    """Structured response returned from Specialist Multi-Agent System to Northstar."""

    capability: str
    status: Literal["success", "unavailable", "error"] = "success"
    summary: str
    findings: Dict[str, Any] = Field(default_factory=dict)
    proposed_actions: List[Dict[str, Any]] = Field(default_factory=list)
    requires_confirmation: bool = False


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

    summary = "\n".join(summary_parts) if summary_parts else f"Coursework analysis completed for '{goal}'."

    return SpecialistResult(
        capability="coursework",
        status="success",
        summary=summary,
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
    from backend.skills import handle_search_web, handle_verify_deadline

    goal = request.user_goal.strip()
    findings: Dict[str, Any] = {}
    summary_parts: List[str] = []

    # 1. Determine if deadline verification or general web search
    is_deadline_query = any(k in goal.lower() for k in ["deadline", "extension", "devpost", "due date"])

    if is_deadline_query:
        try:
            ver_res = await handle_verify_deadline({"task_title": goal}, pool)
            findings["deadline_verification"] = ver_res.get("data", {})
            if ver_res.get("response"):
                summary_parts.append(ver_res["response"])
        except Exception as e:
            logger.warning(f"[ResearchSpecialist] Verify deadline failed: {e}")

    if not summary_parts:
        try:
            web_res = await handle_search_web({"query": goal}, pool)
            findings["web_results"] = web_res.get("data", {})
            if web_res.get("response"):
                summary_parts.append(web_res["response"])
        except Exception as e:
            logger.warning(f"[ResearchSpecialist] Web search failed: {e}")

    summary = "\n".join(summary_parts) if summary_parts else f"Research web query completed for '{goal}'."

    return SpecialistResult(
        capability="research",
        status="success",
        summary=summary,
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
    """Specialist Agent for calendar availability, schedule conflicts, and time-blocking.
    Directly delegates capacity and workload feasibility queries to The Realist (assess_feasibility).
    """
    from backend.skills import (
        handle_get_calendar_availability,
        handle_detect_schedule_conflicts,
        handle_assess_feasibility,
    )

    goal = request.user_goal.strip()
    findings: Dict[str, Any] = {}
    summary_parts: List[str] = []

    # 1. Feasibility & Workload Analysis (delegating directly to The Realist)
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

    # 2. Fetch calendar availability
    try:
        avail_res = await handle_get_calendar_availability({}, pool)
        findings["availability"] = avail_res.get("data", {})
        if avail_res.get("response") and not is_feasibility_query:
            summary_parts.append(avail_res["response"])
    except Exception as e:
        logger.warning(f"[CalendarSpecialist] Availability query failed: {e}")

    # 3. Detect schedule conflicts
    try:
        conf_res = await handle_detect_schedule_conflicts({}, pool)
        findings["conflicts"] = conf_res.get("data", {})
        if conf_res.get("response") and not summary_parts:
            summary_parts.append(conf_res["response"])
    except Exception as e:
        logger.warning(f"[CalendarSpecialist] Conflict check failed: {e}")

    summary = "\n".join(summary_parts) if summary_parts else f"Calendar & schedule analysis completed for '{goal}'."

    return SpecialistResult(
        capability="calendar",
        status="success",
        summary=summary,
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

    # 1. Query semantic vector chunks
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

    summary = "\n".join(summary_parts) if summary_parts else f"Memory context search completed for '{goal}'."

    return SpecialistResult(
        capability="memory",
        status="success",
        summary=summary,
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

        try:
            if cap == "coursework":
                return await run_coursework_specialist(request, pool=pool)
            elif cap == "research":
                return await run_research_specialist(request, pool=pool)
            elif cap == "calendar":
                return await run_calendar_specialist(request, pool=pool)
            elif cap == "memory":
                return await run_memory_specialist(request, pool=pool)
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
    req_cap = (capability or "memory").lower().strip()
    if req_cap not in ("coursework", "research", "calendar", "memory"):
        req_cap = "memory"

    request = SpecialistRequest(
        capability=req_cap,  # type: ignore
        user_goal=user_goal,
        relevant_context=relevant_context,
        allowed_tools=allowed_tools,
    )
    result = await SpecialistDispatcher.dispatch(request, pool=pool)
    return result.model_dump()
