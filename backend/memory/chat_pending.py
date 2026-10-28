"""
Compass — Chat Pending Actions and Soft Delete Store.

Provides robust, single-use confirmation state for destructive task operations
(delete_task, complete_task, clear_schedule) and 10-minute undo recovery.
Task IDs are strictly computed server-side from active database records,
never derived from untrusted model hallucinations.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import json
import logging

logger = logging.getLogger("compass.memory.chat_pending")


async def create_chat_pending_action(
    conn: Any,
    action: str,
    task_ids: List[int],
    task_titles: List[Dict[str, Any]],
    count: int,
    owner_identity: str,
    conversation_id: str,
    expires_minutes: int = 5,
) -> Dict[str, Any]:
    """Create a new pending action for user confirmation.
    
    Any existing pending action for the same user and conversation is superseded/cancelled.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=min(expires_minutes, 5))
    
    # Cancel any older pending action for this user & conversation
    await conn.execute(
        """
        UPDATE chat_pending_actions
        SET status = 'cancelled'
        WHERE owner_identity = $1 AND conversation_id = $2 AND status = 'pending'
        """,
        owner_identity,
        conversation_id,
    )

    row = await conn.fetchrow(
        """
        INSERT INTO chat_pending_actions (
            action, task_ids, task_titles, count, owner_identity, conversation_id,
            status, created_at, expires_at
        )
        VALUES ($1, $2, $3::jsonb, $4, $5, $6, 'pending', now(), $7)
        RETURNING id, action, task_ids, task_titles, count, owner_identity, conversation_id, status, created_at, expires_at
        """,
        action,
        task_ids,
        json.dumps(task_titles),
        count,
        owner_identity,
        conversation_id,
        expires_at,
    )
    return dict(row) if row else {}


async def get_active_chat_pending_action(
    conn: Any,
    owner_identity: str,
    conversation_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve the active, non-expired pending action for this user and conversation."""
    row = await conn.fetchrow(
        """
        SELECT id, action, task_ids, task_titles, count, owner_identity, conversation_id,
               status, created_at, expires_at
        FROM chat_pending_actions
        WHERE owner_identity = $1
          AND conversation_id = $2
          AND status = 'pending'
          AND expires_at > now()
        ORDER BY created_at DESC
        LIMIT 1
        """,
        owner_identity,
        conversation_id,
    )
    if not row:
        return None
    d = dict(row)
    if isinstance(d.get("task_titles"), str):
        try:
            d["task_titles"] = json.loads(d["task_titles"])
        except Exception:
            d["task_titles"] = []
    return d


async def resolve_chat_pending_action(
    conn: Any,
    action_id: int,
    new_status: str,
) -> bool:
    """Transition pending action to confirmed, cancelled, executed, or expired (single-use)."""
    res = await conn.execute(
        """
        UPDATE chat_pending_actions
        SET status = $1, executed_at = CASE WHEN $1 = 'executed' THEN now() ELSE executed_at END
        WHERE id = $2 AND status = 'pending'
        """,
        new_status,
        action_id,
    )
    return "UPDATE 1" in res


async def soft_delete_tasks(
    conn: Any,
    task_ids: List[int],
    owner_identity: str,
) -> List[Dict[str, Any]]:
    """Soft-delete tasks belonging to owner_identity by setting deleted_at = now().
    
    Returns the list of deleted tasks for confirmation and audit logging.
    """
    if not task_ids:
        return []

    rows = await conn.fetch(
        """
        UPDATE tasks
        SET deleted_at = now(), updated_at = now()
        WHERE id = ANY($1::int[])
          AND (user_id = $2 OR (user_id IS NULL AND $2 IS NULL))
          AND deleted_at IS NULL
        RETURNING id, title, domain, due_date, status, priority, user_id, deleted_at
        """,
        task_ids,
        owner_identity,
    )
    
    deleted_tasks = [dict(r) for r in rows]
    # Log to agent audit log
    for t in deleted_tasks:
        try:
            # Savepoint: a failed audit insert must not abort the caller's transaction.
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO agent_audit_log (
                        run_id, tool, affected_id, action, previous_state, new_state, user_id, timestamp
                    )
                    VALUES ($1, 'delete_task', $2, 'soft_delete', $3::jsonb, $4::jsonb, $5, now())
                    """,
                    f"chat-delete-{t['id']}",
                    t["id"],
                    json.dumps({"status": t.get("status"), "deleted_at": None}),
                    json.dumps({"status": t.get("status"), "deleted_at": t["deleted_at"].isoformat() if t.get("deleted_at") else None}),
                    owner_identity,
                )
        except Exception as e:
            logger.debug("Failed to record agent_audit_log for task %s: %s", t["id"], e)
            
    return deleted_tasks


async def undo_soft_deleted_tasks(
    conn: Any,
    owner_identity: str,
    minutes: int = 10,
) -> List[Dict[str, Any]]:
    """Restore tasks for owner_identity deleted within the undo window (10 minutes).
    
    Idempotent: double-undo mutates 0 rows on the second pass.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    
    rows = await conn.fetch(
        """
        UPDATE tasks
        SET deleted_at = NULL, updated_at = now()
        WHERE (user_id = $1 OR (user_id IS NULL AND $1 IS NULL))
          AND deleted_at IS NOT NULL
          AND deleted_at >= $2
        RETURNING id, title, domain, due_date, status, priority, user_id
        """,
        owner_identity,
        cutoff,
    )
    
    restored = [dict(r) for r in rows]
    for t in restored:
        try:
            await conn.execute(
                """
                INSERT INTO agent_audit_log (
                    run_id, tool, affected_id, action, previous_state, new_state, user_id, timestamp
                )
                VALUES ($1, 'undo_delete', $2, 'restore', $3::jsonb, $4::jsonb, $5, now())
                """,
                f"chat-undo-{t['id']}",
                t["id"],
                json.dumps({"deleted_at": "soft_deleted"}),
                json.dumps({"deleted_at": None}),
                owner_identity,
            )
        except Exception as e:
            logger.debug("Failed to record agent_audit_log for restored task %s: %s", t["id"], e)
            
    return restored


async def search_active_tasks_for_delete(
    conn: Any,
    owner_identity: str,
    query: str,
) -> List[Dict[str, Any]]:
    """Search for non-deleted tasks matching the user's delete query.
    
    Supports numeric ID, exact title match, and substring search on the
    already-normalised target (see backend/services/delete_target.py).
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    # If query is a purely numeric ID (e.g. "42")
    if clean_q.isdigit():
        task_id = int(clean_q)
        row = await conn.fetchrow(
            """
            SELECT id, title, domain, due_date, status, priority, user_id
            FROM tasks
            WHERE id = $1
              AND (user_id = $2 OR (user_id IS NULL AND $2 IS NULL))
              AND deleted_at IS NULL
            """,
            task_id,
            owner_identity,
        )
        return [dict(row)] if row else []

    # Case-insensitive title match: exact title or title containing the text.
    # LIKE wildcards in the user text are escaped with '!' so they match literally.
    like_q = clean_q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    rows = await conn.fetch(
        """
        SELECT id, title, domain, due_date, status, priority, user_id
        FROM tasks
        WHERE (user_id = $1 OR (user_id IS NULL AND $1 IS NULL))
          AND deleted_at IS NULL
          AND (
            LOWER(title) = LOWER($2)
            OR LOWER(title) LIKE '%' || LOWER($3) || '%' ESCAPE '!'
          )
        ORDER BY
          CASE WHEN LOWER(title) = LOWER($2) THEN 0 ELSE 1 END,
          LENGTH(title) ASC
        LIMIT 10
        """,
        owner_identity,
        clean_q,
        like_q,
    )
    return [dict(r) for r in rows]


async def list_nearest_active_titles(
    conn: Any,
    owner_identity: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Up to ``limit`` active tasks of this owner, soonest due first (for "no match" replies)."""
    rows = await conn.fetch(
        """
        SELECT id, title, domain, due_date, status, priority, user_id
        FROM tasks
        WHERE (user_id = $1 OR (user_id IS NULL AND $1 IS NULL))
          AND deleted_at IS NULL
        ORDER BY due_date ASC NULLS LAST, id ASC
        LIMIT $2
        """,
        owner_identity,
        limit,
    )
    return [dict(r) for r in rows]


async def get_all_active_tasks_for_user(
    conn: Any,
    owner_identity: str,
) -> List[Dict[str, Any]]:
    """Get all non-deleted active tasks for clear_schedule confirmation."""
    rows = await conn.fetch(
        """
        SELECT id, title, domain, due_date, status, priority, user_id
        FROM tasks
        WHERE (user_id = $1 OR (user_id IS NULL AND $1 IS NULL))
          AND deleted_at IS NULL
        ORDER BY due_date ASC NULLS LAST, id ASC
        """,
        owner_identity,
    )
    return [dict(r) for r in rows]
