"""
Compass — FastAPI Application Shell.

This is the main entry point for the backend API server. It wires up:
  - Async database pool lifecycle (startup/shutdown)
  - CORS middleware
  - Bearer token authentication
  - All API endpoints defined in docs/api_contract.md (stub responses)

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, date, timezone
from typing import Optional, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from backend.config import get_settings
from backend.memory.db import init_pool, close_pool, get_pool
from backend.memory import structured, conversations
from backend.orchestrator import handle_message

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("compass")

# ---------------------------------------------------------------------------
# Lifespan — database pool init / teardown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    logger.info("🧭 Compass starting up — initializing database pool...")
    try:
        await init_pool()
        logger.info("✅ Database pool initialized")
    except Exception as e:
        logger.warning(f"⚠️  Database pool init failed (stubs will still work): {e}")
    yield
    logger.info("🧭 Compass shutting down — closing database pool...")
    await close_pool()
    logger.info("✅ Database pool closed")


# ---------------------------------------------------------------------------
# App Instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Compass API",
    description="Personal AI assistant with persistent memory",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware — CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth Dependency — Bearer Token
# ---------------------------------------------------------------------------
_bearer_scheme = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """Validate the Authorization: Bearer <token> header against AUTH_TOKEN."""
    if credentials.credentials != get_settings().AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return credentials.credentials


# ---------------------------------------------------------------------------
# Pydantic Models — Request / Response schemas matching api_contract.md
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    skill_used: Optional[str] = None
    data: Optional[dict] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    skill_called: Optional[str] = None
    created_at: str


class MessagesResponse(BaseModel):
    conversation_id: str
    messages: list[MessageOut]


class ProjectOut(BaseModel):
    id: int
    name: str
    domain: str
    description: Optional[str] = None
    created_at: str


class ProjectsResponse(BaseModel):
    projects: list[ProjectOut]


class TaskProjectRef(BaseModel):
    id: int
    name: str


class TaskOut(BaseModel):
    id: int
    domain: str
    project: Optional[TaskProjectRef] = None
    title: str
    due_date: Optional[str] = None
    status: str
    priority: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class TasksResponse(BaseModel):
    tasks: list[TaskOut]


class NearestDeadline(BaseModel):
    task_id: int
    title: str
    due_date: str


class DomainStats(BaseModel):
    project_count: int
    open_task_count: int
    nearest_deadline: Optional[NearestDeadline] = None
    last_activity: Optional[str] = None


class DashboardResponse(BaseModel):
    domains: dict[str, DomainStats]
    total_open_tasks: int
    total_projects: int


class TimelineEntry(BaseModel):
    type: str
    domain: str
    project: Optional[str] = None
    summary: str
    created_at: str


class TimelineResponse(BaseModel):
    entries: list[TimelineEntry]
    total: int
    has_more: bool


class ModelUsage(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UsageResponse(BaseModel):
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    by_model: dict[str, ModelUsage]


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    database: str
    db_connected: bool = False


# ---------------------------------------------------------------------------
# Helper — current UTC timestamp as ISO 8601
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---- 0. GET / (Redirect to Swagger Docs) -----------------------------------
@app.get("/", include_in_schema=False)
async def root():
    """Redirect root path to interactive Swagger documentation."""
    return RedirectResponse(url="/docs")


# ---- 1. POST /chat -------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _token: str = Depends(verify_token)):
    """Main conversational endpoint — wired to Nemotron router and orchestrator."""
    result = await handle_message(
        conversation_id=request.conversation_id,
        message=request.message,
    )
    return ChatResponse(**result)


# ---- 2. GET /conversations/{conversation_id}/messages --------------------
@app.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
async def get_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    _token: str = Depends(verify_token),
):
    """Get message history for a conversation from PostgreSQL."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conversations.get_recent_messages(conn, conversation_id, limit=limit)
            messages = [
                MessageOut(
                    id=r["id"],
                    role=r["role"],
                    content=r["content"],
                    skill_called=r.get("skill_called"),
                    created_at=r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                )
                for r in rows
            ]
            return MessagesResponse(conversation_id=conversation_id, messages=messages)
    except Exception as e:
        logger.warning(f"Database query failed for get_messages, returning empty list: {e}")
        return MessagesResponse(conversation_id=conversation_id, messages=[])


# ---- 3. GET /projects ----------------------------------------------------
@app.get("/projects", response_model=ProjectsResponse)
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
        return ProjectsResponse(projects=[])


# ---- 4. GET /tasks -------------------------------------------------------
@app.get("/tasks", response_model=TasksResponse)
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


# ---- 5. GET /dashboard ---------------------------------------------------
@app.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(_token: str = Depends(verify_token)):
    """Aggregate live counts via SQL (total open tasks, tasks due within 72 hours, project counts by domain)."""
    domains = {
        d: DomainStats(project_count=0, open_task_count=0, nearest_deadline=None, last_activity=None)
        for d in ("hackathon", "coursework", "code", "general")
    }

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # 1. Project counts by domain
            proj_rows = await conn.fetch(
                "SELECT domain, COUNT(*) AS count FROM projects GROUP BY domain"
            )
            for r in proj_rows:
                d = r["domain"]
                if d in domains:
                    domains[d].project_count = r["count"]

            # 2. Open tasks count by domain
            task_rows = await conn.fetch(
                "SELECT domain, COUNT(*) AS count FROM tasks WHERE status = 'open' GROUP BY domain"
            )
            for r in task_rows:
                d = r["domain"]
                if d in domains:
                    domains[d].open_task_count = r["count"]

            # 3. Nearest deadline per domain
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

            # 4. Last activity per domain (latest task update or creation)
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


# ---- 6. GET /memory/timeline ---------------------------------------------
@app.get("/memory/timeline", response_model=TimelineResponse)
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

            # Count total
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


# ---- 7. GET /admin/usage -------------------------------------------------
@app.get("/admin/usage", response_model=UsageResponse)
async def get_usage(_token: str = Depends(verify_token)):
    """Query the usage_log table to report total input/output tokens and estimated cost across models."""
    base_by_model = {
        model_id: ModelUsage(calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0)
        for model_id in get_settings().COST_PER_1M_INPUT
    }

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT model,
                       COUNT(*) AS calls,
                       COALESCE(SUM(input_tokens), 0) AS total_input,
                       COALESCE(SUM(output_tokens), 0) AS total_output,
                       COALESCE(SUM(estimated_cost_usd), 0.0) AS total_cost
                FROM usage_log
                GROUP BY model
                """
            )
            total_in = 0
            total_out = 0
            total_cost = 0.0

            for r in rows:
                m = r["model"]
                m_in = int(r["total_input"])
                m_out = int(r["total_output"])
                m_cost = float(r["total_cost"])

                total_in += m_in
                total_out += m_out
                total_cost += m_cost

                base_by_model[m] = ModelUsage(
                    calls=int(r["calls"]),
                    input_tokens=m_in,
                    output_tokens=m_out,
                    estimated_cost_usd=m_cost,
                )

            return UsageResponse(
                total_input_tokens=total_in,
                total_output_tokens=total_out,
                total_estimated_cost_usd=round(total_cost, 6),
                by_model=base_by_model,
            )
    except Exception as e:
        logger.warning(f"Database query failed for get_usage: {e}")
        return UsageResponse(
            total_input_tokens=0,
            total_output_tokens=0,
            total_estimated_cost_usd=0.0,
            by_model=base_by_model,
        )


# ---- 8. GET /health (no auth) --------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check with SELECT 1 ping against the asyncpg connection pool."""
    db_status = "disconnected"
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_status = "connected"
    except Exception:
        pass

    return HealthResponse(
        status="ok",
        version="0.1.0",
        database=db_status,
        db_connected=(db_status == "connected"),
    )
