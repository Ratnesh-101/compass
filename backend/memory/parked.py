"""
Compass — Parked Thoughts Memory ("Park it" shelf).

Stores and manages deferred thoughts, tangents, and ideas
per user/conversation so the thinking partner can gracefully
resume them later.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import asyncpg

logger = logging.getLogger("compass.memory.parked")

MAX_PARKED_TEXT_LENGTH = 200


def sanitize_parked_text(text: str) -> str:
    """Sanitize and length-cap parked thought text to prevent prompt injection."""
    if not text:
        return ""
    # Collapse newlines and carriage returns to single spaces
    collapsed = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    # Cap length at 200 characters
    return collapsed[:MAX_PARKED_TEXT_LENGTH].strip()


async def park_thought(
    conn: asyncpg.Connection,
    text: str,
    user_id: str = "default_user",
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Park a thought or tangent for later discussion.

    Returns the inserted thought record dict.
    """
    clean_text = sanitize_parked_text(text)
    if not clean_text:
        return {
            "id": 0,
            "text": "",
            "status": "parked",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO parked_thoughts (user_id, conversation_id, text, status)
            VALUES ($1, $2, $3, 'parked')
            RETURNING id, user_id, conversation_id, text, status, created_at
            """,
            user_id,
            conversation_id,
            clean_text,
        )
        if row:
            return {
                "id": row["id"],
                "user_id": row["user_id"],
                "conversation_id": row["conversation_id"],
                "text": row["text"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            }
    except Exception as e:
        logger.warning("Failed to park thought (continuing gracefully): %s", e)

    return {
        "id": 0,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "text": clean_text,
        "status": "parked",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def list_parked_thoughts(
    conn: asyncpg.Connection,
    user_id: str = "default_user",
    status: str = "parked",
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """List parked thoughts for a user, ordered newest first."""
    try:
        rows = await conn.fetch(
            """
            SELECT id, user_id, conversation_id, text, status, created_at
            FROM parked_thoughts
            WHERE user_id = $1 AND status = $2
            ORDER BY created_at DESC
            LIMIT $3
            """,
            user_id,
            status,
            limit,
        )
        return [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "conversation_id": r["conversation_id"],
                "text": r["text"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to query parked thoughts (continuing gracefully): %s", e)
        return []


async def resolve_parked_thought(
    conn: asyncpg.Connection,
    thought_id: int,
    user_id: str = "default_user",
) -> bool:
    """Mark a parked thought as done."""
    try:
        res = await conn.execute(
            """
            UPDATE parked_thoughts
            SET status = 'done'
            WHERE id = $1 AND user_id = $2
            """,
            thought_id,
            user_id,
        )
        return "UPDATE 1" in res
    except Exception as e:
        logger.warning("Failed to resolve parked thought (continuing gracefully): %s", e)
        return False


async def migrate_guest_parked_thoughts(
    conn: asyncpg.Connection,
    guest_id: str,
    user_id: str,
) -> int:
    """Migrate guest parked thoughts to registered user account (non-destructive clone, idempotent, concurrent-safe)."""
    try:
        # 1. Fetch guest thoughts that have not yet been migrated for this user
        thoughts = await conn.fetch(
            """
            SELECT pt.id, pt.conversation_id, pt.text, pt.status, pt.created_at
            FROM parked_thoughts pt
            WHERE pt.user_id = $1
              AND NOT EXISTS (
                  SELECT 1 FROM guest_migration_log gml
                  WHERE gml.guest_id = $1 AND gml.user_id = $2
                    AND gml.entity_type = 'parked_thought'
                    AND gml.entity_key = pt.id::text
              )
            ORDER BY pt.id ASC
            """,
            guest_id,
            user_id,
        )
        if not thoughts:
            return 0

        migrated_count = 0
        for t in thoughts:
            # 2. Try recording in guest_migration_log first with ON CONFLICT DO NOTHING
            # Only if the log entry was successfully claimed by this execution, clone the parked thought!
            res = await conn.execute(
                """
                INSERT INTO guest_migration_log (guest_id, user_id, entity_type, entity_key, detail)
                VALUES ($1, $2, 'parked_thought', $3, json_build_object('text', $4::text, 'status', $5::text))
                ON CONFLICT (guest_id, user_id, entity_type, entity_key) WHERE entity_key IS NOT NULL DO NOTHING
                """,
                guest_id,
                user_id,
                str(t["id"]),
                str(t["text"]),
                str(t["status"]),
            )

            if "INSERT 0 1" in res:
                # 3. We won the concurrency race for this thought: insert cloned row for user account
                await conn.execute(
                    """
                    INSERT INTO parked_thoughts (user_id, conversation_id, text, status, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    user_id,
                    t["conversation_id"],
                    t["text"],
                    t["status"],
                    t["created_at"],
                )
                migrated_count += 1

        return migrated_count
    except Exception as e:
        logger.warning("Could not migrate parked thoughts from %s to %s: %s", guest_id, user_id, e)
        return 0


async def delete_guest_parked_thoughts(
    conn: asyncpg.Connection,
    guest_id: str,
) -> int:
    """Delete all parked thoughts belonging to a guest."""
    try:
        res = await conn.execute(
            """
            DELETE FROM parked_thoughts
            WHERE user_id = $1
            """,
            guest_id,
        )
        parts = res.split()
        return int(parts[1]) if len(parts) == 2 else 0
    except Exception as e:
        logger.warning("Could not delete parked thoughts for guest %s: %s", guest_id, e)
        return 0

