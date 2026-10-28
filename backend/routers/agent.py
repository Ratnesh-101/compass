"""
Compass — Autonomous Agent Endpoints.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend import dependencies as _dependencies
from backend.config import get_settings
from backend.dependencies import (
    _get_current_identity,
    _get_or_create_user_id,
    agent_rate_limit,
    verify_token,
)
from backend.memory.db import get_pool
from backend.models import (
    AgentRequest,
    AgentConfirmRequest,
    AgentUndoRequest,
    FeasibilityRequest,
)

logger = logging.getLogger("compass.routers.agent")
settings = get_settings()

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/run", dependencies=[Depends(agent_rate_limit)])
async def agent_run(req: AgentRequest, request: Request):
    """Stream the agent's ReAct execution trace via SSE."""
    from backend.agent import run_agent, _PENDING_CONFIRMATION_EVENTS, count_active_agent_runs, MAX_CONCURRENT_AGENT_RUNS

    if req.run_id and req.run_id in _PENDING_CONFIRMATION_EVENTS and hasattr(req, "action") and req.action:
        evt, outcome = _PENDING_CONFIRMATION_EVENTS[req.run_id]
        outcome["action"] = req.action
        outcome["feedback"] = getattr(req, "feedback", None) or ""
        evt.set()
        return {"status": "ok", "message": f"Action '{req.action}' delivered to active run {req.run_id}."}

    pool = await get_pool()

    if not getattr(req, "action", None) and not req.run_id:
        active_count = await count_active_agent_runs(pool)
        if active_count >= MAX_CONCURRENT_AGENT_RUNS:
            raise HTTPException(
                status_code=429,
                detail=f"Concurrent active agent runs cap reached ({active_count}/{MAX_CONCURRENT_AGENT_RUNS}). Please complete or wait for existing runs to finish.",
            )

    agent_user_id = _get_or_create_user_id(request)

    async def agent_event_generator():
        import asyncio
        try:
            async for step in run_agent(
                goal=req.goal,
                pool=pool,
                max_steps=req.max_steps or 8,
                enable_critic=req.enable_critic if req.enable_critic is not None else True,
                confirmed_actions=getattr(req, "confirmed_actions", []),
                run_id=req.run_id,
                action=getattr(req, "action", None),
                feedback=getattr(req, "feedback", None),
                confirm_timeout_seconds=getattr(req, "confirm_timeout_seconds", 300.0),
                wait_for_confirmation=getattr(req, "wait_for_confirmation", False),
                conversation_id=req.conversation_id,
                user_id=agent_user_id,
            ):
                if await request.is_disconnected():
                    logger.info("Client disconnected from agent SSE stream; terminating run %s", req.run_id)
                    return
                yield step.to_sse()
        except asyncio.CancelledError:
            logger.info("Agent SSE stream cancelled by client disconnect.")
            return
        except Exception:
            logger.exception("Agent stream error")
            yield f"data: {json.dumps({'type': 'error', 'content': 'An internal error occurred.'})}\n\n"

    return StreamingResponse(
        agent_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/confirm")
async def agent_confirm(req: AgentConfirmRequest, request: Request):
    """Execute previously confirmed state-mutating actions from an agent run.

    The run's registered pending actions are claimed atomically: ownership, the confirmation TTL,
    single use and argument integrity are enforced, and the STORED arguments are executed, never
    client-supplied ones. Admin overrides are audit-logged before execution.
    """
    from backend.agent import execute_confirmed_actions, get_agent_run, save_agent_run
    from backend.agent_pending import PendingClaimError, claim_run_actions, mark_action_executed, mark_action_failed

    ident = _dependencies._get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Authentication required")

    pool = await get_pool()
    actions = getattr(req, "actions", None) or []
    run_id = getattr(req, "run_id", None)
    caller = ident.id
    is_admin = ident.is_admin
    audit_record_ids: list[int] = []
    claimed_action_ids: list[str] = []

    if not run_id:
        raise HTTPException(status_code=400, detail="run_id is required to confirm actions.")
    if not pool:
        raise HTTPException(status_code=503, detail="Database unavailable")

    existing_run = await get_agent_run(pool, run_id)
    if not existing_run:
        raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found.")

    pending = existing_run.get("pending_actions") or []
    if not pending:
        raise HTTPException(
            status_code=400,
            detail="No pending unconfirmed actions found for this agent run (replay rejected).",
        )

    try:
        claimed = await claim_run_actions(pool, run_id, ident, actions or None)
        actions = [{"tool": c["tool"], "args": c["args"]} for c in claimed]
        claimed_action_ids = [c["action_id"] for c in claimed]
    except PendingClaimError as claim_err:
        if not (is_admin and claim_err.unregistered):
            raise HTTPException(status_code=claim_err.status_code, detail=claim_err.detail) from claim_err
        # Admin override on a legacy run that predates pending_actions registration.
        pending_tools = {p.get("tool") for p in pending if isinstance(p, dict)}
        for a in actions:
            if a.get("tool") not in pending_tools:
                raise HTTPException(
                    status_code=400,
                    detail=f"Action '{a.get('tool')}' does not match any pending proposal for run '{run_id}'.",
                ) from claim_err
        actions = actions or pending

    # Write+commit admin-override audit row BEFORE executing action; abort if write fails
    if is_admin:
        try:
            logger.warning("SECURITY AUDIT: Admin override invoked for run %s by %s", run_id, caller)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for a in actions:
                        aid = await conn.fetchval(
                            """
                            INSERT INTO agent_audit_log (run_id, tool, args, approved_by, status, new_state)
                            VALUES ($1, $2, $3::jsonb, 'admin_override', 'pending_execution', '{"status": "pending_execution"}'::jsonb)
                            RETURNING id
                            """,
                            run_id,
                            a.get("tool", "unknown"),
                            json.dumps(a.get("args") or {}),
                        )
                        audit_record_ids.append(aid)
        except Exception as log_err:
            logger.error("Failed to record admin override in agent_audit_log: %s", log_err)
            for aid in claimed_action_ids:
                await mark_action_failed(pool, aid, "audit log failure")
            raise HTTPException(
                status_code=500,
                detail="Security audit log failure: admin override action aborted.",
            ) from log_err

    try:
        await save_agent_run(
            pool,
            run_id,
            existing_run.get("goal", ""),
            "completed",
            existing_run.get("steps", []),
            existing_run.get("messages", []),
            pending_actions=[],
            conversation_id=existing_run.get("conversation_id"),
        )
    except Exception as e:
        logger.warning(f"Could not clear pending actions on run {run_id}: {e}")

    results = await execute_confirmed_actions(
        actions, pool, run_id=run_id, approved_by="admin_override" if is_admin else "user", user_id=caller
    )

    for aid, res in zip(claimed_action_ids, results):
        try:
            if res.get("status") == "error":
                await mark_action_failed(pool, aid, str(res.get("message", "")))
            else:
                await mark_action_executed(pool, aid)
        except Exception as mark_err:
            logger.warning("Could not finalize pending action %s: %s", aid, mark_err)

    # Record post-execution outcome in audit log
    if is_admin and audit_record_ids:
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for aid, res in zip(audit_record_ids, results):
                        await conn.execute(
                            """
                            UPDATE agent_audit_log
                            SET status = 'executed', new_state = $1::jsonb
                            WHERE id = $2
                            """,
                            json.dumps({"status": "executed", "result": res}),
                            aid,
                        )
        except Exception as outcome_err:
            logger.warning("Failed to record post-execution outcome in agent_audit_log: %s", outcome_err)

    return {"status": "ok", "results": results}


@router.post("/undo")
async def agent_undo(req: AgentUndoRequest, request: Request):
    """Revert an agent-executed mutation using agent_audit_log with identity ownership verification."""
    from backend.agent import undo_last_agent_action

    ident = _dependencies._get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Authentication required")

    pool = await get_pool()
    audit_log_id = getattr(req, "audit_log_id", None)
    caller = ident.id
    is_admin = ident.is_admin

    if not is_admin and pool:
        async with pool.acquire() as conn:
            if audit_log_id:
                row = await conn.fetchrow("SELECT * FROM agent_audit_log WHERE id = $1", audit_log_id)
            elif req.run_id:
                row = await conn.fetchrow(
                    "SELECT * FROM agent_audit_log WHERE run_id = $1 AND is_reverted = FALSE ORDER BY id DESC LIMIT 1",
                    req.run_id,
                )
            else:
                row = None
            if row:
                approved_by = row.get("approved_by") or ""
                args = row.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                owner = args.get("user_id") or approved_by
                if owner and owner.lower() != caller.lower() and approved_by != "admin_override":
                    raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to undo another user's action.")

    # Scope the undo itself to the caller so an empty request can never revert someone else's action.
    result = await undo_last_agent_action(
        pool, run_id=req.run_id, audit_log_id=audit_log_id, owner_id=None if is_admin else caller
    )
    return result


@router.get("/activity")
async def agent_activity(request: Request, limit: int = 30):
    """Retrieve recent agent audit log entries scoped to the authenticated caller to prevent cross-user data leakage."""

    ident = _dependencies._get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Authentication required")

    pool = await get_pool()
    if not pool:
        return {"activity": []}

    async with pool.acquire() as conn:
        if ident.is_admin:
            rows = await conn.fetch(
                "SELECT id, run_id, tool, args, affected_table, affected_id, previous_state, new_state, approved_by, is_reverted, created_at "
                "FROM agent_audit_log ORDER BY id DESC LIMIT $1",
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, run_id, tool, args, affected_table, affected_id, previous_state, new_state, approved_by, is_reverted, created_at "
                "FROM agent_audit_log WHERE approved_by = $1 OR args->>'user_id' = $1 ORDER BY id DESC LIMIT $2",
                ident.id,
                limit,
            )

    return {
        "activity": [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "tool": r["tool"],
                "args": r["args"],
                "affected_table": r["affected_table"],
                "affected_id": r["affected_id"],
                "previous_state": r["previous_state"],
                "new_state": r["new_state"],
                "approved_by": r["approved_by"],
                "is_reverted": r.get("is_reverted", False),
                "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            }
            for r in rows
        ]
    }


@router.get("/critique-stats")
async def agent_critique_stats(request: Request):
    """Surface critique effectiveness metrics computed from persisted agent runs.
    Strips individual run details and goals to high-level aggregate counts unless caller is authenticated admin.
    """
    from backend.agent import get_critique_stats

    ident = _dependencies._get_current_identity(request)
    is_admin = bool(ident and ident.is_admin)

    pool = await get_pool()
    stats = await get_critique_stats(pool)
    if not is_admin:
        # Strip granular run goals and evaluations, exposing only high-level aggregate telemetry
        stats = {
            "total_runs_analyzed": stats.get("total_runs_analyzed", 0),
            "runs_with_critique": stats.get("runs_with_critique", 0),
            "critique_issues_flagged": stats.get("critique_issues_flagged", 0),
            "critique_effectiveness_rate": stats.get("critique_effectiveness_rate", 0.0),
        }
    return stats


@router.get("/runs")
async def agent_list_runs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    conversation_id: Optional[str] = Query(None),
):
    """Retrieve the caller's recent agent runs (admins see all) for run history."""
    ident = _dependencies._get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Authentication required")
    owner = None if ident.is_admin else ident.id
    pool = await get_pool()
    if not pool:
        return {"runs": [], "total": 0}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, goal, status, conversation_id, accumulated_steps, pending_actions, created_at, updated_at
            FROM agent_runs
            WHERE ($1::text IS NULL OR lower(user_id) = lower($1::text))
              AND ($2::text IS NULL OR conversation_id = $2)
            ORDER BY created_at DESC
            LIMIT $3
            """,
            owner,
            conversation_id,
            limit,
        )
    runs = []
    for r in rows:
        steps_raw = r.get("accumulated_steps") or "[]"
        try:
            steps_list = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
        except Exception:
            steps_list = []

        pending_raw = r.get("pending_actions") or "[]"
        try:
            pending_list = json.loads(pending_raw) if isinstance(pending_raw, str) else pending_raw
        except Exception:
            pending_list = []

        runs.append({
            "id": r["id"],
            "goal": r["goal"],
            "status": r["status"],
            "conversation_id": r.get("conversation_id"),
            "steps_count": len(steps_list),
            "steps": steps_list,
            "pending_actions_count": len(pending_list),
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            "updated_at": r["updated_at"].isoformat() if hasattr(r["updated_at"], "isoformat") else str(r["updated_at"]),
        })
    return {"runs": runs, "total": len(runs)}


@router.get("/runs/{run_id}")
async def agent_get_run(run_id: str, request: Request):
    """Fetch persistent agent run state by run_id (owner or admin only)."""
    from backend.agent import get_agent_run

    ident = _dependencies._get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Authentication required")
    pool = await get_pool()
    run = await get_agent_run(pool, run_id)
    owner = (run or {}).get("user_id") or ""
    if not run or (not ident.is_admin and owner.lower() != ident.id.lower()):
        raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found.")
    return run


@router.get("/capabilities")
async def agent_capabilities():
    """Return the list of tools the agent has access to."""
    from backend.skills import get_tool_definitions

    tools = []
    for t in get_tool_definitions():
        func = t.get("function", {})
        tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": list(func.get("parameters", {}).get("properties", {}).keys()),
        })

    return {
        "tools": tools,
        "total": len(tools),
        "models": {
            "reasoning": settings.SKILL_MODEL,
            "synthesis": settings.SYNTHESIS_MODEL,
            "routing": settings.ROUTER_MODEL,
        },
        "tavily_abstain_first": getattr(settings, "TAVILY_ABSTAIN_FIRST", False),
    }


@router.get("/proactive-briefing")
async def get_latest_proactive_briefing(request: Request):
    """Retrieve the latest proactive nightly agent run.

    The nightly run audits every tenant's deadlines, so its briefing is only shown to admins.
    """
    ident = _dependencies._get_current_identity(request)
    if not ident or not ident.is_admin:
        return {"found": False, "message": "No proactive nightly briefing found yet."}
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, goal, status, accumulated_steps, messages, pending_actions, created_at, updated_at
            FROM agent_runs
            WHERE id LIKE 'proactive_nightly_%' OR goal ILIKE '%Nightly Proactive Consolidation%'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
    if not row:
        return {"found": False, "message": "No proactive nightly briefing found yet."}

    steps = json.loads(row["accumulated_steps"]) if isinstance(row["accumulated_steps"], str) else (row["accumulated_steps"] or [])
    briefing_text = ""
    for s in reversed(steps):
        if s.get("type") in ("synthesize", "observe") and s.get("content"):
            briefing_text = s.get("content")
            break
    if not briefing_text and steps:
        briefing_text = steps[-1].get("content", "")

    return {
        "found": True,
        "run_id": row["id"],
        "goal": row["goal"],
        "status": row["status"],
        "briefing": briefing_text,
        "steps_count": len(steps),
        "accumulated_steps": steps,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/trigger-nightly")
async def trigger_nightly_consolidation_endpoint(_token: str = Depends(verify_token)):
    """Trigger the nightly consolidation job and autonomous proactive briefing run."""
    from backend.jobs.consolidate import run_consolidation
    pool = await get_pool()
    result = await run_consolidation(dry_run=False, pool=pool)
    return {"status": "ok", "consolidation": result}


from backend.services.rate_limiter import enforce_feasibility_guard

@router.post("/feasibility", dependencies=[Depends(agent_rate_limit), Depends(enforce_feasibility_guard)])
async def agent_feasibility(request: Request, req: FeasibilityRequest):
    """Stream feasibility evaluation via SSE."""
    from backend.agents.feasibility import run_feasibility_review
    from backend.dependencies import _get_or_create_user_id
    pool = await get_pool()
    user_id = _get_or_create_user_id(request)

    days = req.days or 5
    hours = req.hours_per_day or 4.0

    async def event_generator():
        try:
            async for ev in run_feasibility_review(
                pool, days=days, hours_per_day=hours,
                domain=req.domain,
                user_id=user_id,
            ):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception:
            logger.exception("Feasibility stream failed")
            yield f"data: {json.dumps({'type': 'error', 'content': 'An internal error occurred during feasibility streaming.'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
