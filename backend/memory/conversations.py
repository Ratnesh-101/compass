"""
Compass — Conversation & Message Storage Operations.

Provides database access for chat conversations and message history in PostgreSQL.
"""

from typing import Optional
import uuid
import asyncpg


async def get_or_create_conversation(
    conn: asyncpg.Connection,
    conversation_id: Optional[str] = None,
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
        except (ValueError, TypeError):
            pass

    # Create new conversation
    row = await conn.fetchrow(
        "INSERT INTO conversations DEFAULT VALUES RETURNING id"
    )
    if row is not None:
        return str(row["id"])
    return str(uuid.uuid4())


async def add_message(
    conn: asyncpg.Connection,
    conversation_id: str,
    role: str,
    content: str,
    skill_called: Optional[str] = None,
) -> dict:
    """Insert a message into the conversation history."""
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
    return dict(row) if row else {}


async def get_recent_messages(
    conn: asyncpg.Connection,
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
