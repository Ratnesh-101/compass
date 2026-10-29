"""
Compass — Calendar and Scheduling Skill Handlers.
"""

from typing import Any, Dict, List
import logging
from datetime import datetime, date, timedelta, timezone

from backend.services.user_timezone import resolve_timezone_name, resolve_zone
from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.calendar")


@register_skill("get_calendar_availability")
async def handle_get_calendar_availability(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query free/busy windows and existing schedule blocks from Google Calendar & tasks."""
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import get_available_windows
    from backend.memory.structured import get_scheduling_preferences

    from backend.services.ownership import scope_owner

    start_str = args.get("start_date")
    end_str = args.get("end_date")
    user_id = args.get("user_id")
    scoped_owner = scope_owner(user_id)
    tz_name = resolve_timezone_name(args.get("timezone"))
    zone = resolve_zone(tz_name)

    now = datetime.now(timezone.utc)
    if start_str:
        try:
            start_dt = datetime.combine(date.fromisoformat(start_str[:10]), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        except Exception:
            start_dt = now
    else:
        start_dt = now

    if end_str:
        try:
            end_dt = datetime.combine(date.fromisoformat(end_str[:10]), datetime.max.time(), tzinfo=zone).astimezone(timezone.utc)
        except Exception:
            end_dt = start_dt + timedelta(days=7)
    else:
        end_dt = start_dt + timedelta(days=7)

    calendar_errors: List[str] = []
    busy = await get_calendar_freebusy(
        start_dt, end_dt, pool=pool, user_id=user_id or "default_user", task_user_id=scoped_owner,
        calendar_errors=calendar_errors,
    )

    prefs: Dict[str, Any] = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                prefs = await get_scheduling_preferences(conn, user_id=user_id or "default_user")
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
        tz_name=tz_name,
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
            "timezone": tz_name,
            "busy_count": len(busy),
            "busy_intervals": busy,
            "calendar_error": calendar_errors[0] if calendar_errors else None,
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
    from backend.services.scheduler import (
        INACTIVE_TASK_STATUSES,
        allocate_task_slots,
        earliest_schedulable_start,
        get_available_windows,
    )

    from backend.services.ownership import scope_owner

    target_date_str = args.get("target_date")
    domain = args.get("domain")
    task_ids = args.get("task_ids")
    user_id = args.get("user_id")
    scoped_owner = scope_owner(user_id)
    tz_name = resolve_timezone_name(args.get("timezone"))
    zone = resolve_zone(tz_name)

    now = datetime.now(timezone.utc)
    if target_date_str:
        try:
            requested_start = datetime.combine(date.fromisoformat(target_date_str[:10]), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
        except Exception:
            requested_start = now
    else:
        requested_start = now
    # Never propose a slot in the past: clamp to now rounded up to the next 15 minutes.
    start_dt = earliest_schedulable_start(requested_start, now)
    end_dt = start_dt + timedelta(days=7)

    tasks: List[Dict[str, Any]] = []
    dep_map: Dict[int, List[int]] = {}
    prefs: Dict[str, Any] = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}

    if pool is not None:
        async with pool.acquire() as conn:
            prefs = await get_scheduling_preferences(conn, user_id=user_id or "default_user")
            dep_map = await get_all_dependencies_map(conn)
            if task_ids:
                all_tasks = await list_tasks(conn, domain=domain, user_id=scoped_owner)
                id_set = set(task_ids)
                tasks = [t for t in all_tasks if t["id"] in id_set]
            else:
                tasks = await list_tasks(conn, domain=domain, status="open", user_id=scoped_owner)
    tasks = [t for t in tasks if str(t.get("status") or "").lower() not in INACTIVE_TASK_STATUSES]

    busy = await get_calendar_freebusy(
        start_dt, end_dt, pool=pool, user_id=user_id or "default_user", task_user_id=scoped_owner
    )
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
        tz_name=tz_name,
    )

    allocation = allocate_task_slots(
        tasks,
        free_windows,
        buffer_minutes=buffer_minutes,
        dependencies=dep_map,
        not_before=start_dt,
        tz_name=tz_name,
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
            "timezone": tz_name,
            "horizon": {"start": start_dt.isoformat(), "end": end_dt.isoformat()},
            "earliest_start": start_dt.isoformat(),
            "scheduled": allocation["scheduled"],
            "unassigned": allocation["unassigned"],
            "conflicts": allocation["conflicts"],
            "summary": allocation["summary"],
        },
    }


# A slot may have started a moment ago while the user reviewed the plan; older than this is "in the past".
SLOT_PAST_GRACE = timedelta(minutes=5)


def validate_assignments(assignments: List[Any], now: datetime) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate every assignment up front. Returns (valid, errors); nothing is applied here.

    Each valid item is {"task_id": int, "start": datetime, "end": datetime} (UTC).
    Each error is {"index": int, "task_id": Any, "error": str}.
    """
    from backend.services.scheduler import _ensure_utc

    valid: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for idx, item in enumerate(assignments):
        if not isinstance(item, dict):
            errors.append({"index": idx, "task_id": None, "error": "Each assignment must be an object."})
            continue
        raw_id = item.get("task_id")

        def fail(message: str, _idx: int = idx, _raw: Any = raw_id) -> None:
            errors.append({"index": _idx, "task_id": _raw, "error": message})

        try:
            t_id = int(raw_id)
        except (TypeError, ValueError):
            fail("task_id must be an integer.")
            continue
        if not item.get("scheduled_start") or not item.get("scheduled_end"):
            fail("scheduled_start and scheduled_end are required.")
            continue
        try:
            start = _ensure_utc(item["scheduled_start"])
            end = _ensure_utc(item["scheduled_end"])
        except Exception:
            fail("scheduled_start and scheduled_end must be valid ISO 8601 timestamps.")
            continue
        if end <= start:
            fail("scheduled_end must be after scheduled_start.")
        elif start < now - SLOT_PAST_GRACE:
            fail("This slot starts in the past. Propose a new schedule.")
        else:
            valid.append({"task_id": t_id, "start": start, "end": end})
    return valid, errors


def _previous_state(prev: Dict[str, Any], t_id: int) -> Dict[str, Any]:
    p_start = prev.get("scheduled_start")
    p_end = prev.get("scheduled_end")
    return {
        "task_id": t_id,
        "scheduled_start": p_start.isoformat() if (p_start is not None and hasattr(p_start, "isoformat")) else (str(p_start) if p_start else None),
        "scheduled_end": p_end.isoformat() if (p_end is not None and hasattr(p_end, "isoformat")) else (str(p_end) if p_end else None),
    }


@register_skill("commit_schedule")
async def handle_commit_schedule(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Commit approved time slots to tasks, then try to create the Google Calendar events.

    All assignments are validated first; if any is invalid nothing is applied and the
    per-item errors are returned (status "invalid"). Task updates run in one transaction.
    Calendar results are reported honestly: `live_created` counts events Google really
    created, `error_count`/`calendar_error` describe refusals.
    """
    from backend.memory.structured import get_task, update_task
    from backend.services.calendar import link_calendar_event, summarize_calendar_outcome, tally_link_results
    from backend.services.ownership import scope_owner

    user_id = args.get("user_id")
    scoped_owner = scope_owner(user_id)
    assignments = args.get("assignments") or []
    rationale = args.get("rationale") or "Schedule committed by Compass Agent."

    if not assignments:
        return {"response": "No task assignments provided to commit.", "data": {"status": "error"}}

    valid, errors = validate_assignments(assignments, datetime.now(timezone.utc))
    if errors:
        return {
            "response": f"Nothing was scheduled: {len(errors)} assignment(s) are invalid. {errors[0]['error']}",
            "data": {
                "status": "invalid",
                "committed_count": 0,
                "committed_tasks": [],
                "previous_states": [],
                "rejected_task_ids": [],
                "errors": errors,
                "rationale": rationale,
            },
        }

    committed_results: List[Dict[str, Any]] = []
    previous_states: List[Dict[str, Any]] = []
    rejected_task_ids: List[Any] = []
    committed_slots: List[Dict[str, Any]] = []
    link_results: List[Dict[str, Any]] = []

    if pool is not None:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for item in valid:
                    t_id = item["task_id"]
                    prev = await get_task(conn, t_id)
                    if scoped_owner and (not prev or (prev.get("user_id") or "").lower() != scoped_owner.lower()):
                        rejected_task_ids.append(t_id)
                        continue
                    updated = await update_task(
                        conn,
                        t_id,
                        owner_id=scoped_owner,
                        scheduled_start=item["start"],
                        scheduled_end=item["end"],
                    )
                    if not updated:
                        rejected_task_ids.append(t_id)
                        continue
                    if prev:
                        previous_states.append(_previous_state(prev, t_id))
                    committed_slots.append(item)
                    committed_results.append({
                        "task_id": t_id,
                        "title": updated["title"],
                        "scheduled_start": item["start"].isoformat(),
                        "scheduled_end": item["end"].isoformat(),
                    })

        # Calendar events are created after the DB transaction so no connection is held during HTTP calls.
        for entry, item in zip(committed_results, committed_slots):
            cal_link = await link_calendar_event(
                task_id=entry["task_id"],
                start_dt=item["start"],
                end_dt=item["end"],
                title=entry["title"],
                pool=pool,
                user_id=user_id or "default_user",
            )
            link_results.append(cal_link)
            entry["calendar_event_id"] = cal_link.get("google_event_id")
            entry["calendar_status"] = cal_link.get("status")
            entry["live_created"] = cal_link.get("live_created", False)
            entry["calendar_error"] = cal_link.get("error")

    tally = tally_link_results(link_results)
    response_text = f"Scheduled {len(committed_results)} task(s) in Compass."
    if committed_results:
        response_text += " " + summarize_calendar_outcome(
            tally["live_created"], tally["error_count"], tally["simulated_count"],
            tally["not_connected_count"], tally["calendar_error"],
        )
    response_text += f"\nRationale: {rationale}"

    return {
        "response": response_text,
        "data": {
            "status": "committed",
            "committed_count": len(committed_results),
            "committed_tasks": committed_results,
            "previous_states": previous_states,
            "rejected_task_ids": rejected_task_ids,
            "live_created": tally["live_created"],
            "simulated_count": tally["simulated_count"],
            "error_count": tally["error_count"],
            "calendar_error": tally["calendar_error"],
            "rationale": rationale,
        },
    }


@register_skill("detect_schedule_conflicts")
async def handle_detect_schedule_conflicts(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Analyze scheduled tasks, calendar events, and dependencies for timing conflicts and violations."""
    from backend.memory.structured import list_tasks, get_all_dependencies_map
    from backend.services.calendar import get_calendar_freebusy
    from backend.services.scheduler import detect_schedule_conflicts

    from backend.services.ownership import scope_owner

    start_date = args.get("start_date")
    end_date = args.get("end_date")
    user_id = args.get("user_id")
    scoped_owner = scope_owner(user_id)
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
            tasks = await list_tasks(conn, user_id=scoped_owner)
            dep_map = await get_all_dependencies_map(conn)

    # External busy intervals
    ext_events: List[Dict[str, Any]] = []
    if pool is not None:
        all_busy = await get_calendar_freebusy(
            s_dt, e_dt, pool=pool, user_id=user_id or "default_user", task_user_id=scoped_owner
        )
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
