"""
Compass — Feasibility and Triage Skill Handlers.

This is the single implementation of ``assess_feasibility`` and ``apply_triage_plan``.
Both are tenant-scoped: the caller's ``user_id`` is required.
"""

from typing import Any, Dict, Optional
import logging

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.feasibility")


def _missing_user() -> Dict[str, Any]:
    return {"success": False, "data": {}, "summary": "",
            "error": "Authenticated user required."}


def _as_int_ids(raw: Any) -> list:
    ids = []
    for i in raw or []:
        try:
            ids.append(int(i))
        except (TypeError, ValueError):
            continue
    return ids


async def _run_scoped_review(pool: Any, *, days: int, hours: float, domain: Optional[str],
                             user_id: str, include_demo: bool):
    """Non-streaming wrapper that, unlike agents.feasibility.assess_feasibility,
    passes the owner through to the task query."""
    from backend.agents.feasibility import run_feasibility_review, TriagePlan
    final: Optional[Dict[str, Any]] = None
    async for ev in run_feasibility_review(
        pool, days=days, hours_per_day=hours, domain=domain,
        user_id=user_id, include_demo=include_demo,
    ):
        if ev["type"] == "done":
            final = ev
        elif ev["type"] == "error":
            raise RuntimeError(ev["content"])
    if not final:
        raise RuntimeError("Feasibility review produced no verdict")
    return TriagePlan.model_validate(final["metadata"]["triage_plan"])


@register_skill("assess_feasibility")
async def handle_assess_feasibility(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    from backend.agents.feasibility import DEFAULT_HOURS_PER_DAY
    user_id = args.get("user_id")
    if not user_id:
        return _missing_user()
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
        plan = await _run_scoped_review(
            pool, days=days, hours=hours, domain=domain,
            user_id=str(user_id), include_demo=bool(args.get("include_demo", False)),
        )
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
    """Set deferred tasks to 'open' and drop others, only for the caller's own tasks.
    MUTATING — must be confirm-gated."""
    from backend.memory import structured
    user_id = args.get("user_id")
    if not user_id:
        return _missing_user()
    defer_ids = _as_int_ids(args.get("defer_ids"))
    drop_ids = _as_int_ids(args.get("drop_ids"))
    changed = []
    skipped = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for tid, status, label in (
                [(t, "done", "dropped") for t in drop_ids]
                + [(t, "open", "deferred") for t in defer_ids]
            ):
                row = await structured.update_task(conn, tid, owner_id=str(user_id), status=status)
                if row:
                    changed.append({"id": tid, "action": label})
                else:
                    skipped.append(tid)
    n_drop = sum(1 for c in changed if c["action"] == "dropped")
    n_defer = len(changed) - n_drop
    summary = f"Applied triage: {n_drop} dropped, {n_defer} deferred."
    if skipped:
        summary += f" Skipped {len(skipped)} task id(s) not found for this user."
    return {
        "success": True,
        "data": {"changed": changed, "skipped_ids": skipped},
        "summary": summary,
        "error": None,
    }
