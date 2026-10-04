"""
Compass — Task, Project, and Timeline Endpoints.
"""

import hmac
import logging
from datetime import date, datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.config import get_settings
from backend.dependencies import (
    _get_current_identity,
    _get_or_create_user_id,
    rate_limit,
    verify_token,
)
from backend.memory import structured
from backend.memory.db import get_pool
from backend.models import (
    CreateTaskRequest,
    DashboardResponse,
    DomainStats,
    FrontendTaskOut,
    NearestDeadline,
    ProjectOut,
    ProjectsResponse,
    TaskOut,
    TaskProjectRef,
    TasksResponse,
    TimelineEntry,
    TimelineResponse,
    UpdateTaskRequest,
)
from backend.routers.tasks_verification import router as tasks_verification_router
from backend.services.task_service import (
    build_frontend_task,
    format_countdown,
    handle_create_task,
)

logger = logging.getLogger("compass.routers.tasks")

router = APIRouter(tags=["tasks"])
settings = get_settings()

# Mount verification, dependencies, and demo seeding endpoints
router.include_router(tasks_verification_router)


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
        ident = _get_current_identity(request)
        user_id = ident.id if ident else None
        pool = await get_pool()
        async with pool.acquire() as conn:
            raw_tasks = await structured.list_tasks(conn, domain=domain, user_id=user_id)
            result = []
            for t in raw_tasks:
                proj_name = t.get("project", {}).get("name", "General") if t.get("project") else "General"
                result.append(build_frontend_task(t, proj_name=proj_name))
            return result
    except Exception as e:
        logger.warning(f"Error fetching frontend tasks from DB: {e}")
        return []


# ---- POST /api/tasks --------------------------------------------------
@router.post("/api/tasks", response_model=FrontendTaskOut, dependencies=[Depends(rate_limit)])
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
        if not pool:
            raise HTTPException(status_code=503, detail="Database unavailable")
        async with pool.acquire() as conn:
            return await handle_create_task(conn, req, user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"DB unavailable for task creation: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable") from e


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
            return build_frontend_task(updated, proj_name=proj_name_out)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"DB unavailable for task update: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")


# ---- DELETE /api/tasks/{task_id} --------------------------------------
@router.delete("/api/tasks/{task_id}")
async def delete_frontend_task(task_id: str, request: Request):
    """Direct user endpoint to delete a task or deadline without relying on AI chat."""
    if not task_id.isdigit():
        if task_id.startswith(("demo-", "mock-", "sim-")):
            if getattr(settings, "ENVIRONMENT", "").lower() in ("development", "test"):
                return {"status": "ok", "deleted": True, "task_id": task_id}
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    numeric_id = int(task_id)

    try:
        pool = await get_pool()
        if not pool:
            raise HTTPException(status_code=503, detail="Database unavailable")
        async with pool.acquire() as conn:
            existing = await structured.get_task(conn, numeric_id)
            if not existing:
                raise HTTPException(status_code=404, detail="Task not found")

            # Ownership check (IDOR mitigation)
            ident = _get_current_identity(request) if request else None
            is_admin = bool(ident and ident.is_admin)
            user_id = ident.id if ident else _get_or_create_user_id(request)

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
        logger.error(f"DB error during task deletion: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable") from e
