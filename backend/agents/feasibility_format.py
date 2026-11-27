"""
Compass — Feasibility Text Builders and Formatting Helpers.

Pure formatting and text generation functions for the Realist feasibility agent
and the assess_feasibility skill handler.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def task_has_length(task: Dict[str, Any]) -> bool:
    try:
        return float(task.get("duration_minutes")) > 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def estimate_assumption_sentence(entries: List[str], max_listed: int = 6) -> str:
    """One sentence naming tasks counted at an estimated length ("Title (2h)"); '' when none."""
    if not entries:
        return ""
    listed = ", ".join(entries[:max_listed])
    if len(entries) > max_listed:
        listed += f" and {len(entries) - max_listed} more"
    return f"Tasks without a set length use estimated lengths: {listed}."


def estimate_entries(tasks: List[Dict[str, Any]], loads: List[Any], fallback: Any) -> List[str]:
    """'Title (Nh)' per task without a stored length, using the hours the plan used."""
    by_id = {load.task_id: load for load in loads}
    out: List[str] = []
    for t in tasks:
        if task_has_length(t):
            continue
        load = by_id.get(int(t.get("id", 0) or 0))
        hours = load.estimated_hours if load is not None else fallback(t)
        out.append(f"{t.get('title') or 'untitled'} ({hours:g}h)")
    return out

def task_duration_hours(task: Dict[str, Any], default: float = 0.0) -> float:
    """Return the task's stored duration in hours (duration_minutes / 60 when > 0), else `default`."""
    dm = task.get("duration_minutes")
    if dm is not None:
        try:
            val = float(dm)
            if val > 0:
                return round(val / 60.0, 2)
        except (TypeError, ValueError):
            pass
    return default

def describe_tasks(tasks: List[Dict[str, Any]]) -> str:
    """Format tasks for model prompts."""
    out = []
    for t in tasks:
        dur = f"{task_duration_hours(t):g}h" if task_has_length(t) else "unset (estimate it)"
        due = t.get("due_date")
        due_str = str(due)[:10] if due else "none"
        out.append(
            f"- id={t.get('id')} | {t.get('title')} | domain={t.get('domain')} "
            f"| priority={t.get('priority')} | duration={dur} | due={due_str}"
        )
    return "\n".join(out) if out else "(no open tasks)"


def format_bucket(label: str, tasks: List[Any], max_titles: int = 8) -> str:
    """Format a triage bucket (Keep / Defer / Drop) with task titles and hours."""
    count = len(tasks)
    if count == 0:
        return f"{label} 0"
    items: List[str] = []
    for t in tasks[:max_titles]:
        title = getattr(t, "title", None) or (t.get("title") if isinstance(t, dict) else "untitled")
        hours = getattr(t, "estimated_hours", None)
        if hours is None and isinstance(t, dict):
            hours = t.get("estimated_hours")
        if hours is None and isinstance(t, dict):
            hours = task_duration_hours(t)
        elif hours is None:
            hours = 0.0
        items.append(f"{title} ({hours:g}h)")
    if count > max_titles:
        items.append(f"and {count - max_titles} more")
    return f"{label} {count} ({', '.join(items)})"


def format_buckets_summary(keep: List[Any], defer: List[Any], drop: List[Any], max_titles: int = 8) -> str:
    """Format all three triage buckets for user-facing summary."""
    k = format_bucket("Keeping", keep, max_titles=max_titles)
    d = format_bucket("deferring", defer, max_titles=max_titles)
    dr = format_bucket("dropping", drop, max_titles=max_titles)
    return f"{k}, {d}, {dr}."


def format_empty_summary(days: int, hours_per_day: float, capacity_hours: float) -> str:
    """Plain sentence summary when there are zero open tasks."""
    return (
        f"Nothing to assess yet: you have no open tasks in Compass. "
        f"At {hours_per_day:g} hours a day for {days} days you would have {capacity_hours:g} hours "
        f"of focused time. Tell me your tasks, or add them in the Timeline, and I will check whether they fit."
    )


def format_feasibility_summary(
    plan: Any,
    *,
    days: int,
    hours_per_day: float,
    days_stated: bool = True,
    retried_all_domains: bool = False,
    workload_hours: Optional[float] = None,
) -> str:
    """Build the complete, consistent user-facing summary string."""
    v = plan.verdict
    capacity = round(max(0.5, float(days) * float(hours_per_day)), 2)
    usable_capacity = round(capacity * 0.8, 2)

    # Empty case: no tasks in any bucket and no user-supplied workload hours
    if not plan.keep and not plan.defer and not plan.drop and (workload_hours is None or workload_hours <= 0):
        return format_empty_summary(days, hours_per_day, capacity)

    # Workload-only case (no tasks in DB, user gave workload_hours)
    if not plan.keep and not plan.defer and not plan.drop and workload_hours is not None and workload_hours > 0:
        demand = v.demand_hours or workload_hours
        util_pct = round((demand / usable_capacity * 100.0), 1) if usable_capacity > 0 else 999.9
        verdict_text = "Yes, it fits" if demand <= usable_capacity else "Not all of it fits"
        summary = (
            f"{verdict_text}: {demand:g}h of work against {capacity:g}h available "
            f"({days} days × {hours_per_day:g}h/day; about {usable_capacity:g}h of that is "
            f"usable focus time after breaks, giving {util_pct}% utilisation)."
        )
        if not days_stated:
            summary += f" (I assumed the next {days} days at {hours_per_day:g} hours a day.)"
        return summary

    # Standard case with tasks
    demand = v.demand_hours
    util_pct = round((demand / usable_capacity * 100.0), 1) if usable_capacity > 0 else 999.9

    if not plan.defer and not plan.drop and demand <= usable_capacity:
        verdict_text = "Yes, it fits"
    else:
        verdict_text = "Not all of it fits"

    capacity_phrase = (
        f"{capacity:g}h available ({days} days × {hours_per_day:g}h/day; "
        f"about {usable_capacity:g}h of that is usable focus time after breaks, "
        f"{util_pct}% utilisation)"
    )
    buckets_text = format_buckets_summary(plan.keep, plan.defer, plan.drop)

    parts = [f"{verdict_text}: {demand:g}h of work against {capacity_phrase}. {buckets_text}"]
    if retried_all_domains:
        parts.append("I looked at all your open tasks.")
    if not days_stated:
        parts.append(f"(I assumed the next {days} days at {hours_per_day:g} hours a day.)")
    assumption = estimate_assumption_sentence(list(getattr(plan, "default_duration_titles", None) or []))
    if assumption:
        parts.append(assumption)

    return " ".join(parts)


def format_triage_markdown(plan: Any) -> str:
    """Format copy-pasteable artifact markdown for TriagePlan."""
    v = plan.verdict
    verdict_text = "Nothing to assess yet" if v.demand_hours == 0 else v.verdict
    lines = [
        "# Compass — Feasibility Triage",
        "",
        f"**Verdict:** {verdict_text}",
        f"**Demand:** {v.demand_hours}h  |  **Capacity:** {v.capacity_hours}h  "
        f"|  **Utilisation:** {v.utilisation_pct}%",
    ]
    if v.overcommit_hours > 0:
        lines.append(f"**Overcommitted by:** {v.overcommit_hours}h")
    lines += ["", f"_{plan.narrative}_", ""]

    for label, bucket in (("Keep", plan.keep), ("Defer", plan.defer), ("Drop", plan.drop)):
        lines.append(f"## {label} ({len(bucket)})")
        if not bucket:
            lines.append("_none_")
        for t in bucket:
            due = f" — due {t.due_date}" if t.due_date else ""
            why = f" — {t.rationale}" if t.rationale else ""
            lines.append(f"- **{t.title}** [{t.domain}] · {t.estimated_hours}h{due}{why}")
        lines.append("")

    if v.challenged_estimates:
        lines.append("## Estimates the Realist challenged")
        lines += [f"- {c}" for c in v.challenged_estimates]
        lines.append("")

    lines.append(f"_Negotiation rounds: {plan.rounds_used}_")
    if plan.degraded:
        lines.append("_Produced by the offline deterministic fallback (model provider unreachable)._")
    return "\n".join(lines)
