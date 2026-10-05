"""
Compass — Persistent User Profile Facts Data Access.

Stores and retrieves explicit user personal facts (e.g. name, goals, preferences)
in the `user_profile_facts` table.
"""

from typing import Dict, List, Optional, Any, Union
import logging
import asyncpg
from asyncpg.pool import PoolConnectionProxy

logger = logging.getLogger("compass.memory.profile")

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]


async def get_profile_facts(
    conn: DbConn,
    user_id: str = "default_user",
) -> Dict[str, str]:
    """Retrieve all profile facts for a user as a key-value dictionary."""
    try:
        rows = await conn.fetch(
            """
            SELECT key, value
            FROM user_profile_facts
            WHERE user_id = $1
            ORDER BY updated_at ASC
            """,
            user_id,
        )
        return {r["key"]: r["value"] for r in rows}
    except Exception as e:
        logger.warning("Could not fetch profile facts for %s (continuing gracefully): %s", user_id, e)
        return {}


async def list_profile_facts_records(
    conn: DbConn,
    user_id: str = "default_user",
) -> List[Dict[str, Any]]:
    """Retrieve all profile fact records for a user with timestamps and source message."""
    try:
        rows = await conn.fetch(
            """
            SELECT id, user_id, key, value, source_message_id, created_at, updated_at
            FROM user_profile_facts
            WHERE user_id = $1
            ORDER BY key ASC
            """,
            user_id,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("Could not list profile fact records for %s: %s", user_id, e)
        return []


MAX_KEY_LENGTH = 40
MAX_VALUE_LENGTH = 200


def sanitize_fact_key(key: str) -> str:
    """Sanitize and cap fact key to prevent injection and unbounded growth."""
    cleaned = str(key).replace("\r", " ").replace("\n", " ").strip().lower()
    cleaned = " ".join(cleaned.split())
    return cleaned[:MAX_KEY_LENGTH]


def sanitize_fact_value(value: str) -> str:
    """Sanitize and cap fact value to prevent injection and unbounded growth."""
    cleaned = str(value).replace("\r", " ").replace("\n", " ").strip()
    cleaned = " ".join(cleaned.split())
    return cleaned[:MAX_VALUE_LENGTH]


async def set_profile_fact(
    conn: DbConn,
    key: str,
    value: str,
    user_id: str = "default_user",
    source_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Insert or update a profile fact for a user with length caps and sanitization.

    If key exists, updates value and updated_at timestamp.
    """
    clean_key = sanitize_fact_key(key)
    clean_val = sanitize_fact_value(value)
    if not clean_key or not clean_val:
        return {}

    row = await conn.fetchrow(
        """
        INSERT INTO user_profile_facts (user_id, key, value, source_message_id, created_at, updated_at)
        VALUES ($1, $2, $3, $4, now(), now())
        ON CONFLICT (user_id, key)
        DO UPDATE SET
            value = EXCLUDED.value,
            source_message_id = COALESCE(EXCLUDED.source_message_id, user_profile_facts.source_message_id),
            updated_at = now()
        RETURNING id, user_id, key, value, source_message_id, created_at, updated_at
        """,
        user_id,
        clean_key,
        clean_val,
        source_message_id,
    )

    return dict(row) if row else {}


async def delete_profile_fact(
    conn: DbConn,
    key: str,
    user_id: str = "default_user",
) -> bool:
    """Delete a profile fact by key. Returns True if a record was removed."""
    clean_key = key.strip().lower()
    try:
        res = await conn.execute(
            """
            DELETE FROM user_profile_facts
            WHERE user_id = $1 AND (key = $2 OR key ILIKE $2)
            """,
            user_id,
            clean_key,
        )
        # res format: 'DELETE N'
        parts = res.split()
        return len(parts) == 2 and int(parts[1]) > 0
    except Exception as e:
        logger.debug("Could not delete profile fact %s for %s: %s", clean_key, user_id, e)
        return False
