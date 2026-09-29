"""
Compass — FastAPI Application Shell.

This is the main entry point for the backend API server. It wires up:
  - Async database pool lifecycle (startup/shutdown)
  - CORS middleware
  - Domain API routers
  - Backward-compatible symbols and rate-limit stores

Run with:
    uvicorn backend.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.memory.db import init_pool, close_pool
from backend.dependencies import (
    _rate_store,
    _agent_rate_store,
    rate_limit,
    agent_rate_limit,
    verify_token,
    _get_current_user_id,
    _now_iso,
)
from backend.models import (
    ChatRequest,
    ChatResponse,
    MessageOut,
    MessagesResponse,
    ProjectOut,
    ProjectsResponse,
    TaskProjectRef,
    TaskOut,
    TasksResponse,
    NearestDeadline,
    DomainStats,
    DashboardResponse,
    TimelineEntry,
    TimelineResponse,
    ModelUsage,
    UsageResponse,
    HealthResponse,
    ConversationUpdate,
    ConsolidateRequest,
    ConsolidateResponse,
    FrontendTaskOut,
    CreateTaskRequest,
    UpdateTaskRequest,
    PublicChatRequest,
    PublicChatResponse,
    LogMemoryRequest,
    StreamChatRequest,
    AgentRequest,
    AgentConfirmRequest,
    AgentUndoRequest,
    FeasibilityRequest,
    ProposeScheduleBody,
    CommitScheduleBody,
    UpdatePreferencesBody,
    SelectAccountBody,
    QuickConnectBody,
    AddDependencyBody,
    ReactiveCheckBody,
)
from backend.routers import (
    admin_router,
    tasks_router,
    chat_router,
    agent_router,
    calendar_router,
    auth_router,
    specialist_router,
)

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
        pool = await init_pool()
        logger.info("✅ Database pool initialized")
        from backend.services.usage import hydrate_usage_from_db
        await hydrate_usage_from_db(pool)
    except Exception as e:
        logger.warning(f"⚠️  Database pool init failed (stubs will still work): {e}")

    yield
    logger.info("🧭 Compass shutting down — closing database pool...")
    await close_pool()
    logger.info("✅ Database pool closed")


# ---------------------------------------------------------------------------
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforce standard security headers on all HTTP responses (SEC-01)."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https:;"
        )
        if request.url.scheme == "https" or settings.is_production():
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


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
# Middleware — Security Headers & CORS
# ---------------------------------------------------------------------------
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "x-user-id", "Accept", "Origin", "X-Requested-With"],
)

# ---------------------------------------------------------------------------
# Router Registration
# ---------------------------------------------------------------------------
app.include_router(admin_router)
app.include_router(tasks_router)
app.include_router(chat_router)
app.include_router(agent_router)
app.include_router(calendar_router)
app.include_router(auth_router)
app.include_router(specialist_router)
