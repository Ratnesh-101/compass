"""
Compass — Conversation & Message Storage Operations.

Provides database access for chat conversations and message history in PostgreSQL.
"""

from typing import Optional, Union, List, Dict, Any
import logging
import uuid
import asyncpg
from asyncpg.pool import PoolConnectionProxy

logger = logging.getLogger("compass.conversations")

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]


async def get_or_create_conversation(
    conn: DbConn,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Validate or create a conversation record, returning its UUID as string."""
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
    row = await conn.fetchrow(
        """
        INSERT INTO messages (conversation_id, role, content, skill_called)
        VALUES ($1, $2, $3, $4)
        RETURNING id, conversation_id, role, content, skill_called, created_at
        """,
        cid, role, content, skill_called
    )
    await conn.execute(
        "UPDATE conversations SET last_active_at = now() WHERE id = $1",
        cid
    )

    # Set conversation title if it's the first user message
    if role == "user":
        try:
            clean_title = content.strip().replace("\n", " ")
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
        FROM messages
        WHERE conversation_id = $1
        ORDER BY created_at ASC, id ASC
        LIMIT $2
        """,
        cid, limit
    )
    return [dict(r) for r in rows]


async def list_conversations(
    conn: DbConn,
    limit: int = 30,
    user_id: Optional[str] = None,
    include_archived: bool = False,
) -> List[Dict[str, Any]]:
    """Retrieve list of previous conversations with metadata, pinned state, and last message preview."""
    try:
        # Check column existence safely
        has_title_col = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'conversations' AND column_name = 'title'
            )
            """
        )
        has_user_col = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'conversations' AND column_name = 'user_id'
            )
            """
        )
        has_pinned_col = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'conversations' AND column_name = 'is_pinned'
            )
            """
        )
        has_archived_col = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'conversations' AND column_name = 'is_archived'
            )
            """
        )

        title_expr = "c.title" if has_title_col else "NULL"
        pinned_expr = "c.is_pinned" if has_pinned_col else "FALSE"
        archived_expr = "c.is_archived" if has_archived_col else "FALSE"

        query = f"""
            SELECT c.id, c.started_at, c.last_active_at,
                   {title_expr} AS title,
                   {pinned_expr} AS is_pinned,
                   {archived_expr} AS is_archived,
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
        """

        where_clauses = []
        params: List[Any] = []

        if user_id and has_user_col:
            params.append(user_id)
            where_clauses.append(f"(c.user_id = ${len(params)} OR c.user_id IS NULL)")

        if not include_archived and has_archived_col:
            where_clauses.append("(c.is_archived = FALSE OR c.is_archived IS NULL)")

        if where_clauses:
            query += f" WHERE {' AND '.join(where_clauses)} "

        group_cols = ["c.id", "c.started_at", "c.last_active_at"]
        if has_title_col:
            group_cols.append("c.title")
        if has_pinned_col:
            group_cols.append("c.is_pinned")
        if has_archived_col:
            group_cols.append("c.is_archived")

        order_by = "ORDER BY c.is_pinned DESC, c.last_active_at DESC" if has_pinned_col else "ORDER BY c.last_active_at DESC"

        query += f"""
            GROUP BY {', '.join(group_cols)}
            {order_by}
            LIMIT ${len(params) + 1}
        """
        params.append(limit)

        rows = await conn.fetch(query, *params)
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
) -> bool:
    """Update title, pinned status, or archive status of a conversation."""
    try:
        cid = uuid.UUID(conversation_id)
        updates: List[str] = []
        params: List[Any] = [cid]

        if title is not None:
            clean_title = title.strip()[:100]
            params.append(clean_title)
            updates.append(f"title = ${len(params)}")

        if is_pinned is not None:
            has_pinned = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'is_pinned')"
            )
            if not has_pinned:
                await conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE")
            params.append(bool(is_pinned))
            updates.append(f"is_pinned = ${len(params)}")

        if is_archived is not None:
            has_archived = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'is_archived')"
            )
            if not has_archived:
                await conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE")
            params.append(bool(is_archived))
            updates.append(f"is_archived = ${len(params)}")

        if not updates:
            return True

        query = f"UPDATE conversations SET {', '.join(updates)} WHERE id = $1"
        await conn.execute(query, *params)
        return True
    except Exception as e:
        logger.error(f"update_conversation failed: {e}", exc_info=True)
        return False


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
) -> List[Dict[str, Any]]:
    """Retrieve messages and decisions from prior conversations for cross-session recall."""
    try:
        where_clauses = []
        params: List[Any] = []
        if exclude_conversation_id:
            try:
                cid = uuid.UUID(exclude_conversation_id)
                where_clauses.append(f"c.id != ${len(params) + 1}")
                params.append(cid)
            except (ValueError, TypeError):
                pass

        if user_id:
            where_clauses.append(f"(c.user_id IS NULL OR c.user_id = ${len(params) + 1})")
            params.append(user_id)

        query = """
            SELECT m.role, m.content, m.created_at, c.id AS conversation_id
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
        """
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += f" ORDER BY m.created_at DESC LIMIT ${len(params) + 1}"
        params.append(limit)

        rows = await conn.fetch(query, *params)
        return [dict(r) for r in reversed(rows)]
    except Exception:
        return []

