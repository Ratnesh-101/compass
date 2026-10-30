"""Idempotent chat mutations and per-request timezone context.

A client-generated request id travels with each chat request. The first request that mutates data
stores its result under (owner, request_id); a retry carrying the same id gets that result back and
changes nothing. The id is claimed before the work starts, so two concurrent sends of the same id
cannot both create tasks.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from backend.services.task_time import is_valid_timezone, request_timezone, resolve_effective_timezone

logger = logging.getLogger("compass.services.chat_idempotency")

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
IN_FLIGHT_SECONDS = 300
PRUNE_ONE_IN = 50
# Only successful state changes are remembered; reads and previews are always recomputed.
REPLAYABLE_SKILLS = frozenset({"add_task", "undo", "pending_action_confirm"})

CLAIMED, REPLAY, IN_FLIGHT = "claimed", "replay", "in_flight"
IN_FLIGHT_REPLY = "That request is still being processed. Give it a moment, then check your tasks before retrying."


def normalize_request_id(raw: Any) -> Optional[str]:
    """A safe request id, or None (the request then runs without idempotency)."""
    if isinstance(raw, str) and REQUEST_ID_PATTERN.match(raw.strip()):
        return raw.strip()
    return None


def may_mutate(message: Any) -> bool:
    """False for messages that cannot change data (plain chat sends no tools), so they skip the claim."""
    from backend.router_helpers import is_pending_action_cancel, is_pending_action_confirm, is_undo_request, message_needs_tools
    from backend.services.task_intent import is_intake_intent

    text = message if isinstance(message, str) else ""
    return (
        message_needs_tools(text) or is_pending_action_confirm(text) or is_pending_action_cancel(text)
        or is_undo_request(text) or is_intake_intent(text)
    )


def is_replayable(result: Dict[str, Any]) -> bool:
    from backend.agent_types import MUTATING_TOOLS

    skill = result.get("skill_used")
    return bool(result.get("success")) and (skill in REPLAYABLE_SKILLS or skill in MUTATING_TOOLS)


def committed_summary(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the client needs to know that a change is already saved, even if the stream breaks."""
    if not is_replayable(result):
        return None
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    count = data.get("created_count") or len(data.get("deleted_tasks") or []) or 1
    return {"skill_used": result.get("skill_used"), "count": count}


async def _claim(conn: Any, owner: str, request_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    inserted = await conn.fetchval(
        "INSERT INTO chat_request_log (owner_identity, request_id) VALUES ($1, $2) "
        "ON CONFLICT DO NOTHING RETURNING request_id",
        owner, request_id,
    )
    if inserted:
        if random.randrange(PRUNE_ONE_IN) == 0:
            await conn.execute("DELETE FROM chat_request_log WHERE created_at < now() - interval '1 day'")
        return CLAIMED, None
    row = await conn.fetchrow(
        "SELECT state, response FROM chat_request_log WHERE owner_identity = $1 AND request_id = $2",
        owner, request_id,
    )
    if row and row["state"] == "done" and row["response"] is not None:
        stored = row["response"]
        return REPLAY, json.loads(stored) if isinstance(stored, str) else stored
    # Take over a claim whose worker died (stale), otherwise report it as still running.
    taken = await conn.fetchval(
        "UPDATE chat_request_log SET created_at = now() WHERE owner_identity = $1 AND request_id = $2 "
        "AND state = 'pending' AND created_at < now() - make_interval(secs => $3) RETURNING request_id",
        owner, request_id, float(IN_FLIGHT_SECONDS),
    )
    return (CLAIMED, None) if taken else (IN_FLIGHT, None)


async def peek_replay(pool: Any, owner: str, request_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Stored result for an already-completed request id (used to skip the model call on retry)."""
    if not (pool and request_id):
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT response FROM chat_request_log WHERE owner_identity = $1 AND request_id = $2 AND state = 'done'",
                owner, request_id,
            )
        stored = row["response"] if row else None
        return json.loads(stored) if isinstance(stored, str) else stored
    except Exception as e:
        logger.warning("Idempotency lookup failed (continuing without replay): %s", e)
        return None


async def _finish(pool: Any, owner: str, request_id: str, result: Optional[Dict[str, Any]]) -> None:
    """Store a replayable result; release the claim for everything else so a retry can run."""
    try:
        async with pool.acquire() as conn:
            if result is not None and is_replayable(result):
                await conn.execute(
                    "UPDATE chat_request_log SET state = 'done', response = $3::jsonb "
                    "WHERE owner_identity = $1 AND request_id = $2",
                    owner, request_id, json.dumps(result, default=str),
                )
            else:
                await conn.execute(
                    "DELETE FROM chat_request_log WHERE owner_identity = $1 AND request_id = $2 AND state = 'pending'",
                    owner, request_id,
                )
    except Exception as e:
        logger.error("Could not finalize chat request %s: %s", request_id, e)


async def _usable_pool(pool: Any) -> Any:
    if pool is not None:
        return pool
    from backend.memory.db import get_pool

    try:
        return await get_pool()
    except Exception:
        return None


async def run_chat_request(
    core: Callable[..., Awaitable[Dict[str, Any]]],
    args: tuple,
    kwargs: Dict[str, Any],
    *,
    request_id: Any = None,
    tz: Any = None,
) -> Dict[str, Any]:
    """Run one chat turn with the user's timezone in context and at-most-once mutation semantics."""
    bound = inspect.signature(core).bind_partial(*args, **kwargs).arguments
    owner = bound.get("user_id") or bound.get("guest_id") or "default_user"
    rid = normalize_request_id(request_id) if may_mutate(bound.get("message")) else None
    pool = bound.get("pool")
    if rid or not is_valid_timezone(tz):
        pool = await _usable_pool(pool)

    claimed = False
    if rid and pool:
        try:
            async with pool.acquire() as conn:
                state, stored = await _claim(conn, owner, rid)
        except Exception as e:
            logger.warning("Idempotency claim failed (continuing without it): %s", e)
            state, stored = "unavailable", None
        if state == REPLAY and stored is not None:
            return {**stored, "replayed": True}
        if state == IN_FLIGHT:
            return {
                "conversation_id": bound.get("conversation_id"), "response": IN_FLIGHT_REPLY,
                "message": IN_FLIGHT_REPLY, "skill_used": "chat", "success": False, "data": None,
                "verifiable": False, "routing_latency_ms": 0,
            }
        claimed = state == CLAIMED

    token = request_timezone.set(await resolve_effective_timezone(pool, owner, tz))

    async def run_and_finish() -> Dict[str, Any]:
        result: Optional[Dict[str, Any]] = None
        try:
            result = await core(*args, **kwargs)
            return result
        finally:
            if claimed:
                await _finish(pool, owner, rid, result)

    # Shielded: if the client disconnects mid-request the change still completes and its result is
    # stored, so a Retry with the same id replays it instead of creating a duplicate.
    work = asyncio.ensure_future(run_and_finish())
    try:
        return await asyncio.shield(work)
    finally:
        request_timezone.reset(token)


def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


def committed_event(result: Dict[str, Any]) -> str:
    """SSE event sent before the reply text so a dropped connection cannot hide a saved change."""
    summary = committed_summary(result)
    return _sse({"type": "committed", **summary}) if summary else ""


def replay_events(stored: Dict[str, Any], conv_id: str) -> list[str]:
    """SSE events that re-deliver a previously stored result without running anything again."""
    events = []
    committed = committed_event(stored)
    if committed:
        events.append(committed)
    events.append(_sse({"type": "token", "value": stored.get("response", "")}))
    data = stored.get("data") if isinstance(stored.get("data"), dict) else {}
    done: Dict[str, Any] = {
        "type": "done", "conversation_id": stored.get("conversation_id", conv_id),
        "skill_used": stored.get("skill_used"), "verifiable": False, "replayed": True,
    }
    if data:
        done["data"] = data
    if "can_undo" in data:
        done["can_undo"] = data["can_undo"]
    events.append(_sse(done))
    return events
