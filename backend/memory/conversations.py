"""
Compass — Conversation & Message Storage Operations.

Provides database access for chat conversations and message history in PostgreSQL.
"""

from typing import Optional, Union, List, Dict, Any
import logging
import secrets
import hashlib
import uuid
import asyncpg
from asyncpg.pool import PoolConnectionProxy

import re

logger = logging.getLogger("compass.conversations")

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]

MODES_MARKER_REGEX = re.compile(r"\[{1,2}\s*modes?(?::[^\r\n\]]*|\s*)\]{1,2}", re.IGNORECASE)


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
    evidence: Optional[Union[Dict[str, Any], List[Any], str]] = None,
    verifiable: Optional[bool] = None,
) -> dict:
    """Insert a message into the conversation history and update title if first user message."""
    import json
    cid = uuid.UUID(conversation_id)
    # Strip [[modes]] control marker and all variants before persisting
    clean_content = strip_modes_marker(content)
    evidence_json = json.dumps(evidence) if isinstance(evidence, (dict, list)) else (evidence if isinstance(evidence, str) else None)

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO messages (conversation_id, role, content, skill_called, evidence, verifiable)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            RETURNING id, conversation_id, role, content, skill_called, evidence, verifiable, created_at
            """,
            cid, role, clean_content, skill_called, evidence_json, verifiable
        )
    except Exception:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO messages (conversation_id, role, content, skill_called, evidence)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id, conversation_id, role, content, skill_called, evidence, created_at
                """,
                cid, role, clean_content, skill_called, evidence_json
            )
        except Exception:
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

    res = dict(row) if row else {}
    if "evidence" in res and isinstance(res["evidence"], str):
        try:
            res["evidence"] = json.loads(res["evidence"])
        except Exception:
            pass
    return res


async def get_recent_messages(
    conn: DbConn,
    conversation_id: str,
    limit: int = 50,
) -> list[dict]:
    """Retrieve message history for a conversation, ordered chronologically."""
    import json
    try:
        cid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        return []

    try:
        rows = await conn.fetch(
            """
            SELECT id, role, content, skill_called, evidence, verifiable, created_at
            FROM (
                SELECT id, role, content, skill_called, evidence, verifiable, created_at
                FROM messages
                WHERE conversation_id = $1
                ORDER BY created_at DESC, id DESC
                LIMIT $2
            ) sub
            ORDER BY created_at ASC, id ASC
            """,
            cid, limit
        )
    except Exception:
        try:
            rows = await conn.fetch(
                """
                SELECT id, role, content, skill_called, evidence, created_at
                FROM (
                    SELECT id, role, content, skill_called, evidence, created_at
                    FROM messages
                    WHERE conversation_id = $1
                    ORDER BY created_at DESC, id DESC
                    LIMIT $2
                ) sub
                ORDER BY created_at ASC, id ASC
                """,
                cid, limit
            )
        except Exception:
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

    result = []
    for r in rows:
        item = dict(r)
        item["content"] = strip_modes_marker(r["content"])
        if "evidence" in item and isinstance(item["evidence"], str):
            try:
                item["evidence"] = json.loads(item["evidence"])
            except Exception:
                pass
        result.append(item)
    return result


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
                   COALESCE(c.is_shared, FALSE) AS is_shared,
                   c.share_token,
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
            GROUP BY c.id, c.started_at, c.last_active_at, c.title, c.is_pinned, c.is_archived, c.is_shared, c.share_token
            ORDER BY COALESCE(c.is_pinned, FALSE) DESC, c.last_active_at DESC
            LIMIT $4
        """
        rows = await conn.fetch(query, user_id, guest_id, include_archived, limit)
        conversations_list = []
        for r in rows:
            title = r.get("title") or r.get("first_user_msg") or "Chat Session"
            if len(title) > 60:
                title = title[:57] + "..."
            stored_st = str(r["share_token"]) if r.get("share_token") else None
            is_hex_hash = bool(stored_st and len(stored_st) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored_st))
            conversations_list.append({
                "id": str(r["id"]),
                "title": title,
                "is_pinned": bool(r.get("is_pinned", False)),
                "is_archived": bool(r.get("is_archived", False)),
                "is_shared": bool(r.get("is_shared", False)),
                "share_token": stored_st if (stored_st and not is_hex_hash) else None,
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
        raw_token = secrets.token_urlsafe(32) if is_shared is True else None
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest() if raw_token else None

        query = """
            UPDATE conversations
            SET title = CASE WHEN $2::boolean THEN $3::text ELSE title END,
                is_pinned = CASE WHEN $4::boolean THEN $5::boolean ELSE is_pinned END,
                is_archived = CASE WHEN $6::boolean THEN $7::boolean ELSE is_archived END,
                is_shared = CASE WHEN $8::boolean THEN $9::boolean ELSE is_shared END,
                share_token = CASE
                    WHEN $8::boolean AND $9::boolean THEN $10::text
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
            token_hash,
        )
        returned_token = raw_token if (is_shared is True and raw_token) else None
        return True, returned_token
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
    if not user_id and not guest_id:
        return []
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
# Public Sharing Operations
# ---------------------------------------------------------------------------
async def get_shared_conversation_by_token(
    conn: DbConn,
    share_token: str,
    limit: int = 100,
) -> Optional[Dict[str, Any]]:
    """Retrieve a shared conversation and its message history by cryptographically secure share_token.
    Enforces that is_shared is TRUE. Returns None if not found, revoked, or unshared.
    Guarantees that knowing a conversation's database ID alone does not grant access.
    """
    if not share_token or not isinstance(share_token, str):
        return None

    clean_token = share_token.strip()
    if not clean_token:
        return None

    await ensure_conversation_columns(conn)
    token_hash = hashlib.sha256(clean_token.encode("utf-8")).hexdigest()

    conv_row = await conn.fetchrow(
        """
        SELECT id, started_at, last_active_at, COALESCE(title, 'Chat Session') AS title, is_shared, share_token
        FROM conversations
        WHERE is_shared = TRUE
          AND (
            share_token = $1
            OR (
              share_token = $2
              AND (LENGTH(share_token) != 64 OR share_token !~ '^[0-9a-fA-F]{64}$')
            )
          )
        """,
        token_hash,
        clean_token,
    )
    if not conv_row:
        return None

    # Transitional upgrade: If the matched row stored the legacy plaintext token,
    # automatically upgrade it to sha256 hash on first access.
    if conv_row.get("share_token") == clean_token and clean_token != token_hash:
        try:
            await conn.execute(
                """
                UPDATE conversations
                SET share_token = $1
                WHERE id = $2 AND share_token = $3
                """,
                token_hash,
                conv_row["id"],
                clean_token,
            )
        except Exception as e:
            logger.warning(f"Failed to upgrade legacy share token to sha256: {e}")

    cid_str = str(conv_row["id"])
    rows = await get_recent_messages(conn, cid_str, limit=limit)
    messages = [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "skill_called": r.get("skill_called"),
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
        }
        for r in rows
    ]

    return {
        "title": conv_row["title"],
        "started_at": conv_row["started_at"].isoformat() if hasattr(conv_row["started_at"], "isoformat") else str(conv_row["started_at"]),
        "last_active_at": conv_row["last_active_at"].isoformat() if hasattr(conv_row["last_active_at"], "isoformat") else str(conv_row["last_active_at"]),
        "messages": messages,
    }


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




