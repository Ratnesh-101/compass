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
import sys
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse

from backend.config import get_settings
from backend.memory.db import init_pool, close_pool
from backend.services import budget_context
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
    specialist_router,
    radar_router,
    career_router,
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
    # 0. Startup Database Safety Guard & Secrets Validation
    settings.validate_database_target()
    logger.info(f"🧭 Compass database target: {settings.get_masked_database_url()}")

    try:
        settings.validate_production_secrets()
        logger.info("✅ Production secrets validation: all required secrets set distinctly")
    except Exception as e:
        logger.error(f"⚠️ Production secrets validation issue (config_ok will report false): {e}")

    logger.info("🧭 Compass starting up — initializing database pool...")
    cleanup_task = None

    async def _periodic_cleanup_worker():
        while True:
            try:
                await asyncio.sleep(6 * 3600)  # every 6 hours
                from backend.services.rate_limiter import cleanup_stale_rate_limit_buckets
                from backend.services.budgets import prune_expired_guests
                from backend.services.oauth import cleanup_expired_oauth_states
                await cleanup_stale_rate_limit_buckets(older_than_hours=24)
                await prune_expired_guests(retention_days=int(getattr(settings, "GUEST_RETENTION_DAYS", 30)))
                if pool:
                    await cleanup_expired_oauth_states(pool)
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
        # Background startup seed for Internship Radar (in development/production only, never in tests)
        # Uses 'standard' lightweight sources to avoid hung scraper threads in web process
        if settings.ENVIRONMENT != "test" and "pytest" not in sys.modules:
            try:
                from backend.services.radar_sync import run_radar_sync
                asyncio.create_task(run_radar_sync("standard"))
            except Exception as seed_err:
                logger.warning(f"Could not trigger startup radar sync: {seed_err}")
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
        if "Content-Security-Policy" not in response.headers:
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
        if "compass_user_id" in request.cookies:
            response.delete_cookie("compass_user_id", path="/")
        return response


class BudgetContextMiddleware:
    """Pure ASGI middleware binding the caller's identity and a per-run Tavily counter.

    Pure ASGI (not BaseHTTPMiddleware) so the contextvars survive into streaming responses
    (SSE generators) and tasks spawned by the request. Identity resolution failures never
    break the request: the route's own auth dependency still produces the 401/403.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        identity = None
        try:
            from backend.dependencies import _get_current_identity
            ident = _get_current_identity(Request(scope))
            if ident and ident.id:
                identity = budget_context.BudgetIdentity(
                    identity_id=ident.id, is_guest=bool(ident.is_guest), is_admin=bool(ident.is_admin)
                )
        except Exception as exc:  # HTTPException from bad headers, etc.
            logger.debug("Budget context identity resolution skipped: %s", exc)
        identity_token = budget_context.bind_identity(identity)
        # One HTTP request is one run for non-admin callers; admin/system work is not run-capped.
        counter_token = None if (identity and identity.is_admin) else budget_context.begin_run_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            if counter_token is not None:
                budget_context.end_run_counter(counter_token)
            budget_context.reset_identity(identity_token)


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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    headers = getattr(exc, "headers", None)
    if isinstance(exc.detail, dict):
        content = dict(exc.detail)
        if "detail" not in content and "code" in content:
            content["detail"] = str(content["code"])
        return JSONResponse(status_code=exc.status_code, content=content, headers=headers)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)

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
app.add_middleware(BudgetContextMiddleware)  # outermost: binds identity/run counter for the whole request

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
app.include_router(specialist_router)
app.include_router(radar_router)
app.include_router(career_router)

from backend.services.rate_limiter import enforce_company_intel_guard

@app.get(
    "/opportunities/{opportunity_id}/company-intel",
    include_in_schema=False,
    dependencies=[Depends(enforce_company_intel_guard)],
)
async def company_intel_alias(opportunity_id: int, request: Request, refresh: bool = False):
    from backend.routers.career import get_company_intel_endpoint
    return await get_company_intel_endpoint(opportunity_id, request, refresh=refresh)

@app.get(
    "/opportunities/{opportunity_id}/job-analysis",
    include_in_schema=False,
)
async def job_analysis_alias(opportunity_id: int, request: Request):
    from backend.routers.career import get_job_analysis_report_endpoint
    return await get_job_analysis_report_endpoint(opportunity_id, request)


@app.get("/")
async def root_redirect(request: Request):
    """Root redirect handler. Resolves active frontend origin or redirects to frontend dev server."""
    query_str = request.url.query
    query_suffix = f"?{query_str}" if query_str else ""
    referer = request.headers.get("referer") or request.headers.get("origin")
    if referer:
        parsed = urllib.parse.urlparse(referer)
        if parsed.scheme and parsed.netloc:
            target = f"{parsed.scheme}://{parsed.netloc}/{query_suffix}"
            return RedirectResponse(url=target)

    frontend_url = "http://localhost:5173" if settings.is_development() else "https://compass-kappa-nine.vercel.app"
    return RedirectResponse(url=f"{frontend_url}/{query_suffix}")


