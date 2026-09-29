"""
Compass — Admin, Health, and Usage Endpoints.
"""

import os
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from backend.dependencies import verify_token
from backend.memory.db import get_pool
from backend.models import HealthResponse, ConsolidateRequest, ConsolidateResponse

logger = logging.getLogger("compass.routers.admin")

router = APIRouter(tags=["admin"])


@router.get("/", include_in_schema=False)
async def root():
    """Redirect root path to interactive Swagger documentation."""
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
async def get_public_usage_summary():
    """Public lightweight usage summary for the frontend live token counter.
    No authentication required — returns only aggregated totals, not per-model breakdowns.
    """
    from backend.services.usage import get_usage_summary, hydrate_usage_from_db, _USAGE_STATE
    if not _USAGE_STATE:
        try:
            pool = await get_pool()
            await hydrate_usage_from_db(pool)
        except Exception:
            pass
    full = get_usage_summary()
    return {
        "total_requests": full.get("total_requests", 0),
        "total_input_tokens": full.get("total_input_tokens", 0),
        "total_output_tokens": full.get("total_output_tokens", 0),
        "total_estimated_cost_usd": full.get("total_estimated_cost_usd", 0.0),
    }


@router.get("/health", response_model=HealthResponse)
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

    raw_commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT") or "unknown"
    commit_sha = raw_commit[:7] if len(raw_commit) >= 7 and raw_commit != "unknown" else raw_commit

    return HealthResponse(
        status="ok",
        version="0.1.0",
        database=db_status,
        db_connected=(db_status == "connected"),
        commit=commit_sha,
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
