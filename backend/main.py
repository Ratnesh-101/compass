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

import asyncio
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
    migration_router,
    profile_router,
    persona_router,
    parked_router,
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
    # 0. Startup Secrets Validation (fails immediately if production secrets are missing or reused)
    settings.validate_production_secrets()

    logger.info("🧭 Compass starting up — initializing database pool...")
    cleanup_task = None

    async def _periodic_cleanup_worker():
        while True:
            try:
                await asyncio.sleep(6 * 3600)  # every 6 hours
                from backend.services.rate_limiter import cleanup_stale_rate_limit_buckets
                from backend.services.budgets import prune_expired_guests
                await cleanup_stale_rate_limit_buckets(older_than_hours=24)
                await prune_expired_guests(retention_days=int(getattr(settings, "GUEST_RETENTION_DAYS", 30)))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Periodic background cleanup error: {e}")

    try:
        pool = await init_pool()
        logger.info("✅ Database pool initialized")
        from backend.services.usage import hydrate_usage_from_db
        await hydrate_usage_from_db(pool)
        from backend.routers.auth import load_sessions_from_db
        await load_sessions_from_db(pool)
        cleanup_task = asyncio.create_task(_periodic_cleanup_worker())

        # Startup check: verify configured models exist in Nebius catalog (fail loudly, never silently fall back)
        if settings.is_production() or (settings.NEBIUS_API_KEY and not settings.NEBIUS_API_KEY.startswith("mock-")):
            from backend.services.model_check import check_models_catalog
            routed_roles = {
                "router": settings.ROUTER_MODEL,
                "skill": settings.SKILL_MODEL,
                "reasoning": settings.REASONING_MODEL,
                "synthesis": settings.SYNTHESIS_MODEL,
                "embedding": settings.EMBEDDING_MODEL,
            }
            check_models_catalog(
                base_url=settings.NEBIUS_BASE_URL,
                api_key=settings.NEBIUS_API_KEY,
                required_models=set(routed_roles.values()),
                fail_loudly=settings.is_production(),
                routed_roles=routed_roles,
            )
    except Exception as e:
        logger.warning(f"⚠️  Database pool init failed (stubs will still work): {e}")

    yield
    if cleanup_task:
        cleanup_task.cancel()
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
        if not get_settings().is_development() and request.url.path in ("/docs", "/redoc", "/openapi.json"):
            return Response(status_code=404, content="Not Found")
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
_is_dev = settings.is_development()

app = FastAPI(
    title="Compass API",
    description="Personal AI assistant with persistent memory",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
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
    allow_headers=[
        "Authorization",
        "Content-Type",
        "x-user-id",
        "x-guest-token",
        "x-guest-id",
        "Accept",
        "Origin",
        "X-Requested-With",
    ],
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
app.include_router(migration_router)
app.include_router(profile_router)
app.include_router(persona_router)
app.include_router(parked_router)

