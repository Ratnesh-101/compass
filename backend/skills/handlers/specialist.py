"""
Compass — Specialist Multi-Agent and Feasibility Skill Handlers.
"""

from typing import Any, Dict
import logging

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.specialist")


@register_skill("assess_feasibility")
async def handle_assess_feasibility(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    from backend.agents.feasibility import assess_feasibility, DEFAULT_HOURS_PER_DAY
    try:
        days = int(args.get("days") or 5)
        hours = float(args.get("hours_per_day") or DEFAULT_HOURS_PER_DAY)
    except (TypeError, ValueError):
        days, hours = 5, DEFAULT_HOURS_PER_DAY
    days = min(max(days, 1), 90)
    hours = min(max(hours, 0.5), 16.0)

    domain = args.get("domain")
    if domain not in ("hackathon", "coursework", "code", "general"):
        domain = None

    try:
        plan = await assess_feasibility(pool, days=days, hours_per_day=hours, domain=domain)
    except Exception as e:
        logger.error("Feasibility review failed: %s", e, exc_info=True)
        return {"success": False, "data": {}, "summary": "",
                "error": "Could not complete the feasibility review."}

    v = plan.verdict
    return {
        "success": True,
        "data": {
            "triage_plan": plan.model_dump(),
            "artifact_markdown": plan.as_markdown(),
            "rounds_used": plan.rounds_used,
            "degraded": plan.degraded,
        },
        "summary": (
            f"{v.verdict}: {v.demand_hours}h of work against {v.capacity_hours}h "
            f"available ({v.utilisation_pct}% utilisation). "
            f"Keeping {len(plan.keep)}, deferring {len(plan.defer)}, "
            f"dropping {len(plan.drop)}. {plan.narrative}"
        ),
        "error": None,
    }


@register_skill("apply_triage_plan")
async def handle_apply_triage_plan(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Set deferred tasks to 'open' with pushed dates and drop others.
    MUTATING — must be confirm-gated."""
    from backend.memory import structured
    defer_ids = [int(i) for i in (args.get("defer_ids") or [])]
    drop_ids = [int(i) for i in (args.get("drop_ids") or [])]
    changed = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for tid in drop_ids:
                await structured.update_task_status(conn, tid, "done")
                changed.append({"id": tid, "action": "dropped"})
            for tid in defer_ids:
                await structured.update_task_status(conn, tid, "open")
                changed.append({"id": tid, "action": "deferred"})
    return {
        "success": True,
        "data": {"changed": changed},
        "summary": f"Applied triage: {len(drop_ids)} dropped, {len(defer_ids)} deferred.",
        "error": None,
    }


@register_skill("delegate_to_specialist")
async def handle_delegate_to_specialist(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Delegate a specialized sub-task to the Specialist Multi-Agent System."""
    from backend.agents.specialist import run_specialist_task

    capability = args.get("capability") or "memory"
    task_description = args.get("task_description") or args.get("goal") or "Specialized query"

    specialist_res = await run_specialist_task(
        capability=capability,
        user_goal=task_description,
        pool=pool,
    )

    summary = specialist_res.get("summary", "")
    return {
        "response": summary,
        "data": specialist_res,
    }
