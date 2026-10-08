"""
Compass — Admin, Health, and Usage Endpoints.
"""

import os
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.dependencies import verify_token
from backend.memory.db import get_pool
from backend.models import HealthResponse, ConsolidateRequest, ConsolidateResponse

logger = logging.getLogger("compass.routers.admin")

router = APIRouter(tags=["admin"])




@router.get("/", include_in_schema=False)
async def root():
    """Redirect root path to API documentation in dev, or return status in production."""
    from backend.config import get_settings
    settings = get_settings()
    if not settings.is_development():
        return {"status": "ok", "app": "Compass API"}
    return RedirectResponse(url="/docs")


@router.get("/api/admin/usage")
@router.get("/admin/usage")
async def get_usage(_token: str = Depends(verify_token)):
    """Returns token consumption breakdown, total requests, and cost from usage.py."""
    from backend.services.usage import get_usage_summary, hydrate_usage_from_db, _USAGE_STATE
    if not _USAGE_STATE:
        try:
            pool = await get_pool()
            await hydrate_usage_from_db(pool)
        except Exception:
            pass
    return get_usage_summary()


@router.get("/api/usage/summary")
@router.get("/api/telemetry")
async def get_public_usage_summary(request: Request):
    """Public usage summary and Nebius/NVIDIA architectural telemetry.
    Returns token breakdown and model metrics. Strips internal cost data unless caller has admin authentication.
    """
    from backend.services.usage import get_usage_summary, hydrate_usage_from_db, _USAGE_STATE
    from backend.dependencies import _get_current_identity

    if not _USAGE_STATE:
        try:
            pool = await get_pool()
            await hydrate_usage_from_db(pool)
        except Exception:
            pass

    summary = dict(get_usage_summary())
    ident = _get_current_identity(request)
    if not (ident and ident.is_admin):
        # Strip internal cost details for public callers
        for cost_key in (
            "estimated_cost_usd",
            "cost_savings_usd",
            "cost_breakdown",
            "savings_vs_gpt4o",
            "savings_vs_gemini_flash",
            "budget_used_usd",
        ):
            summary.pop(cost_key, None)
    return summary


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check with SELECT 1 ping against the asyncpg connection pool."""
    db_status = "disconnected"
    try:
        pool = await asyncio.wait_for(get_pool(), timeout=2.0)
        if pool is not None:
            async with pool.acquire(timeout=2.0) as conn:
                await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout=2.0)
            db_status = "connected"
    except Exception:
        pass

    raw_commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "unknown"
    commit_sha = raw_commit[:7] if len(raw_commit) >= 7 and raw_commit != "unknown" else raw_commit

    # Verify configuration validity without exposing any secret values
    config_ok = True
    try:
        from backend.config import get_settings
        settings = get_settings()
        if settings.is_production():
            missing_names, duplicate_names = settings.get_missing_production_secrets()
            if missing_names or duplicate_names:
                config_ok = False
        else:
            settings.validate_production_secrets()
    except Exception:
        config_ok = False

    return HealthResponse(
        status="ok" if config_ok else "config_error",
        version="0.1.0",
        database=db_status,
        db_connected=(db_status == "connected"),
        commit=commit_sha,
        config_ok=config_ok,
    )


@router.post("/admin/consolidate", response_model=ConsolidateResponse)
async def trigger_consolidation(
    req: ConsolidateRequest = ConsolidateRequest(),
    _token: str = Depends(verify_token),
):
    """Trigger memory consolidation and overdue task flagging on demand."""
    from backend.jobs.consolidate import run_consolidation

    try:
        report = await run_consolidation(
            similarity_threshold=req.similarity_threshold,
            stale_thread_days=req.stale_thread_days,
            dry_run=req.dry_run,
        )
        return ConsolidateResponse(
            status="ok",
            dry_run=req.dry_run,
            overdue_tasks_flagged=report.get("overdue_tasks_flagged", 0),
            duplicate_chunks_merged=report.get("duplicate_chunks_merged", 0),
            stale_conversations_rolled_up=report.get("stale_conversations_rolled_up", 0),
        )
    except Exception as e:
        logger.error(f"Consolidation job failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Consolidation job failed. Check server logs for details.")
