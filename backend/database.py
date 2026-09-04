"""
Compass — Database Engine & Vector Connection.

Initializes asyncpg connection pool to Neon PostgreSQL instance using DATABASE_URL.
Ensures pgvector extension is created and registers the pgvector codec on every connection.
"""

import logging
from typing import Optional
import asyncpg
from pgvector.asyncpg import register_vector
from backend.config import get_settings

logger = logging.getLogger("compass.database")

_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register pgvector type codec on every connection in the pool."""
    await register_vector(conn)


async def init_pool(dsn: Optional[str] = None) -> asyncpg.Pool:
    """Initialize connection pool to Neon PostgreSQL and ensure pgvector is active."""
    global _pool
    if _pool is not None:
        return _pool

    if dsn is None:
        dsn = get_settings().DATABASE_URL

    # Ensure sslmode=require for Neon managed PostgreSQL
    if "sslmode" not in dsn and "localhost" not in dsn:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"

    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        init=_init_connection,
    )

    # Confirm pgvector extension is active
    try:
        async with _pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            logger.info("✅ pgvector extension active in Neon PostgreSQL")
    except Exception as e:
        logger.warning(f"Note on pgvector extension check: {e}")

    return _pool


async def get_pool() -> asyncpg.Pool:
    """Retrieve initialized connection pool."""
    global _pool
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Close connection pool gracefully."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
