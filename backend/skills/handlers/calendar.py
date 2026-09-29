"""
Compass — Calendar and Scheduling Skill Handlers.
"""

from typing import Any, Dict, List
import logging
from datetime import datetime, date, timedelta, timezone

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.calendar")


@register_skill("get_calendar_availability")
async def handle_get_calendar_availability(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query free/busy windows and existing schedule blocks from Google Calendar & tasks."""
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import get_available_windows
    from backend.memory.structured import get_scheduling_preferences

    start_str = args.get("start_date")
    end_str = args.get("end_date")

    now = datetime.now(timezone.utc)
    if start_str:
        try:
            start_dt = datetime.combine(date.fromisoformat(start_str[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            start_dt = now
    else:
        start_dt = now

    if end_str:
        try:
            end_dt = datetime.combine(date.fromisoformat(end_str[:10]), datetime.max.time(), tzinfo=timezone.utc)
        except Exception:
            end_dt = start_dt + timedelta(days=7)
    else:
        end_dt = start_dt + timedelta(days=7)

    busy = await get_calendar_freebusy(start_dt, end_dt, pool=pool)

    prefs: Dict[str, Any] = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                prefs = await get_scheduling_preferences(conn)
        except Exception:
            pass

    raw_buf = prefs.get("buffer_minutes", 15)
    buffer_minutes = int(raw_buf) if isinstance(raw_buf, (int, str)) else 15
    free_windows = get_available_windows(
        busy,
        start_dt,
        end_dt,
        work_start_time=str(prefs.get("work_start_time", "09:00:00")),
        work_end_time=str(prefs.get("work_end_time", "18:00:00")),
        work_days=list(prefs.get("work_days", [1, 2, 3, 4, 5])),
        buffer_minutes=buffer_minutes,
    )

    summary = (
        f"📅 Calendar Availability ({start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}):\n"
        f"• {len(busy)} busy event(s)/commitments\n"
        f"• {len(free_windows)} available focus window(s) within working hours"
    )

    return {
        "response": summary,
        "data": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "busy_count": len(busy),
            "busy_intervals": busy,
            "free_windows_count": len(free_windows),
            "free_windows": [
                {"start": w.start.isoformat(), "end": w.end.isoformat(), "duration_minutes": w.duration_minutes}
                for w in free_windows
            ],
        },
    }


@register_skill("propose_schedule")
async def handle_propose_schedule(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Run deterministic interval slot allocation for pending tasks."""
    from backend.memory.structured import list_tasks, get_scheduling_preferences, get_all_dependencies_map
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import get_available_windows, allocate_task_slots

    target_date_str = args.get("target_date")
    domain = args.get("domain")
    task_ids = args.get("task_ids")

    now = datetime.now(timezone.utc)
    if target_date_str:
        try:
            start_dt = datetime.combine(date.fromisoformat(target_date_str[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            start_dt = now
    else:
        start_dt = now
    end_dt = start_dt + timedelta(days=7)

    tasks: List[Dict[str, Any]] = []
    dep_map: Dict[int, List[int]] = {}
    prefs: Dict[str, Any] = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}

    if pool is not None:
        user_id = args.get("user_id")
        async with pool.acquire() as conn:
            prefs = await get_scheduling_preferences(conn)
            dep_map = await get_all_dependencies_map(conn)
            if task_ids:
                all_tasks = await list_tasks(conn, domain=domain, user_id=user_id)
                id_set = set(task_ids)
                tasks = [t for t in all_tasks if t["id"] in id_set]
            else:
                tasks = await list_tasks(conn, domain=domain, status="open", user_id=user_id)

    busy = await get_calendar_freebusy(start_dt, end_dt, pool=pool)
    raw_buf = prefs.get("buffer_minutes", 15)
    buffer_minutes = int(raw_buf) if isinstance(raw_buf, (int, str)) else 15
    free_windows = get_available_windows(
        busy,
        start_dt,
        end_dt,
        work_start_time=str(prefs.get("work_start_time", "09:00:00")),
        work_end_time=str(prefs.get("work_end_time", "18:00:00")),
        work_days=list(prefs.get("work_days", [1, 2, 3, 4, 5])),
        buffer_minutes=buffer_minutes,
    )

    allocation = allocate_task_slots(
        tasks,
        free_windows,
        buffer_minutes=buffer_minutes,
        dependencies=dep_map,
    )

    scheduled_list = allocation["scheduled"]
    lines = [f"⚡ Proposed Schedule Plan: {allocation['summary']}"]
    for s in scheduled_list:
        lines.append(f"  • Task #{s['task_id']} '{s['title']}' ({s['domain']}): {s['scheduled_start'][:16]} → {s['scheduled_end'][:16]}")
    if allocation["unassigned"]:
        lines.append(f"\n⚠️ Unplaced tasks ({len(allocation['unassigned'])}):")
        for u in allocation["unassigned"]:
            lines.append(f"  • Task #{u['task_id']} '{u['title']}': {u['reason']}")

    return {
        "response": "\n".join(lines),
        "data": {
            "status": "proposed",
            "horizon": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "scheduled": allocation["scheduled"],
            "unassigned": allocation["unassigned"],
            "conflicts": allocation["conflicts"],
            "summary": allocation["summary"],
        },
    }


@register_skill("commit_schedule")
async def handle_commit_schedule(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Commit approved time slots to tasks and synchronize to Google Calendar."""
    from backend.memory.structured import get_task, update_task
    from backend.services.calendar import link_calendar_event
    from backend.services.scheduler import _ensure_utc

    assignments = args.get("assignments") or []
    rationale = args.get("rationale") or "Schedule committed by Compass Agent."

    if not assignments:
        return {"response": "No task assignments provided to commit.", "data": {"status": "error"}}

    committed_results: List[Dict[str, Any]] = []
    previous_states: List[Dict[str, Any]] = []

    if pool is not None:
        async with pool.acquire() as conn:
            for item in assignments:
                t_id = item.get("task_id")
                s_start = item.get("scheduled_start")
                s_end = item.get("scheduled_end")
                if not t_id or not s_start or not s_end:
                    continue

                prev = await get_task(conn, t_id)
                if prev:
                    previous_states.append({
                        "task_id": t_id,
                        "scheduled_start": prev.get("scheduled_start").isoformat() if prev.get("scheduled_start") else None,
                        "scheduled_end": prev.get("scheduled_end").isoformat() if prev.get("scheduled_end") else None,
                    })

                s_start_dt = _ensure_utc(s_start)
                s_end_dt = _ensure_utc(s_end)

                updated = await update_task(
                    conn,
                    t_id,
                    scheduled_start=s_start_dt,
                    scheduled_end=s_end_dt,
                )
                if updated:
                    cal_link = await link_calendar_event(
                        task_id=t_id,
                        start_dt=s_start_dt,
                        end_dt=s_end_dt,
                        title=updated["title"],
                        pool=pool,
                    )
                    committed_results.append({
                        "task_id": t_id,
                        "title": updated["title"],
                        "scheduled_start": s_start_dt.isoformat(),
                        "scheduled_end": s_end_dt.isoformat(),
                        "calendar_event_id": cal_link.get("google_event_id"),
                    })

    response_text = (
        f"✅ Successfully committed schedule for {len(committed_results)} task(s) and synced to Google Calendar.\n"
        f"Rationale: {rationale}"
    )

    return {
        "response": response_text,
        "data": {
            "status": "committed",
            "committed_count": len(committed_results),
            "committed_tasks": committed_results,
            "previous_states": previous_states,
            "rationale": rationale,
        },
    }


@register_skill("detect_schedule_conflicts")
async def handle_detect_schedule_conflicts(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Analyze scheduled tasks, calendar events, and dependencies for timing conflicts and violations."""
    from backend.memory.structured import list_tasks, get_all_dependencies_map
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import detect_schedule_conflicts

    start_date = args.get("start_date")
    end_date = args.get("end_date")
    now = datetime.now(timezone.utc)

    if start_date:
        try:
            s_dt = datetime.combine(date.fromisoformat(start_date[:10]), datetime.min.time(), tzinfo=timezone.utc)
        except Exception:
            s_dt = now
    else:
        s_dt = now

    if end_date:
        try:
            e_dt = datetime.combine(date.fromisoformat(end_date[:10]), datetime.max.time(), tzinfo=timezone.utc)
        except Exception:
            e_dt = s_dt + timedelta(days=14)
    else:
        e_dt = s_dt + timedelta(days=14)

    tasks: List[Dict[str, Any]] = []
    dep_map: Dict[int, List[int]] = {}
    if pool is not None:
        async with pool.acquire() as conn:
            tasks = await list_tasks(conn)
            dep_map = await get_all_dependencies_map(conn)

    # External busy intervals
    ext_events: List[Dict[str, Any]] = []
    if pool is not None:
        all_busy = await get_calendar_freebusy(s_dt, e_dt, pool=pool)
        ext_events = [b for b in all_busy if b.get("source") != "compass_task"]

    conflicts = detect_schedule_conflicts(
        scheduled_tasks=tasks,
        external_events=ext_events,
        dependencies=dep_map,
        current_time=now,
    )

    if conflicts:
        lines = [f"⚠️ Detected {len(conflicts)} schedule conflict(s) or constraint violation(s):"]
        for c in conflicts:
            lines.append(f"  • [{c['conflict_type'].upper()}] {c.get('issue', c)}")
        resp_text = "\n".join(lines)
    else:
        resp_text = "✅ No schedule conflicts, dependency timing violations, or slipped deadlines detected."

    return {
        "response": resp_text,
        "data": {
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "scanned_tasks_count": len(tasks),
            "scanned_external_events_count": len(ext_events),
        },
    }
