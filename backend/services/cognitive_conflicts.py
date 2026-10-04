"""
Compass — Proactive Cognitive Conflict Detection Service.
Evaluates cross-domain collisions, capacity overcommit, and generates actionable arbitration advice.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("compass.cognitive_conflicts")

_PRIORITY_DEFAULT_HOURS: Dict[str, float] = {
    "urgent": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}

_DOMAIN_EFFORT_MULTIPLIERS: Dict[str, float] = {
    "hackathon": 1.25,
    "code": 1.1,
    "coursework": 1.0,
    "general": 0.8,
}


def _ensure_utc(dt: datetime | str | date | Dict[str, Any]) -> datetime:
    """Normalize input datetime to UTC timezone-aware datetime."""
    if isinstance(dt, dict):
        raw = dt.get("dateTime") or dt.get("date") or dt.get("start") or dt.get("end")
        if raw is not None:
            return _ensure_utc(raw)
        raise ValueError(f"Cannot extract datetime from dict: {dt}")
    if isinstance(dt, str):
        clean_str = dt.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(clean_str)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            d = date.fromisoformat(clean_str[:10])
            return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
    elif isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc)
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError(f"Cannot convert {type(dt)} to UTC datetime")


def estimate_task_effort_hours(task: Dict[str, Any]) -> float:
    """Extract or estimate effort in hours for a task.

    Checks:
    1. Explicit duration_minutes field if present and > 0.
    2. Explicit text hints in title or notes (e.g. '36-hour', '8 hrs', '4h', '90 min').
    3. Heuristic fallback based on priority and domain.
    """
    # 1. Direct duration_minutes
    dur_min = task.get("duration_minutes")
    if dur_min is not None:
        try:
            val = float(dur_min)
            if val > 0:
                return round(val / 60.0, 2)
        except (ValueError, TypeError):
            pass

    # 2. Textual hints in title or notes (capped length and linear regex to avoid ReDoS)
    text_corpus = f"{task.get('title', '')} {task.get('notes', '')} {task.get('description', '')}"[:500]
    if text_corpus.strip():
        normalized_corpus = text_corpus.replace("-", " ")
        m_hr = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b', normalized_corpus, re.IGNORECASE)
        if m_hr:
            try:
                hrs = float(m_hr.group(1))
                if 0.25 <= hrs <= 100.0:
                    return round(hrs, 2)
            except ValueError:
                pass

        m_min = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)\b', normalized_corpus, re.IGNORECASE)
        if m_min:
            try:
                mins = float(m_min.group(1))
                if mins > 0:
                    return round(mins / 60.0, 2)
            except ValueError:
                pass

    # 3. Fallback heuristic
    priority = str(task.get("priority", "medium")).lower().strip()
    domain = str(task.get("domain", "general")).lower().strip()
    base_hrs = _PRIORITY_DEFAULT_HOURS.get(priority, 2.0)
    mult = _DOMAIN_EFFORT_MULTIPLIERS.get(domain, 1.0)
    return round(base_hrs * mult, 2)


def check_proactive_cognitive_conflicts(
    proposed_task: Dict[str, Any],
    existing_tasks: Sequence[Dict[str, Any]],
    external_events: Optional[Sequence[Dict[str, Any]]] = None,
    current_time: Optional[datetime | str] = None,
    daily_capacity_hours: float = 8.0,
    weekend_capacity_hours: float = 16.0,
) -> Optional[Dict[str, Any]]:
    """Proactively detect cross-domain collisions, capacity overcommit, and deadline clashes."""
    now_utc = _ensure_utc(current_time) if current_time else datetime.now(timezone.utc)
    proposed_title = str(proposed_task.get("title", "Untitled Task")).strip()
    proposed_domain = str(proposed_task.get("domain", "general")).lower().strip()
    proposed_hours = estimate_task_effort_hours(proposed_task)

    # 1. Determine target date anchor
    target_d: Optional[date] = None
    raw_due = proposed_task.get("due_date")
    if raw_due:
        try:
            target_d = date.fromisoformat(str(raw_due)[:10])
        except Exception:
            target_d = None

    if not target_d and proposed_task.get("scheduled_start"):
        try:
            target_d = _ensure_utc(proposed_task["scheduled_start"]).date()
        except Exception:
            target_d = None

    title_lower = proposed_title.lower()
    is_weekend_cue = "weekend" in title_lower or "saturday" in title_lower or "sunday" in title_lower
    if not target_d and is_weekend_cue:
        days_ahead = (5 - now_utc.weekday()) % 7
        if days_ahead == 0 and now_utc.weekday() != 5:
            days_ahead = 7
        target_d = (now_utc + timedelta(days=days_ahead)).date()

    if not target_d:
        if proposed_hours < 16.0:
            return None
        days_ahead = (5 - now_utc.weekday()) % 7
        target_d = (now_utc + timedelta(days=days_ahead)).date()

    is_weekend = target_d.weekday() in (5, 6) or is_weekend_cue
    if is_weekend:
        if target_d.weekday() == 6:  # Sunday
            sat_d = target_d - timedelta(days=1)
            sun_d = target_d
        elif target_d.weekday() == 5:  # Saturday
            sat_d = target_d
            sun_d = target_d + timedelta(days=1)
        else:
            sat_d = target_d
            sun_d = target_d + timedelta(days=1)
        scope_dates = {sat_d, sun_d}
        capacity_limit = weekend_capacity_hours * 2.0
    else:
        scope_dates = {target_d}
        capacity_limit = daily_capacity_hours

    cross_domain_conflicts: List[Dict[str, Any]] = []
    same_domain_tasks: List[Dict[str, Any]] = []
    cross_domain_hours = 0.0
    same_domain_hours = 0.0

    for t in existing_tasks:
        st = str(t.get("status", "open")).lower().strip()
        if st in ("done", "completed", "closed"):
            continue
        if proposed_task.get("id") and t.get("id") == proposed_task.get("id"):
            continue

        t_due = t.get("due_date")
        t_date: Optional[date] = None
        if t_due:
            try:
                t_date = date.fromisoformat(str(t_due)[:10])
            except Exception:
                pass
        if not t_date and t.get("scheduled_start"):
            try:
                t_date = _ensure_utc(t["scheduled_start"]).date()
            except Exception:
                pass

        if t_date and t_date in scope_dates:
            t_hrs = estimate_task_effort_hours(t)
            t_domain = str(t.get("domain", "general")).lower().strip()

            if t_domain != proposed_domain:
                cross_domain_conflicts.append({
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "domain": t_domain,
                    "due_date": str(t_due) if t_due else t_date.isoformat(),
                    "priority": t.get("priority", "medium"),
                    "estimated_hours": t_hrs,
                })
                cross_domain_hours += t_hrs
            else:
                same_domain_tasks.append(t)
                same_domain_hours += t_hrs

    external_busy_hours = 0.0
    if external_events:
        for ev in external_events:
            ev_start = ev.get("start") or ev.get("scheduled_start")
            ev_end = ev.get("end") or ev.get("scheduled_end")
            if ev_start and ev_end:
                try:
                    s_dt = _ensure_utc(ev_start)
                    e_dt = _ensure_utc(ev_end)
                    if s_dt.date() in scope_dates or e_dt.date() in scope_dates:
                        dur_hrs = max(0.0, (e_dt - s_dt).total_seconds() / 3600.0)
                        external_busy_hours += dur_hrs
                except Exception:
                    continue

    total_demand = round(proposed_hours + cross_domain_hours + same_domain_hours + external_busy_hours, 1)
    is_overcommitted = total_demand > capacity_limit
    has_cross_domain_clash = len(cross_domain_conflicts) > 0

    if not is_overcommitted and not (has_cross_domain_clash and proposed_hours >= 4.0):
        return None

    overcommit_hrs = max(0.0, round(total_demand - capacity_limit, 1))
    overcommit_pct = int(round((total_demand / max(1.0, capacity_limit)) * 100))

    timeframe_str = "weekend" if is_weekend else f"day ({target_d.strftime('%a, %b %d')})"
    alert_lines = [
        "⚡ Cognitive Conflict Alert:",
    ]

    if cross_domain_conflicts:
        conflict_summaries = [
            f"'{c['title']}' [{c['domain'].upper()}] (due {c['due_date']}, est. {c['estimated_hours']:.1f}h)"
            for c in cross_domain_conflicts[:3]
        ]
        alert_lines.append(
            f"• Cross-Domain Collision: You have {len(cross_domain_conflicts)} active commitment(s) in other domains: {'; '.join(conflict_summaries)}."
        )

    alert_lines.append(
        f"• Capacity Math: Total demand is {total_demand}h against {capacity_limit:.0f}h available {timeframe_str} capacity ({overcommit_pct}% load, +{overcommit_hrs}h overcommit)."
    )

    if cross_domain_conflicts:
        primary_conflict = cross_domain_conflicts[0]
        shifted_target = target_d - timedelta(days=2 if not is_weekend else 2)
        suggested_action = (
            f"Propose shifting '{primary_conflict['title']}' prep to {shifted_target.strftime('%A, %b %d')} "
            f"to protect focus bandwidth for '{proposed_title}'."
        )
        alert_lines.append(f"• Suggested Arbitration: {suggested_action}")
    else:
        suggested_action = (
            f"Propose splitting '{proposed_title}' ({proposed_hours}h) into staged milestones or deferring non-urgent backlog."
        )
        alert_lines.append(f"• Suggested Arbitration: {suggested_action}")

    alert_message = "\n".join(alert_lines)

    return {
        "has_conflict": True,
        "conflict_type": "cross_domain_capacity_overload" if (is_overcommitted and has_cross_domain_clash) else ("cross_domain_collision" if has_cross_domain_clash else "capacity_overload"),
        "target_date": target_d.isoformat(),
        "is_weekend": is_weekend,
        "timeframe": timeframe_str,
        "proposed_task": {
            "title": proposed_title,
            "domain": proposed_domain,
            "estimated_hours": proposed_hours,
        },
        "conflicting_cross_domain_tasks": cross_domain_conflicts,
        "total_demand_hours": total_demand,
        "capacity_limit_hours": capacity_limit,
        "overcommit_hours": overcommit_hrs,
        "overcommit_pct": overcommit_pct,
        "suggested_action": suggested_action,
        "alert_message": alert_message,
    }
