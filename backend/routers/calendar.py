"""
Compass — Calendar and Scheduling Endpoints.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from backend.dependencies import _get_current_user_id
from backend.memory.db import get_pool
from backend.memory import structured
from backend.models import (
    ProposeScheduleBody,
    CommitScheduleBody,
    UpdatePreferencesBody,
    ReactiveCheckBody,
)

logger = logging.getLogger("compass.routers.calendar")

router = APIRouter(tags=["calendar"])


@router.get("/api/calendar/status")
async def get_calendar_status_endpoint(request: Request):
    """Check connection status for Google Calendar integration."""
    from backend.services.calendar import get_calendar_connection_status
    uid = _get_current_user_id(request)
    pool = await get_pool()
    status = await get_calendar_connection_status(pool=pool, user_id=uid)
    return {"status": "ok", "calendar": status}


@router.get("/api/calendar/availability")
async def get_calendar_availability_endpoint(
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
):
    """Retrieve busy blocks and available working windows."""
    from backend.skills import SKILL_REGISTRY
    pool = await get_pool()
    handler = SKILL_REGISTRY.get("get_calendar_availability")
    if not handler:
        raise HTTPException(status_code=500, detail="Availability skill not registered")
    result = await handler({"start_date": start_date, "end_date": end_date}, pool)
    return result


@router.post("/api/schedule/propose")
async def propose_schedule_endpoint(body: ProposeScheduleBody):
    """Generate deterministic schedule proposal for tasks."""
    from backend.skills import SKILL_REGISTRY
    pool = await get_pool()
    handler = SKILL_REGISTRY.get("propose_schedule")
    if not handler:
        raise HTTPException(status_code=500, detail="Schedule proposer skill not registered")
    result = await handler(body.model_dump(), pool)
    return result


@router.post("/api/schedule/commit")
async def commit_schedule_endpoint(body: CommitScheduleBody):
    """Commit approved time slots to tasks and calendar."""
    from backend.skills import SKILL_REGISTRY
    pool = await get_pool()
    handler = SKILL_REGISTRY.get("commit_schedule")
    if not handler:
        raise HTTPException(status_code=500, detail="Schedule commit skill not registered")
    result = await handler(body.model_dump(), pool)
    return result


@router.get("/api/calendar/export.ics")
async def export_calendar_ics_endpoint(
    request: Request,
    domain: Optional[str] = Query(None),
):
    """Export standard RFC 5545 iCalendar feed for calendar apps."""
    from backend.services.calendar import generate_ics_feed
    target_user_id = _get_current_user_id(request)
    pool = await get_pool()
    tasks = []
    if pool is not None:
        async with pool.acquire() as conn:
            tasks = await structured.list_tasks(conn, domain=domain, user_id=target_user_id, scheduled_only=True)
            if not tasks:
                tasks = await structured.list_tasks(conn, domain=domain, user_id=target_user_id)

    ics_content = generate_ics_feed(tasks, calendar_name="Compass Tasks")
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={
            "Content-Disposition": "attachment; filename=compass_schedule.ics",
            "Cache-Control": "no-cache",
        },
    )


@router.get("/api/calendar/preferences")
async def get_calendar_preferences_endpoint():
    """Retrieve working hours, days, and buffer preferences."""
    pool = await get_pool()
    if not pool:
        return {
            "user_id": "default_user",
            "work_start_time": "09:00:00",
            "work_end_time": "18:00:00",
            "work_days": [1, 2, 3, 4, 5],
            "buffer_minutes": 15,
            "preferred_focus": "morning",
        }
    async with pool.acquire() as conn:
        prefs = await structured.get_scheduling_preferences(conn)
        return prefs


@router.put("/api/calendar/preferences")
async def update_calendar_preferences_endpoint(body: UpdatePreferencesBody):
    """Update working hours, days, and buffer preferences."""
    pool = await get_pool()
    if not pool:
        return {"status": "error", "message": "Database not available"}
    async with pool.acquire() as conn:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        prefs = await structured.update_scheduling_preferences(conn, **updates)
        return {"status": "ok", "preferences": prefs}


@router.post("/api/schedule/reactive-check")
async def reactive_schedule_check_endpoint(body: Optional[ReactiveCheckBody] = None):
    """Detect uncompleted tasks that passed their scheduled end time and compute reactive re-plan."""
    from backend.services.scheduler import find_slipped_tasks, replan_slipped_tasks, get_available_windows
    from backend.services.calendar import get_calendar_freebusy
    from backend.agent import AgentStep, save_agent_run

    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")

    now = datetime.fromisoformat(body.current_time.replace("Z", "+00:00")) if (body and body.current_time) else datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        all_tasks = await structured.list_tasks(conn)
        dep_map = await structured.get_all_dependencies_map(conn)
        prefs = await structured.get_scheduling_preferences(conn)

    slipped = find_slipped_tasks(all_tasks, current_time=now)
    if not slipped:
        return {
            "status": "ok",
            "slipped_count": 0,
            "message": "No slipped tasks detected. Schedule is currently on track.",
            "slipped_tasks": [],
            "replan": None,
        }

    busy = await get_calendar_freebusy(now, now + timedelta(days=7), pool=pool)
    windows = get_available_windows(
        busy,
        now,
        now + timedelta(days=7),
        work_start_time=prefs.get("work_start_time", "09:00:00"),
        work_end_time=prefs.get("work_end_time", "18:00:00"),
        work_days=prefs.get("work_days", [1, 2, 3, 4, 5]),
        buffer_minutes=prefs.get("buffer_minutes", 15),
    )

    replan = replan_slipped_tasks(
        slipped_tasks=slipped,
        all_tasks=all_tasks,
        dependencies=dep_map,
        available_windows=windows,
        buffer_minutes=prefs.get("buffer_minutes", 15),
    )

    run_id = f"reactive_replan_{int(now.timestamp())}"
    if replan["rescheduled"]:
        rationale = f"Reactive re-schedule: {len(slipped)} task(s) slipped past scheduled end ({replan['slipped_task_ids']}). Replanned {len(replan['rescheduled'])} affected tasks."
        pending_action = {
            "tool": "commit_schedule",
            "args": {
                "assignments": replan["rescheduled"],
                "rationale": rationale,
            },
        }
        step_think = AgentStep(
            type="think",
            content=f"Detected slipped uncompleted task(s): {', '.join(str(s.get('title', 'Task')) for s in slipped)}. Calculating cascading dependencies and replanning into available slots.",
            step_number=1,
            run_id=run_id,
        )
        step_confirm = AgentStep(
            type="confirm_request",
            content=rationale,
            tool_name="commit_schedule",
            tool_args=pending_action["args"],
            step_number=2,
            run_id=run_id,
        )

        try:
            await save_agent_run(
                pool=pool,
                run_id=run_id,
                goal=f"Reactive Re-Plan: Slipped Tasks {replan['slipped_task_ids']}",
                status="pending_confirmation",
                accumulated_steps=[step_think, step_confirm],
                messages=[{"role": "assistant", "content": rationale}],
                pending_actions=[pending_action],
            )
        except Exception as e:
            logger.warning(f"Could not persist reactive agent run: {e}")

    return {
        "status": "reactive_replan_staged" if replan["rescheduled"] else "slipped_detected_no_slots",
        "run_id": run_id if replan["rescheduled"] else None,
        "slipped_count": len(slipped),
        "slipped_tasks": slipped,
        "replan": replan,
    }


@router.get("/api/schedule/conflicts")
async def get_schedule_conflicts_endpoint(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Check for schedule overlaps, dependency timing violations, and slipped deadlines."""
    from backend.skills import SKILL_REGISTRY
    pool = await get_pool()
    handler = SKILL_REGISTRY.get("detect_schedule_conflicts")
    if not handler:
        raise HTTPException(status_code=500, detail="Conflict detection skill not registered")
    result = await handler({"start_date": start_date, "end_date": end_date}, pool)
    return result
