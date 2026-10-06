"""
Compass — Conversation & Message Storage Operations.

Provides database access for chat conversations and message history in PostgreSQL.
"""

from typing import Optional, Union, List, Dict, Any
import logging
import secrets
import uuid
import asyncpg
from asyncpg.pool import PoolConnectionProxy

import re

logger = logging.getLogger("compass.conversations")

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]

MODES_MARKER_REGEX = re.compile(r"\[\[\s*modes(?::[^\]]*)?\s*\]\]", re.IGNORECASE)


def strip_modes_marker(text: Optional[str]) -> str:
    """Strip [[modes]] control marker and all variants (e.g. [[modes: advice]], [[modes:plan]]) from text."""
    if not text:
        return ""
    return MODES_MARKER_REGEX.sub("", text).strip()



async def ensure_conversation_columns(conn: DbConn) -> None:
    """Ensure optional metadata columns exist on the conversations table."""
    try:
        await conn.execute(
            """
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title TEXT;
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id TEXT;
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS guest_id TEXT;
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE conversations ADD COLUMN IF NOT EXISTS share_token TEXT UNIQUE;
            ALTER TABLE conversations ALTER COLUMN share_token TYPE TEXT;
            """
        )
    except Exception:
        pass


async def get_or_create_conversation(
    conn: DbConn,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Validate or create a conversation record, returning its UUID as string.
    Ensures ownership is assigned to user_id or guest_id.
    """
    has_guest_col = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'conversations' AND column_name = 'guest_id'
        )
        """
    )

    if conversation_id:
        try:
            cid = uuid.UUID(conversation_id)
            row = await conn.fetchrow(
                "SELECT id FROM conversations WHERE id = $1",
                cid
            )
            if row:
                await conn.execute(
                    "UPDATE conversations SET last_active_at = now() WHERE id = $1",
                    cid
                )
                return str(row["id"])
            else:
                try:
                    if has_guest_col:
                        ins_row = await conn.fetchrow(
                            """
                            INSERT INTO conversations (id, title, user_id, guest_id)
                            VALUES ($1, $2, $3, $4)
                            RETURNING id
                            """,
                            cid, title, user_id, guest_id if not user_id else None
                        )
                    else:
                        ins_row = await conn.fetchrow(
                            """
                            INSERT INTO conversations (id, title, user_id)
                            VALUES ($1, $2, $3)
                            RETURNING id
                            """,
                            cid, title, user_id
                        )
                    if ins_row:
                        return str(ins_row["id"])
                except Exception:
                    try:
                        ins_row = await conn.fetchrow(
                            "INSERT INTO conversations (id) VALUES ($1) RETURNING id",
                            cid
                        )
                        if ins_row:
                            return str(ins_row["id"])
                    except Exception:
                        pass
        except (ValueError, TypeError):
            pass

    # Create new conversation
    try:
        if has_guest_col:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (title, user_id, guest_id)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                title, user_id, guest_id if not user_id else None
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (title, user_id)
                VALUES ($1, $2)
                RETURNING id
                """,
                title, user_id
            )
    except Exception:
        # Fallback if title/user_id columns don't exist yet
        row = await conn.fetchrow(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        )

    if row is not None:
        return str(row["id"])
    return str(uuid.uuid4())



async def add_message(
    conn: DbConn,
    conversation_id: str,
    role: str,
    content: str,
    skill_called: Optional[str] = None,
) -> dict:
    """Insert a message into the conversation history and update title if first user message."""
    cid = uuid.UUID(conversation_id)
    # Strip [[modes]] control marker and all variants before persisting
    clean_content = strip_modes_marker(content)
    row = await conn.fetchrow(
        """
        INSERT INTO messages (conversation_id, role, content, skill_called)
        VALUES ($1, $2, $3, $4)
        RETURNING id, conversation_id, role, content, skill_called, created_at
        """,
        cid, role, clean_content, skill_called
    )
    await conn.execute(
        "UPDATE conversations SET last_active_at = now() WHERE id = $1",
        cid
    )

    # Set conversation title if it's the first user message
    if role == "user":
        try:
            clean_title = strip_modes_marker(content).strip().replace("\n", " ")
            if len(clean_title) > 60:
                clean_title = clean_title[:57] + "..."
            await conn.execute(
                """
                UPDATE conversations
                SET title = COALESCE(title, $2)
                WHERE id = $1 AND (title IS NULL OR title = '' OR title = 'New Chat')
                """,
                cid, clean_title
            )
        except Exception:
            pass

    return dict(row) if row else {}


async def get_recent_messages(
    conn: DbConn,
    conversation_id: str,
    limit: int = 50,
) -> list[dict]:
    """Retrieve message history for a conversation, ordered chronologically."""
    try:
        cid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        return []

    rows = await conn.fetch(
        """
        SELECT id, role, content, skill_called, created_at
        FROM (
            SELECT id, role, content, skill_called, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC, id DESC
            LIMIT $2
        ) sub
        ORDER BY created_at ASC, id ASC
        """,
        cid, limit
    )
    return [
        {
            **dict(r),
            "content": strip_modes_marker(r["content"]),
        }
        for r in rows
    ]


async def list_conversations(
    conn: DbConn,
    limit: int = 30,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    include_archived: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve list of previous conversations with metadata, pinned state, and last message preview.
    Strictly isolates authenticated user chats from anonymous guest chats.
    """
    try:
        await ensure_conversation_columns(conn)
        query = """
            SELECT c.id, c.started_at, c.last_active_at,
                   c.title AS title,
                   COALESCE(c.is_pinned, FALSE) AS is_pinned,
                   COALESCE(c.is_archived, FALSE) AS is_archived,
                   COUNT(m.id) AS message_count,
                   (
                       SELECT content FROM messages
                       WHERE conversation_id = c.id AND role = 'user'
                       ORDER BY created_at ASC, id ASC LIMIT 1
                   ) AS first_user_msg,
                   (
                       SELECT content FROM messages
                       WHERE conversation_id = c.id
                       ORDER BY created_at DESC, id DESC LIMIT 1
                   ) AS last_msg
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE (
                ($1::text IS NOT NULL AND c.user_id = $1)
                OR ($2::text IS NOT NULL AND c.guest_id = $2 AND c.user_id IS NULL)
                OR ($1::text IS NULL AND $2::text IS NULL AND c.user_id IS NULL AND (c.guest_id IS NULL OR c.guest_id = ''))
            )
            AND ($3::boolean = TRUE OR c.is_archived = FALSE OR c.is_archived IS NULL)
            GROUP BY c.id, c.started_at, c.last_active_at, c.title, c.is_pinned, c.is_archived
            ORDER BY COALESCE(c.is_pinned, FALSE) DESC, c.last_active_at DESC
            LIMIT $4
        """
        rows = await conn.fetch(query, user_id, guest_id, include_archived, limit)
        conversations_list = []
        for r in rows:
            title = r.get("title") or r.get("first_user_msg") or "Chat Session"
            if len(title) > 60:
                title = title[:57] + "..."
            conversations_list.append({
                "id": str(r["id"]),
                "title": title,
                "is_pinned": bool(r.get("is_pinned", False)),
                "is_archived": bool(r.get("is_archived", False)),
                "started_at": r["started_at"].isoformat() if hasattr(r["started_at"], "isoformat") else str(r["started_at"]),
                "last_active_at": r["last_active_at"].isoformat() if hasattr(r["last_active_at"], "isoformat") else str(r["last_active_at"]),
                "message_count": int(r["message_count"] or 0),
                "preview": (r.get("last_msg") or "")[:120],
            })
        return conversations_list
    except Exception as e:
        return []


async def update_conversation(
    conn: DbConn,
    conversation_id: str,
    title: Optional[str] = None,
    is_pinned: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    is_shared: Optional[bool] = None,
) -> tuple[bool, Optional[str]]:
    """Update title, pinned status, archive status, or shared status of a conversation.
    When is_shared is enabled, generates a cryptographically unguessable token (secrets.token_urlsafe(32)).
    When is_shared is disabled, revokes the token by setting share_token to NULL.
    """
    try:
        cid = uuid.UUID(conversation_id)

        if title is None and is_pinned is None and is_archived is None and is_shared is None:
            return True, None

        await ensure_conversation_columns(conn)
        cand_token = secrets.token_urlsafe(32) if is_shared is True else None

        query = """
            UPDATE conversations
            SET title = CASE WHEN $2::boolean THEN $3::text ELSE title END,
                is_pinned = CASE WHEN $4::boolean THEN $5::boolean ELSE is_pinned END,
                is_archived = CASE WHEN $6::boolean THEN $7::boolean ELSE is_archived END,
                is_shared = CASE WHEN $8::boolean THEN $9::boolean ELSE is_shared END,
                share_token = CASE
                    WHEN $8::boolean AND $9::boolean THEN COALESCE(share_token, $10::text)
                    WHEN $8::boolean AND NOT $9::boolean THEN NULL
                    ELSE share_token
                END
            WHERE id = $1
            RETURNING share_token
        """
        row = await conn.fetchrow(
            query,
            cid,
            title is not None,
            title.strip()[:100] if title is not None else "",
            is_pinned is not None,
            bool(is_pinned) if is_pinned is not None else False,
            is_archived is not None,
            bool(is_archived) if is_archived is not None else False,
            is_shared is not None,
            bool(is_shared) if is_shared is not None else False,
            cand_token,
        )
        st = str(row["share_token"]) if row and row.get("share_token") else None
        return True, st
    except Exception as e:
        logger.error(f"update_conversation failed: {e}", exc_info=True)
        return False, None


async def delete_conversation(
    conn: DbConn,
    conversation_id: str,
) -> bool:
    """Delete a conversation and all its messages."""
    try:
        cid = uuid.UUID(conversation_id)
        await conn.execute("DELETE FROM messages WHERE conversation_id = $1", cid)
        await conn.execute("DELETE FROM conversations WHERE id = $1", cid)
        return True
    except Exception:
        return False


async def get_cross_conversation_memory(
    conn: DbConn,
    exclude_conversation_id: Optional[str] = None,
    limit: int = 6,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve messages and decisions from prior conversations for cross-session recall."""
    try:
        cid = None
        if exclude_conversation_id:
            try:
                cid = uuid.UUID(exclude_conversation_id)
            except (ValueError, TypeError):
                cid = None

        query = """
            SELECT m.role, m.content, m.created_at, c.id AS conversation_id
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE ($1::uuid IS NULL OR c.id != $1)
              AND (
                  ($2::text IS NOT NULL AND c.user_id = $2)
                  OR ($3::text IS NOT NULL AND c.guest_id = $3 AND c.user_id IS NULL)
                  OR ($2::text IS NULL AND $3::text IS NULL)
              )
            ORDER BY m.created_at DESC
            LIMIT $4
        """
        rows = await conn.fetch(query, cid, user_id, guest_id, limit)
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Access Control & Ownership Verification
# ---------------------------------------------------------------------------
async def check_conversation_access(
    conn: DbConn,
    conversation_id: str,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    is_admin: bool = False,
    allow_shared: bool = False,
) -> tuple[bool, Optional[str]]:
    """Verify caller has permission to view/modify a conversation.
    Returns (has_access, error_detail).
    """
    try:
        cid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        return False, "Invalid conversation ID"

    try:
        conv_row = await conn.fetchrow(
            """
            SELECT id, user_id, guest_id, is_shared
            FROM conversations
            WHERE id = $1
            """,
            cid,
        )
    except Exception:
        conv_row = await conn.fetchrow(
            "SELECT id FROM conversations WHERE id = $1",
            cid,
        )
    if not conv_row:
        return False, "Conversation not found"

    if is_admin:
        return True, None

    conv_owner = conv_row.get("user_id")
    conv_guest = conv_row.get("guest_id")

    if conv_owner:
        if not user_id or user_id.lower() != conv_owner.lower():
            return False, "Forbidden: You do not have permission to access this conversation."
    elif conv_guest:
        if not guest_id or guest_id != conv_guest:
            return False, "Forbidden: You do not have permission to access this conversation."

    return True, None


# ---------------------------------------------------------------------------
# Guest Migration & Preservation Operations (Delegated to conversation_migration)
# ---------------------------------------------------------------------------
from backend.memory.conversation_migration import (
    get_guest_migration_overview,
    list_guest_conversations_for_migration,
    migrate_single_conversation,
    migrate_all_guest_conversations,
    migrate_guest_memories,
    delete_guest_data,
)




