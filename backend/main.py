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
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from backend.config import get_settings
from backend.memory.db import init_pool, close_pool, get_pool

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
    version: str
    database: str


# ---------------------------------------------------------------------------
# Helper — current UTC timestamp as ISO 8601
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ---- 1. POST /chat -------------------------------------------------------
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, _token: str = Depends(verify_token)):
    """Main conversational endpoint (stub)."""
    conv_id = request.conversation_id or str(uuid.uuid4())
    return ChatResponse(
        conversation_id=conv_id,
        response=f"Mock assistant reply to: {request.message}",
        skill_used="chat",
        data=None,
    )


# ---- 2. GET /conversations/{conversation_id}/messages --------------------
@app.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
async def get_messages(
    conversation_id: str,
    _token: str = Depends(verify_token),
):
    """Get message history for a conversation (stub)."""
    return MessagesResponse(
        conversation_id=conversation_id,
        messages=[
            MessageOut(
                id=1,
                role="user",
                content="Hello, Compass!",
                skill_called=None,
                created_at=_now_iso(),
            ),
            MessageOut(
                id=2,
                role="assistant",
                content="Hi! I'm Compass, your personal AI assistant. How can I help?",
                skill_called="chat",
                created_at=_now_iso(),
            ),
        ],
    )


# ---- 3. GET /projects ----------------------------------------------------
@app.get("/projects", response_model=ProjectsResponse)
async def get_projects(
    domain: Optional[str] = Query(None, description="Filter by domain"),
    _token: str = Depends(verify_token),
):
    """List all tracked projects (stub)."""
    mock_projects = [
        ProjectOut(id=1, name="Compass", domain="hackathon", description="Personal AI assistant", created_at=_now_iso()),
        ProjectOut(id=2, name="ML Coursework", domain="coursework", description="Fall 2026 ML assignments", created_at=_now_iso()),
        ProjectOut(id=3, name="dotfiles", domain="code", description="Personal dev environment configs", created_at=_now_iso()),
    ]
    if domain:
        mock_projects = [p for p in mock_projects if p.domain == domain]
    return ProjectsResponse(projects=mock_projects)


# ---- 4. GET /tasks -------------------------------------------------------
@app.get("/tasks", response_model=TasksResponse)
async def get_tasks(
    domain: Optional[str] = Query(None),
    project: Optional[str] = Query(None, description="Filter by project name"),
    status: Optional[str] = Query(None),
    due_before: Optional[str] = Query(None, description="ISO date"),
    _token: str = Depends(verify_token),
):
    """Query tasks with optional filters (stub)."""
    mock_tasks = [
        TaskOut(
            id=1, domain="hackathon",
            project=TaskProjectRef(id=1, name="Compass"),
            title="Implement /chat endpoint",
            due_date="2026-09-10",
            status="in_progress", priority="high",
            notes="Wire up Nemotron routing",
            created_at=_now_iso(), updated_at=_now_iso(),
        ),
        TaskOut(
            id=2, domain="coursework",
            project=TaskProjectRef(id=2, name="ML Coursework"),
            title="Submit Assignment 1",
            due_date="2026-09-15",
            status="open", priority="urgent",
            notes=None,
            created_at=_now_iso(), updated_at=_now_iso(),
        ),
        TaskOut(
            id=3, domain="code",
            project=None,
            title="Refactor CLI output formatting",
            due_date=None,
            status="open", priority="low",
            notes=None,
            created_at=_now_iso(), updated_at=_now_iso(),
        ),
    ]

    if domain:
        mock_tasks = [t for t in mock_tasks if t.domain == domain]
    if status:
        mock_tasks = [t for t in mock_tasks if t.status == status]
    if project:
        mock_tasks = [t for t in mock_tasks if t.project and t.project.name == project]

    return TasksResponse(tasks=mock_tasks)


# ---- 5. GET /dashboard ---------------------------------------------------
@app.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(_token: str = Depends(verify_token)):
    """Aggregated stats for the sidebar (stub)."""
    domains = {}
    for d in ("hackathon", "coursework", "code", "general"):
        domains[d] = DomainStats(
            project_count=0,
            open_task_count=0,
            nearest_deadline=None,
            last_activity=None,
        )
    # Populate with some sample data
    domains["hackathon"] = DomainStats(
        project_count=1, open_task_count=1,
        nearest_deadline=NearestDeadline(task_id=1, title="Implement /chat endpoint", due_date="2026-09-10"),
        last_activity=_now_iso(),
    )
    domains["coursework"] = DomainStats(
        project_count=1, open_task_count=1,
        nearest_deadline=NearestDeadline(task_id=2, title="Submit Assignment 1", due_date="2026-09-15"),
        last_activity=_now_iso(),
    )
    return DashboardResponse(
        domains=domains,
        total_open_tasks=2,
        total_projects=3,
    )


# ---- 6. GET /memory/timeline ---------------------------------------------
@app.get("/memory/timeline", response_model=TimelineResponse)
async def get_timeline(
    domain: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _token: str = Depends(verify_token),
):
    """Chronological memory entries for the timeline view (stub)."""
    mock_entries = [
        TimelineEntry(type="task_created", domain="hackathon", project="Compass", summary="Created task: Implement /chat endpoint", created_at=_now_iso()),
        TimelineEntry(type="code_context", domain="code", project="dotfiles", summary="Indexed 12 config files from dotfiles repo", created_at=_now_iso()),
        TimelineEntry(type="conversation", domain="general", project=None, summary="Discussed project architecture and LLM routing strategy", created_at=_now_iso()),
    ]

    if domain:
        mock_entries = [e for e in mock_entries if e.domain == domain]

    total = len(mock_entries)
    sliced = mock_entries[offset : offset + limit]
    return TimelineResponse(
        entries=sliced,
        total=total,
        has_more=(offset + limit) < total,
    )


# ---- 7. GET /admin/usage -------------------------------------------------
@app.get("/admin/usage", response_model=UsageResponse)
async def get_usage(_token: str = Depends(verify_token)):
    """Token usage statistics (stub)."""
    return UsageResponse(
        total_input_tokens=0,
        total_output_tokens=0,
        total_estimated_cost_usd=0.0,
        by_model={
            model_id: ModelUsage(calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0)
            for model_id in get_settings().COST_PER_1M_INPUT
        },
    )


# ---- 8. GET /health (no auth) --------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check — no auth required."""
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
    )
