"""
Compass — Specialist Multi-Agent Skill Handlers.

``assess_feasibility`` and ``apply_triage_plan`` live only in
``backend.skills.handlers.feasibility`` (tenant-scoped). Do not re-register them here:
the last registration wins in SKILL_REGISTRY.
"""

from typing import Any, Dict
import logging

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.specialist")


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
        user_id=args.get("user_id"),
        include_demo=bool(args.get("include_demo", False)),
    )

    summary = specialist_res.get("summary", "")
    return {
        "response": summary,
        "data": specialist_res,
    }
