"""
Compass — Task Domain Business Logic Service.
Handles task creation, conflict detection, countdown formatting, and memory chunk indexing.
"""

import logging
from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import HTTPException

from backend.memory import structured
from backend.models import CreateTaskRequest, FrontendTaskOut

logger = logging.getLogger("compass.services.task_service")


def format_countdown(due_date: Optional[date]) -> str:
    """Format human-readable countdown string for a due date."""
    if not due_date:
        return "Active"
    today = date.today()
    delta = (due_date - today).days
    day_name = due_date.strftime("%A")
    if delta < 0:
        return f"Overdue ({abs(delta)}d ago)"
    elif delta == 0:
        return "Due today"
    elif delta == 1:
        return f"1d left ({day_name})"
    else:
        return f"{delta}d left ({day_name})"


def build_frontend_task(
    row: dict[str, Any],
    proj_name: str = "General",
    cognitive_conflict: Optional[dict] = None,
    duration_minutes: Optional[int] = None,
) -> FrontendTaskOut:
    """Convert a database task row into FrontendTaskOut."""
    due_d = row.get("due_date")
    countdown_str = format_countdown(due_d)
    created_at = row.get("created_at") or datetime.now()
    if isinstance(created_at, (datetime, date)):
        ts_str = created_at.strftime("%b %d, %H:%M")
    else:
        ts_str = "Just now"

    domain_val = row.get("domain", "general")
    tags = [domain_val]
    if proj_name and proj_name != "General":
        tags.append(proj_name.lower().replace(" ", "-"))
    if row.get("priority") == "urgent":
        tags.append("urgent")

    s_start = row.get("scheduled_start")
    s_end = row.get("scheduled_end")
    dur = duration_minutes if duration_minutes is not None else int(row.get("duration_minutes") or 60)

    return FrontendTaskOut(
        id=str(row["id"]),
        title=row["title"],
        domain=domain_val,
        project=proj_name,
        countdown=countdown_str,
        tags=tags,
        vector_dim=768,
        timestamp=ts_str,
        priority=row.get("priority", "medium"),
        status=row.get("status", "open"),
        duration_minutes=dur,
        scheduled_start=s_start.isoformat() if hasattr(s_start, "isoformat") else (str(s_start) if s_start else None),
        scheduled_end=s_end.isoformat() if hasattr(s_end, "isoformat") else (str(s_end) if s_end else None),
        is_fixed=bool(row.get("is_fixed", False)),
        description=row.get("notes") or row.get("description"),
        due_date=due_d.isoformat() if hasattr(due_d, "isoformat") else (str(due_d) if due_d else None),
        cognitive_conflict=cognitive_conflict,
    )


async def handle_create_task(conn, req: CreateTaskRequest, user_id: Optional[str]) -> FrontendTaskOut:
    """Execute complete creation pipeline with deduplication, memory indexing, and conflict checks."""
    title = req.title.strip()
    parsed_date = None
    if req.due_date:
        parsed_date = date.fromisoformat(req.due_date.strip())

    dom_clean = structured.normalize_domain(req.domain)
    proj_name = req.project.strip() if req.project else "General"

    existing_tasks = await structured.list_tasks(conn, user_id=user_id)
    exact_matches = [
        t for t in existing_tasks
        if t["title"].strip().lower() == title.lower()
        and (
            (t.get("due_date") is None and parsed_date is None)
            or (t.get("due_date") == parsed_date)
        )
        and t.get("status") != "done"
    ]
    if exact_matches and not req.allow_duplicate:
        ex = exact_matches[0]
        d_str = ex.get("due_date") or "unscheduled"
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate deadline: '{title}' is already scheduled for {d_str}. Exact duplicate deadlines cannot be added. Ask Northstar to look into schedules or choose a different date."
        )

    same_name_matches = [
        t for t in existing_tasks
        if t["title"].strip().lower() == title.lower()
        and t.get("status") != "done"
    ]
    if same_name_matches and not req.allow_different_thing and not req.allow_duplicate:
        if req.shift_existing:
            target_task = same_name_matches[0]
            updated_row = await structured.update_task(
                conn,
                target_task["id"],
                due_date=parsed_date,
                priority=req.priority or target_task.get("priority", "medium"),
                notes=req.notes or req.description or target_task.get("notes"),
            )
            if not updated_row:
                raise HTTPException(status_code=404, detail="Task to shift was not found.")
            p_data = updated_row.get("project") or {}
            p_name = p_data.get("name", proj_name) if p_data else proj_name
            return build_frontend_task(updated_row, proj_name=p_name, duration_minutes=req.duration_minutes)
        else:
            ex = same_name_matches[0]
            d_str = ex.get("due_date") or "unscheduled"
            raise HTTPException(
                status_code=409,
                detail=f"A deadline with the name '{title}' already exists on {d_str}. Please specify whether to shift the deadline (shift_existing=true) or if it is for a completely different thing (allow_different_thing=true)."
            )

    project_id = None
    if proj_name and proj_name != "General":
        proj = await structured.get_or_create_project(conn, name=proj_name, domain=dom_clean)
        project_id = proj.get("id")

    task_row = await structured.create_task(
        conn,
        domain=dom_clean,
        title=title,
        project_id=project_id,
        due_date=parsed_date,
        priority=req.priority or "medium",
        notes=req.notes or req.description,
        user_id=user_id,
    )
    task_id = task_row["id"]
    if req.duration_minutes:
        try:
            await structured.update_task(conn, task_id, duration_minutes=req.duration_minutes)
        except Exception as ex:
            logger.debug(f"Could not update duration_minutes: {ex}")

    try:
        from backend.services.embeddings import get_embedding
        emb_text = f"Task [{dom_clean}]: {title}"
        if proj_name and proj_name != "General":
            emb_text += f" (Project: {proj_name})"
        if req.notes or req.description:
            emb_text += f" - {req.notes or req.description}"
        embedding = await get_embedding(emb_text)
        tags_list = [dom_clean]
        if proj_name and proj_name != "General":
            tags_list.append(proj_name.lower().replace(" ", "-"))
        if req.priority == "urgent":
            tags_list.append("urgent")
        await conn.execute(
            """
            INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags, user_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            dom_clean, project_id, emb_text, embedding, "direct_task_creation", tags_list, user_id
        )
    except Exception as e:
        logger.warning(f"Could not index memory chunk for new task: {e}")

    conflict_info = None
    try:
        from backend.services.scheduler import check_proactive_cognitive_conflicts
        conflict_info = check_proactive_cognitive_conflicts(
            proposed_task={
                "id": task_id,
                "title": title,
                "domain": dom_clean,
                "due_date": parsed_date.isoformat() if parsed_date else None,
                "priority": req.priority or "medium",
                "notes": req.notes or req.description,
                "duration_minutes": req.duration_minutes or 60,
            },
            existing_tasks=existing_tasks,
        )
    except Exception as cex:
        logger.debug(f"Router conflict check skipped: {cex}")

    return build_frontend_task(task_row, proj_name=proj_name, cognitive_conflict=conflict_info, duration_minutes=req.duration_minutes or 60)
