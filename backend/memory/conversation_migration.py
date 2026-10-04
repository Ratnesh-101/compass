"""
Compass — Guest Conversation & Memory Migration Module.

Handles:
  - Migration overview & candidate listing
  - Single & bulk conversation cloning (COPY/LINK -> PRESERVE semantics)
  - Memory chunk migration with deduplication
  - Idempotency tracking via guest_migration_log
  - Guest data privacy erasure
"""

import uuid
import logging
from typing import Any, Dict, List, Optional, Union

# Define DbConn protocol compatible with asyncpg Connection / Pool
DbConn = Any

logger = logging.getLogger("compass.memory.migration")


async def get_guest_migration_overview(
    conn: DbConn,
    guest_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Retrieve migration statistics: total, unimported, and already imported conversations and memories."""
    has_log_table = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'guest_migration_log')"
    )
    has_guest_col = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'conversations' AND column_name = 'guest_id')"
    )
    if not has_guest_col:
        return {
            "eligible": False,
            "has_guest_data": False,
            "guest_conversations_count": 0,
            "guest_id": guest_id,
            "user_id": user_id,
            "total_conversations": 0,
            "unimported_conversations": 0,
            "already_imported_count": 0,
            "total_memories": 0,
            "unimported_memories": 0,
        }

    guest_alt = guest_id[6:] if guest_id.startswith("guest_") else f"guest_{guest_id}"
    total_convs = await conn.fetchval(
        "SELECT COUNT(*) FROM conversations WHERE (guest_id = $1 OR guest_id = $2) AND user_id IS NULL",
        guest_id, guest_alt
    ) or 0

    already_imported = 0
    if has_log_table and total_convs > 0:
        already_imported = await conn.fetchval(
            """
            SELECT COUNT(*) FROM guest_migration_log gml
            JOIN conversations c ON c.id = gml.guest_conversation_id
            WHERE (gml.guest_id = $1 OR gml.guest_id = $3) AND gml.user_id = $2
            """,
            guest_id, user_id, guest_alt
        ) or 0

    unimported_convs = max(0, total_convs - already_imported)

    guest_pattern = f"guest_{guest_id}"
    total_mems = await conn.fetchval(
        "SELECT COUNT(*) FROM memory_chunks WHERE user_id = $1 OR user_id = $2",
        guest_id, guest_pattern
    ) or 0

    return {
        "eligible": unimported_convs > 0 or total_mems > 0,
        "has_guest_data": int(total_convs) > 0 or int(total_mems) > 0,
        "guest_conversations_count": int(unimported_convs),
        "guest_id": guest_id,
        "user_id": user_id,
        "total_conversations": int(total_convs),
        "unimported_conversations": int(unimported_convs),
        "already_imported_count": int(already_imported),
        "total_memories": int(total_mems),
        "unimported_memories": int(total_mems),
    }


async def list_guest_conversations_for_migration(
    conn: DbConn,
    guest_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """List all guest conversations with metadata, preview, and already_imported status."""
    has_log_table = await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'guest_migration_log')"
    )

    guest_alt = guest_id[6:] if guest_id.startswith("guest_") else f"guest_{guest_id}"
    if has_log_table:
        query = """
            SELECT c.id, c.title, c.started_at, c.last_active_at,
                   COUNT(m.id) AS message_count,
                   (
                       SELECT content FROM messages
                       WHERE conversation_id = c.id
                       ORDER BY created_at DESC, id DESC LIMIT 1
                   ) AS last_message_preview,
                   (gml.id IS NOT NULL) AS already_imported,
                   gml.imported_at
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            LEFT JOIN guest_migration_log gml 
                ON gml.guest_conversation_id = c.id AND gml.user_id = $2
            WHERE (c.guest_id = $1 OR c.guest_id = $3) AND c.user_id IS NULL
            GROUP BY c.id, c.title, c.started_at, c.last_active_at, gml.id, gml.imported_at
            ORDER BY c.last_active_at DESC
        """
        rows = await conn.fetch(query, guest_id, user_id, guest_alt)
    else:
        query = """
            SELECT c.id, c.title, c.started_at, c.last_active_at,
                   COUNT(m.id) AS message_count,
                   (
                       SELECT content FROM messages
                       WHERE conversation_id = c.id
                       ORDER BY created_at DESC, id DESC LIMIT 1
                   ) AS last_message_preview,
                   FALSE AS already_imported,
                   NULL::timestamptz AS imported_at
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE (c.guest_id = $1 OR c.guest_id = $2) AND c.user_id IS NULL
            GROUP BY c.id, c.title, c.started_at, c.last_active_at
            ORDER BY c.last_active_at DESC
        """
        rows = await conn.fetch(query, guest_id, guest_alt)
    return [
        {
            "id": str(r["id"]),
            "title": r["title"] or "Chat Session",
            "started_at": r["started_at"].isoformat() if hasattr(r["started_at"], "isoformat") else str(r["started_at"]),
            "last_active_at": r["last_active_at"].isoformat() if hasattr(r["last_active_at"], "isoformat") else str(r["last_active_at"]),
            "message_count": int(r["message_count"] or 0),
            "already_imported": bool(r.get("already_imported", False)),
            "imported_at": r["imported_at"].isoformat() if r.get("imported_at") and hasattr(r["imported_at"], "isoformat") else None,
            "preview": (r.get("last_message_preview") or "")[:120],
        }
        for r in rows
    ]


async def migrate_single_conversation(
    conn: DbConn,
    guest_conv_id: Union[str, uuid.UUID],
    guest_id: str,
    user_id: str,
) -> Optional[str]:
    """Clone a single guest conversation to the user account with COPY/LINK->PRESERVE semantics.
    Strictly idempotent: returns existing user_conversation_id if already migrated.
    """
    try:
        cid = uuid.UUID(str(guest_conv_id))
    except (ValueError, TypeError):
        return None

    # Execute entire migration inside an atomic transaction with row-level locking
    async with conn.transaction():
        # 1. Lock source guest conversation row exclusively to serialize concurrent migration attempts
        guest_conv = await conn.fetchrow(
            """
            SELECT id, title, started_at, last_active_at 
            FROM conversations 
            WHERE id = $1 AND guest_id = $2 AND user_id IS NULL
            FOR UPDATE
            """,
            cid, guest_id
        )
        if not guest_conv:
            return None

        # 2. Idempotency check: if already migrated by a prior or concurrent transaction
        existing = await conn.fetchrow(
            "SELECT user_conversation_id FROM guest_migration_log WHERE guest_conversation_id = $1 AND user_id = $2",
            cid, user_id
        )
        if existing:
            return str(existing["user_conversation_id"])

        # 3. Create clone for authenticated user with imported_from_id reference
        new_cid = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO conversations (id, title, user_id, guest_id, imported_from_id, started_at, last_active_at)
            VALUES ($1, $2, $3, NULL, $4, $5, $6)
            """,
            new_cid, guest_conv["title"], user_id, cid, guest_conv["started_at"], guest_conv["last_active_at"]
        )

        # 4. Copy all messages
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, skill_called, created_at)
            SELECT $1, role, content, skill_called, created_at
            FROM messages
            WHERE conversation_id = $2
            ORDER BY created_at ASC, id ASC
            """,
            new_cid, cid
        )

        # 5. Record migration mapping
        await conn.execute(
            """
            INSERT INTO guest_migration_log (guest_id, user_id, guest_conversation_id, user_conversation_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guest_conversation_id, user_id) DO NOTHING
            """,
            guest_id, user_id, cid, new_cid
        )

        return str(new_cid)


async def migrate_all_guest_conversations(
    conn: DbConn,
    guest_id: str,
    user_id: str,
) -> int:
    """Migrate all unimported conversations belonging to guest_id into user_id."""
    guest_alt = guest_id[6:] if guest_id.startswith("guest_") else f"guest_{guest_id}"
    unimported = await conn.fetch(
        """
        SELECT c.id FROM conversations c
        LEFT JOIN guest_migration_log gml 
        ON gml.guest_conversation_id = c.id AND gml.user_id = $2
        WHERE (c.guest_id = $1 OR c.guest_id = $3) AND c.user_id IS NULL AND gml.id IS NULL
        """,
        guest_id, user_id, guest_alt
    )

    count = 0
    for row in unimported:
        migrated_id = await migrate_single_conversation(conn, row["id"], guest_id, user_id)
        if migrated_id:
            count += 1
    return count


async def migrate_guest_memories(
    conn: DbConn,
    guest_id: str,
    user_id: str,
) -> int:
    """Clone memory_chunks from guest identity to user account with deduplication.
    Original guest memory chunks are preserved.
    """
    guest_pattern = f"guest_{guest_id}"
    chunks = await conn.fetch(
        """
        SELECT id, domain, project_id, content, embedding, source, tags
        FROM memory_chunks
        WHERE user_id = $1 OR user_id = $2
        ORDER BY id ASC
        """,
        guest_id, guest_pattern
    )

    imported_count = 0
    for ch in chunks:
        exists = await conn.fetchval(
            """
            SELECT id FROM memory_chunks
            WHERE user_id = $1 AND domain = $2 AND content = $3
            LIMIT 1
            """,
            user_id, ch["domain"], ch["content"]
        )
        if exists:
            continue

        await conn.execute(
            """
            INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags, user_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            ch["domain"], ch["project_id"], ch["content"], ch["embedding"],
            f"imported_from_guest:{ch.get('source') or ''}", ch["tags"], user_id
        )
        imported_count += 1

    return imported_count


async def delete_guest_data(
    conn: DbConn,
    guest_id: str,
) -> Dict[str, int]:
    """Privacy control: permanently delete all guest conversations and memory chunks for a guest."""
    guest_alt = guest_id[6:] if guest_id.startswith("guest_") else f"guest_{guest_id}"

    deleted_convs = await conn.fetchval(
        """
        WITH deleted AS (
            DELETE FROM conversations
            WHERE (guest_id = $1 OR guest_id = $2) AND user_id IS NULL
            RETURNING id
        )
        SELECT COUNT(*) FROM deleted
        """,
        guest_id, guest_alt
    ) or 0

    deleted_mems = await conn.fetchval(
        """
        WITH deleted AS (
            DELETE FROM memory_chunks
            WHERE user_id = $1 OR user_id = $2
            RETURNING id
        )
        SELECT COUNT(*) FROM deleted
        """,
        guest_id, guest_alt
    ) or 0

    return {
        "deleted_conversations": int(deleted_convs),
        "deleted_memories": int(deleted_mems),
    }
