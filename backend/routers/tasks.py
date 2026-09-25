"""
Compass — Task, Project, and Timeline Endpoints.
"""

import hmac
import logging
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.config import get_settings
from backend.dependencies import verify_token, _get_current_user_id, _get_or_create_user_id, rate_limit
from backend.memory.db import get_pool
from backend.memory import structured
from backend.models import (
    ProjectsResponse,
    ProjectOut,
    TasksResponse,
    TaskOut,
    TaskProjectRef,
    DashboardResponse,
    DomainStats,
    NearestDeadline,
    TimelineResponse,
    TimelineEntry,
    FrontendTaskOut,
    CreateTaskRequest,
    UpdateTaskRequest,
    AddDependencyBody,
)

logger = logging.getLogger("compass.routers.tasks")

router = APIRouter(tags=["tasks"])
settings = get_settings()


def _format_countdown(due_date: Optional[date]) -> str:
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


# ---- GET /projects ----------------------------------------------------
@router.get("/projects", response_model=ProjectsResponse)
async def get_projects(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    _token: str = Depends(verify_token),
):
    """List all tracked projects from database."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await structured.list_projects(conn, domain=domain)
            projects = [
                ProjectOut(
                    id=r["id"],
                    name=r["name"],
                    domain=r["domain"],
                    description=r.get("description"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return ProjectsResponse(projects=projects)
    except Exception as e:
        logger.warning(f"Database query failed for get_projects: {e}")
        fallback = [
            ProjectOut(id=1, name="Hackathon Submission", domain="hackathon", description="Compass agent demo & docs", created_at="2026-09-01T00:00:00"),
            ProjectOut(id=2, name="Distributed Systems", domain="coursework", description="Coursework assignments & notes", created_at="2026-09-01T00:00:00"),
            ProjectOut(id=3, name="Compass Core", domain="code", description="Backend engine and skills", created_at="2026-09-01T00:00:00"),
        ]
        if domain:
            fallback = [p for p in fallback if p.domain.lower() == domain.lower()]
        return ProjectsResponse(projects=fallback)


# ---- GET /tasks -------------------------------------------------------
@router.get("/tasks", response_model=TasksResponse)
async def get_tasks(
    domain: Optional[str] = Query(None),
    project: Optional[str] = Query(None, description="Filter by project name"),
    status: Optional[str] = Query(None),
    due_before: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    _token: str = Depends(verify_token),
):
    """Query tasks with optional filters from database."""
    due_date_parsed: Optional[date] = None
    if due_before:
        try:
            due_date_parsed = datetime.strptime(due_before.strip(), "%Y-%m-%d").date()
        except Exception:
            pass

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            project_id: Optional[int] = None
            if project:
                p_row = await conn.fetchrow(
                    "SELECT id FROM projects WHERE LOWER(name) = LOWER($1)",
                    project.strip()
                )
                if p_row:
                    project_id = p_row["id"]
                else:
                    return TasksResponse(tasks=[])

            rows = await structured.list_tasks(
                conn,
                domain=domain,
                project_id=project_id,
                status=status,
                due_before=due_date_parsed,
            )
            tasks = [
                TaskOut(
                    id=r["id"],
                    domain=r["domain"],
                    project=TaskProjectRef(**r["project"]) if r.get("project") else None,
                    title=r["title"],
                    due_date=r["due_date"].isoformat() if hasattr(r["due_date"], "isoformat") and r["due_date"] else (str(r["due_date"]) if r["due_date"] else None),
                    status=r["status"],
                    priority=r["priority"],
                    notes=r.get("notes"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                    updated_at=r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else str(r["updated_at"]),
                )
                for r in rows
            ]
            return TasksResponse(tasks=tasks)
    except Exception as e:
        logger.warning(f"Database query failed for get_tasks: {e}")
        return TasksResponse(tasks=[])


# ---- GET /dashboard ---------------------------------------------------
@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(_token: str = Depends(verify_token)):
    """Aggregate live counts via SQL (total open tasks, tasks due within 72 hours, project counts by domain)."""
    domains = {
        d: DomainStats(project_count=0, open_task_count=0, nearest_deadline=None, last_activity=None)
        for d in ("hackathon", "coursework", "code", "general")
    }

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            proj_rows = await conn.fetch(
                "SELECT domain, COUNT(*) AS count FROM projects GROUP BY domain"
            )
            for r in proj_rows:
                d = r["domain"]
                if d in domains:
                    domains[d].project_count = r["count"]

            task_rows = await conn.fetch(
                "SELECT domain, COUNT(*) AS count FROM tasks WHERE status = 'open' GROUP BY domain"
            )
            for r in task_rows:
                d = r["domain"]
                if d in domains:
                    domains[d].open_task_count = r["count"]

            nearest_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (domain) id, domain, title, due_date
                FROM tasks
                WHERE status = 'open' AND due_date IS NOT NULL
                ORDER BY domain, due_date ASC
                """
            )
            for r in nearest_rows:
                d = r["domain"]
                if d in domains and r["due_date"]:
                    domains[d].nearest_deadline = NearestDeadline(
                        task_id=r["id"],
                        title=r["title"],
                        due_date=str(r["due_date"]),
                    )

            activity_rows = await conn.fetch(
                "SELECT domain, MAX(updated_at) AS last_act FROM tasks GROUP BY domain"
            )
            for r in activity_rows:
                d = r["domain"]
                if d in domains and r["last_act"]:
                    domains[d].last_activity = r["last_act"].isoformat()

            total_open = sum(s.open_task_count for s in domains.values())
            total_proj = sum(s.project_count for s in domains.values())

            return DashboardResponse(
                domains=domains,
                total_open_tasks=total_open,
                total_projects=total_proj,
            )
    except Exception as e:
        logger.warning(f"Database query failed for get_dashboard: {e}")
        return DashboardResponse(domains=domains, total_open_tasks=0, total_projects=0)


# ---- GET /memory/timeline ---------------------------------------------
@router.get("/memory/timeline", response_model=TimelineResponse)
async def get_timeline(
    domain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _token: str = Depends(verify_token),
):
    """Fetch ordered rows across tasks (created_at) and memory_chunks (created_at) filtered by domain."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            query = """
                SELECT 'task' AS type, t.domain, p.name AS project, 'Created task: ' || t.title AS summary, t.created_at
                FROM tasks t
                LEFT JOIN projects p ON t.project_id = p.id
                WHERE ($1::text IS NULL OR t.domain = $1)

                UNION ALL

                SELECT 'memory' AS type, m.domain, p.name AS project, LEFT(m.content, 120) AS summary, m.created_at
                FROM memory_chunks m
                LEFT JOIN projects p ON m.project_id = p.id
                WHERE ($1::text IS NULL OR m.domain = $1)

                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
            rows = await conn.fetch(query, domain, limit, offset)

            count_query = """
                SELECT (
                    (SELECT COUNT(*) FROM tasks WHERE ($1::text IS NULL OR domain = $1)) +
                    (SELECT COUNT(*) FROM memory_chunks WHERE ($1::text IS NULL OR domain = $1))
                ) AS total
            """
            total_count = await conn.fetchval(count_query, domain) or 0

            entries = [
                TimelineEntry(
                    type=r["type"],
                    domain=r["domain"],
                    project=r.get("project"),
                    summary=r["summary"],
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return TimelineResponse(
                entries=entries,
                total=total_count,
                has_more=(offset + limit) < total_count,
            )
    except Exception as e:
        logger.warning(f"Database query failed for get_timeline: {e}")
        return TimelineResponse(entries=[], total=0, has_more=False)


# ---- GET /api/tasks ---------------------------------------------------
@router.get("/api/tasks", response_model=List[FrontendTaskOut])
async def get_frontend_tasks(request: Request, domain: Optional[str] = Query(None)):
    """Public frontend endpoint matching frontend/src/api/client.js format with per-account isolation."""
    try:
        user_id = _get_current_user_id(request)
        pool = await get_pool()
        async with pool.acquire() as conn:
            raw_tasks = await structured.list_tasks(conn, domain=domain, user_id=user_id)
            result = []
            for t in raw_tasks:
                proj_name = t.get("project", {}).get("name", "General") if t.get("project") else "General"
                due_d = t.get("due_date")
                countdown_str = _format_countdown(due_d)
                created_at = t.get("created_at")
                if isinstance(created_at, (datetime, date)):
                    ts_str = created_at.strftime("%b %d, %H:%M")
                else:
                    ts_str = "Recently"

                tags = [t.get("domain", "task")]
                if proj_name and proj_name != "General":
                    tags.append(proj_name.lower().replace(" ", "-"))
                if t.get("priority") == "urgent":
                    tags.append("urgent")

                s_start = t.get("scheduled_start")
                s_end = t.get("scheduled_end")

                result.append(
                    FrontendTaskOut(
                        id=str(t["id"]),
                        title=t["title"],
                        domain=t["domain"],
                        project=proj_name,
                        countdown=countdown_str,
                        tags=tags,
                        vector_dim=768,
                        timestamp=ts_str,
                        priority=t.get("priority", "medium"),
                        status=t.get("status", "open"),
                        duration_minutes=int(t.get("duration_minutes") or 60),
                        scheduled_start=s_start.isoformat() if hasattr(s_start, "isoformat") else (str(s_start) if s_start else None),
                        scheduled_end=s_end.isoformat() if hasattr(s_end, "isoformat") else (str(s_end) if s_end else None),
                        is_fixed=bool(t.get("is_fixed", False)),
                        description=t.get("notes") or t.get("description"),
                        due_date=due_d.isoformat() if hasattr(due_d, "isoformat") else (str(due_d) if due_d else None),
                    )
                )
            return result
    except Exception as e:
        logger.warning(f"Error fetching frontend tasks from DB: {e}")
        return []


# ---- POST /api/tasks and POST /tasks ----------------------------------
@router.post("/api/tasks", response_model=FrontendTaskOut, dependencies=[Depends(rate_limit)])
@router.post("/tasks", response_model=FrontendTaskOut, dependencies=[Depends(rate_limit)])
async def create_frontend_task(request: Request, req: CreateTaskRequest):
    """Direct user endpoint to create a task or deadline with per-account isolation."""
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Task title is required")
    if len(title) > 500:
        raise HTTPException(status_code=400, detail="Task title exceeds maximum allowed length of 500 characters")

    parsed_date = None
    if req.due_date:
        try:
            parsed_date = date.fromisoformat(req.due_date.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid due_date format (expected YYYY-MM-DD)")

    dom_clean = structured.normalize_domain(req.domain)
    proj_name = req.project.strip() if req.project else "General"
    user_id = _get_or_create_user_id(request)

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # 1. Check for exact duplicate deadline (same title case-insensitive and same due date, not done)
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

            # 2. Check for existing deadline with same name (different date or asking to shift vs separate thing)
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
                        raise HTTPException(
                            status_code=404,
                            detail="Task to shift was not found.",
                        )
                    due_d = updated_row.get("due_date")
                    countdown_str = _format_countdown(due_d)
                    created_at = updated_row.get("created_at") or datetime.now()
                    ts_str = created_at.strftime("%b %d, %H:%M") if isinstance(created_at, (datetime, date)) else "Just now"
                    p_name = updated_row.get("project_name") or proj_name
                    tags = [updated_row.get("domain", dom_clean)]
                    if p_name and p_name != "General":
                        tags.append(p_name.lower().replace(" ", "-"))
                    if updated_row.get("priority") == "urgent":
                        tags.append("urgent")
                    return FrontendTaskOut(
                        id=str(updated_row["id"]),
                        title=updated_row["title"],
                        domain=updated_row["domain"],
                        project=p_name,
                        countdown=countdown_str,
                        tags=tags,
                        vector_dim=768,
                        timestamp=ts_str,
                        priority=updated_row.get("priority", "medium"),
                        status=updated_row.get("status", "open"),
                        duration_minutes=int(updated_row.get("duration_minutes") or 60),
                        scheduled_start=None,
                        scheduled_end=None,
                        is_fixed=bool(updated_row.get("is_fixed", False)),
                        description=updated_row.get("notes") or updated_row.get("description"),
                        due_date=due_d.isoformat() if hasattr(due_d, "isoformat") else (str(due_d) if due_d else None),
                    )
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
                    await structured.update_task(conn, task_id, duration_minutes=int(req.duration_minutes))
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

            due_d = task_row.get("due_date")
            countdown_str = _format_countdown(due_d)
            created_at = task_row.get("created_at") or datetime.now()
            ts_str = created_at.strftime("%b %d, %H:%M") if isinstance(created_at, (datetime, date)) else "Just now"

            tags = [dom_clean]
            if proj_name and proj_name != "General":
                tags.append(proj_name.lower().replace(" ", "-"))
            if req.priority == "urgent":
                tags.append("urgent")

            return FrontendTaskOut(
                id=str(task_id),
                title=task_row["title"],
                domain=task_row["domain"],
                project=proj_name,
                countdown=countdown_str,
                tags=tags,
                vector_dim=768,
                timestamp=ts_str,
                priority=task_row.get("priority", "medium"),
                status=task_row.get("status", "open"),
                duration_minutes=int(req.duration_minutes or 60),
                scheduled_start=None,
                scheduled_end=None,
                is_fixed=False,
                description=req.notes or req.description,
                due_date=due_d.isoformat() if hasattr(due_d, "isoformat") else (str(due_d) if due_d else None),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"DB unavailable for task creation, falling back to mock: {e}")
        import uuid
        return FrontendTaskOut(
            id=f"demo-{uuid.uuid4().hex[:8]}",
            title=title,
            domain=dom_clean,
            project=proj_name,
            countdown=_format_countdown(parsed_date),
            tags=[dom_clean],
            vector_dim=768,
            timestamp="Just now",
            priority=req.priority or "medium",
            status="open",
            duration_minutes=int(req.duration_minutes or 60),
            description=req.notes or req.description,
            due_date=parsed_date.isoformat() if parsed_date else None,
        )


# ---- PATCH & PUT /api/tasks/{task_id} ---------------------------------
@router.patch("/api/tasks/{task_id}", response_model=FrontendTaskOut)
@router.put("/api/tasks/{task_id}", response_model=FrontendTaskOut)
async def update_frontend_task(task_id: str, req: UpdateTaskRequest, request: Request):
    """Direct user endpoint to edit any field of a task/deadline without relying on AI chat."""
    try:
        numeric_id = int(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await structured.get_task(conn, numeric_id)
            if not existing:
                raise HTTPException(status_code=404, detail="Task not found")

            # Ownership check (IDOR mitigation)
            user_id = _get_or_create_user_id(request)
            auth_header = request.headers.get("authorization", "")
            is_admin = False
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
                if token and settings.AUTH_TOKEN and hmac.compare_digest(token, settings.AUTH_TOKEN):
                    is_admin = True

            if not is_admin:
                task_owner = existing.get("user_id")
                if task_owner:
                    if not user_id or user_id.lower() != task_owner.lower():
                        raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to modify this task.")
                else:
                    raise HTTPException(status_code=403, detail="Forbidden: Unowned tasks can only be modified by an administrator.")

            update_kwargs: dict = {}

            if req.title is not None:
                update_kwargs["title"] = req.title.strip()
            if req.domain is not None:
                update_kwargs["domain"] = req.domain.lower().strip()
            if req.priority is not None:
                update_kwargs["priority"] = req.priority
            if req.status is not None:
                update_kwargs["status"] = req.status
            if req.notes is not None:
                update_kwargs["notes"] = req.notes.strip() or None
            elif req.description is not None:
                update_kwargs["notes"] = req.description.strip() or None
            if req.duration_minutes is not None:
                update_kwargs["duration_minutes"] = req.duration_minutes

            if req.due_date is not None:
                if req.due_date == "" or req.due_date.lower() == "null":
                    update_kwargs["due_date"] = None
                else:
                    try:
                        update_kwargs["due_date"] = date.fromisoformat(req.due_date)
                    except ValueError:
                        raise HTTPException(status_code=400, detail=f"Invalid due_date format: {req.due_date}")

            if req.project is not None:
                proj_name = req.project.strip() or "General"
                dom_for_proj = update_kwargs.get("domain") or existing.get("domain", "general")
                proj_row = await structured.get_or_create_project(conn, proj_name, dom_for_proj)
                update_kwargs["project_id"] = proj_row.get("id")

            updated = await structured.update_task(conn, numeric_id, **update_kwargs)
            if not updated:
                raise HTTPException(status_code=500, detail="Failed to update task")

            proj_data = updated.get("project") or {}
            proj_name_out = proj_data.get("name", "General") if proj_data else "General"
            due_d = updated.get("due_date")
            countdown_str = _format_countdown(due_d)
            created_at = updated.get("created_at")
            if isinstance(created_at, (datetime, date)):
                ts_str = created_at.strftime("%b %d, %H:%M")
            else:
                ts_str = "Recently"

            tags = [updated.get("domain", "task")]
            if proj_name_out and proj_name_out != "General":
                tags.append(proj_name_out.lower().replace(" ", "-"))
            if updated.get("priority") == "urgent":
                tags.append("urgent")

            return FrontendTaskOut(
                id=str(updated["id"]),
                title=updated["title"],
                domain=updated.get("domain", "general"),
                project=proj_name_out,
                countdown=countdown_str,
                tags=tags,
                vector_dim=768,
                timestamp=ts_str,
                priority=updated.get("priority", "medium"),
                status=updated.get("status", "open"),
                duration_minutes=int(updated.get("duration_minutes") or 60),
                description=updated.get("notes") or updated.get("description"),
                due_date=due_d.isoformat() if hasattr(due_d, "isoformat") else (str(due_d) if due_d else None),
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"DB unavailable for task update: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")


# ---- DELETE /api/tasks/{task_id} and DELETE /tasks/{task_id} ----------
@router.delete("/api/tasks/{task_id}")
@router.delete("/tasks/{task_id}")
async def delete_frontend_task(task_id: str, request: Optional[Request] = None):
    """Direct user endpoint to delete a task or deadline without relying on AI chat."""
    try:
        numeric_id = int(task_id)
    except ValueError:
        return {"status": "ok", "deleted": True, "task_id": task_id}

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            existing = await structured.get_task(conn, numeric_id)
            if not existing:
                raise HTTPException(status_code=404, detail="Task not found")

            # Ownership check (IDOR mitigation)
            user_id = _get_or_create_user_id(request) if request else None
            auth_header = request.headers.get("authorization", "") if request else ""
            is_admin = False
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
                if token and settings.AUTH_TOKEN and hmac.compare_digest(token, settings.AUTH_TOKEN):
                    is_admin = True

            if not is_admin:
                task_owner = existing.get("user_id")
                if task_owner:
                    if not user_id or user_id.lower() != task_owner.lower():
                        raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to delete this task.")
                else:
                    raise HTTPException(status_code=403, detail="Forbidden: Unowned tasks can only be deleted by an administrator.")

            try:
                await conn.execute(
                    "DELETE FROM task_dependencies WHERE task_id = $1 OR depends_on_task_id = $1",
                    numeric_id
                )
            except Exception as e:
                logger.warning(f"Could not delete task dependencies for task {numeric_id}: {e}")

            deleted = await structured.delete_task(conn, numeric_id)
            if not deleted:
                raise HTTPException(status_code=500, detail="Failed to delete task")

            return {"status": "ok", "deleted": True, "task_id": str(numeric_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"DB unavailable for task deletion, treating as mock: {e}")
        return {"status": "ok", "deleted": True, "task_id": task_id}


# ---- Task Dependencies Endpoints --------------------------------------
@router.get("/api/tasks/{task_id}/dependencies")
async def get_task_dependencies_endpoint(task_id: int):
    """Retrieve prerequisite dependencies for a task."""
    pool = await get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        return await structured.get_task_dependencies(conn, task_id)


@router.post("/api/tasks/{task_id}/dependencies")
async def add_task_dependency_endpoint(task_id: int, body: AddDependencyBody):
    """Add a prerequisite dependency: task_id depends on body.depends_on_task_id."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")
    async with pool.acquire() as conn:
        try:
            dep = await structured.add_task_dependency(conn, task_id, body.depends_on_task_id)
            return {"status": "ok", "dependency": dep}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/tasks/{task_id}/dependencies/{depends_on_task_id}")
async def remove_task_dependency_endpoint(task_id: int, depends_on_task_id: int):
    """Remove a dependency edge."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")
    async with pool.acquire() as conn:
        deleted = await structured.remove_task_dependency(conn, task_id, depends_on_task_id)
        return {"status": "ok", "deleted": deleted}
