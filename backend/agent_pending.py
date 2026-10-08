"""
Compass — DB-Backed Pending Actions Engine.

Replaces in-memory confirmation tracking with a distributed, single-use,
tamper-proof pending_actions table in PostgreSQL.
Enforces:
  1. Strict ownership binding (cross-user confirmation rejected with 403).
  2. Cryptographic args hashing (tampered arguments rejected).
  3. Single-use atomic status transition (replay protection).
  4. Clean expiration handling across server restarts and multiple workers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from backend.memory.db import get_pool

if TYPE_CHECKING:
    from backend.dependencies import Identity

logger = logging.getLogger("compass.agent_pending")


def compute_args_hash(args: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of canonical arguments."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def register_pending_action(
    pool: Any,
    run_id: str,
    owner_identity: str,
    tool: str,
    args: Dict[str, Any],
    timeout_seconds: float = 300.0,
) -> str:
    """Register a mutating tool call in pending_actions table. Returns action_id."""
    if not pool:
        raise RuntimeError("Database pool unavailable; cannot register pending action.")

    action_id = f"act_{uuid.uuid4()}"
    args_hash = compute_args_hash(args)
    args_json = json.dumps(args, default=str)

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pending_actions 
                    (action_id, run_id, owner_identity, tool, args_hash, original_args, status, created_at, expires_at)
                VALUES 
                    ($1, $2, $3, $4, $5, $6::jsonb, 'pending', now(), now() + ($7 || ' seconds')::interval)
                """,
                action_id,
                run_id,
                owner_identity,
                tool,
                args_hash,
                args_json,
                str(int(timeout_seconds)),
            )
            logger.info("Registered pending action %s for run %s (tool=%s)", action_id, run_id, tool)
            return action_id
    except Exception as e:
        logger.error("Failed to register pending action %s: %s", action_id, e)
        raise RuntimeError(f"Database insertion failed for pending action: {e}") from e


async def verify_and_claim_action(
    pool: Any,
    action_id: Optional[str],
    run_id: Optional[str],
    caller_identity: str | Identity,
    confirmed_args: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Verify ownership, expiry, replay, and args integrity, claiming the action atomically.

    Returns:
        (is_success, status_or_error_message, original_args)
    """
    if not pool:
        return False, "Database connection unavailable", None

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Fetch current pending action row
                if action_id:
                    row = await conn.fetchrow(
                        "SELECT * FROM pending_actions WHERE action_id = $1 FOR UPDATE",
                        action_id,
                    )
                elif run_id:
                    row = await conn.fetchrow(
                        "SELECT * FROM pending_actions WHERE run_id = $1 AND status = 'pending' ORDER BY id DESC LIMIT 1 FOR UPDATE",
                        run_id,
                    )
                else:
                    return False, "Neither action_id nor run_id provided", None

                if not row:
                    # Check if action was already claimed or executed
                    if run_id:
                        prev = await conn.fetchrow(
                            "SELECT status FROM pending_actions WHERE run_id = $1 ORDER BY id DESC LIMIT 1",
                            run_id,
                        )
                        if prev and prev["status"] in ("claimed", "executed"):
                            return False, "Action has already been claimed or executed (replay rejected).", None
                    return False, "Pending action not found.", None

                target_action_id = row["action_id"]
                owner = row["owner_identity"]
                stored_status = row["status"]
                expires_at = row["expires_at"]
                stored_args_hash = row["args_hash"]
                orig_args = row["original_args"]
                if isinstance(orig_args, str):
                    orig_args = json.loads(orig_args)

                # 2. Strict ownership verification
                is_admin = getattr(caller_identity, "is_admin", False)
                caller_id_str = getattr(caller_identity, "id", None) or str(caller_identity or "")
                clean_caller = caller_id_str.strip().lower()
                clean_owner = (owner or "").strip().lower()
                if clean_caller != clean_owner and not is_admin:
                    logger.warning("Ownership mismatch: caller %s attempted to confirm action owned by %s", clean_caller, clean_owner)
                    return False, "Permission denied: Action belongs to another identity.", None

                # 3. Expiration check
                now_utc = datetime.now(timezone.utc)
                if expires_at and expires_at < now_utc:
                    await conn.execute(
                        "UPDATE pending_actions SET status = 'expired' WHERE action_id = $1",
                        target_action_id,
                    )
                    return False, "Action expired: confirmation window timed out.", None

                # 4. Replay check
                if stored_status in ("claimed", "executed"):
                    return False, "Action has already been claimed or executed (replay rejected).", None
                elif stored_status == "failed":
                    return False, "Action previously failed and cannot be re-executed.", None
                elif stored_status != "pending":
                    return False, f"Action is in '{stored_status}' status and cannot be executed.", None

                # 5. Args integrity validation
                if confirmed_args is not None:
                    check_hash = compute_args_hash(confirmed_args)
                    if check_hash != stored_args_hash:
                        logger.warning("Args tampering detected! Expected %s, got %s", stored_args_hash, check_hash)
                        return False, "Tampered action arguments rejected: confirmed args do not match proposed action.", None

                # 6. Single-use atomic update: pending -> claimed
                updated = await conn.fetchval(
                    """
                    UPDATE pending_actions 
                    SET status = 'claimed' 
                    WHERE action_id = $1 AND status = 'pending'
                    RETURNING action_id
                    """,
                    target_action_id,
                )
                if not updated:
                    return False, "Action was claimed concurrently by another worker.", None

                logger.info("Pending action %s claimed successfully for execution.", target_action_id)
                return True, "ok", orig_args

    except Exception as e:
        logger.exception("Error verifying pending action: %s", e)
        return False, f"Internal error during action verification: {e}", None


async def mark_action_executed(pool: Any, action_id: str) -> bool:
    """Transition a claimed action to executed upon successful completion."""
    if not pool:
        return False
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE pending_actions SET status = 'executed' WHERE action_id = $1 AND status = 'claimed'",
            action_id,
        )
        return "UPDATE 1" in str(res)


async def mark_action_failed(pool: Any, action_id: str, error_message: Optional[str] = None) -> bool:
    """Transition a claimed action to failed so failures aren't dead rows."""
    if not pool:
        return False
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE pending_actions SET status = 'failed' WHERE action_id = $1 AND status = 'claimed'",
            action_id,
        )
        return "UPDATE 1" in str(res)


async def reject_pending_action(
    pool: Any,
    action_id: Optional[str],
    run_id: Optional[str],
    caller_identity: str,
    feedback: str = "",
) -> Tuple[bool, str]:
    """Mark a pending action as rejected by the user."""
    if not pool:
        return False, "Database unavailable"

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                if action_id:
                    row = await conn.fetchrow("SELECT * FROM pending_actions WHERE action_id = $1 FOR UPDATE", action_id)
                elif run_id:
                    row = await conn.fetchrow("SELECT * FROM pending_actions WHERE run_id = $1 AND status = 'pending' LIMIT 1 FOR UPDATE", run_id)
                else:
                    return False, "No identifier provided"

                if not row:
                    return False, "Pending action not found"

                clean_caller = (caller_identity or "").strip().lower()
                clean_owner = (row["owner_identity"] or "").strip().lower()
                if clean_caller != clean_owner and clean_caller != "admin":
                    return False, "Permission denied"

                await conn.execute("UPDATE pending_actions SET status = 'rejected' WHERE action_id = $1", row["action_id"])
                return True, "Action rejected"
    except Exception as e:
        return False, str(e)


async def wait_for_pending_action(
    pool: Any,
    run_id: str,
    evt: Optional[Any],
    outcome: Dict[str, Any],
    timeout_seconds: float = 300.0,
) -> Tuple[str, str]:
    """Wait for confirmation outcome via in-memory event or DB pending_actions polling.

    Supports multi-worker setups and recovers gracefully across restarts and worker handoffs.
    """
    import asyncio
    import time
    start = time.monotonic()

    while (time.monotonic() - start) < timeout_seconds:
        if evt and evt.is_set():
            return outcome.get("action", "reject"), outcome.get("feedback", "")

        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT status FROM pending_actions WHERE run_id = $1 AND status != 'pending' ORDER BY created_at DESC LIMIT 1",
                        run_id,
                    )
                    if row:
                        status = row["status"]
                        action = "approve" if status == "executed" else "reject"
                        return action, ""
            except Exception as e:
                logger.debug("Polling pending_actions encountered error: %s", e)

        await asyncio.sleep(0.5)

    raise asyncio.TimeoutError()
