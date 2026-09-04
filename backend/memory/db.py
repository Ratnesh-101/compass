"""
Compass — Async database connection pool.

Uses asyncpg with pgvector codec registration.
The pool registers the vector type on every new connection via the `init` callback,
so all connections in the pool can read/write VECTOR columns.
"""

import asyncpg
from pgvector.asyncpg import register_vector


_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Called for every new connection in the pool.
    Registers the pgvector type codec so asyncpg can handle VECTOR columns."""
    await register_vector(conn)


async def init_pool(dsn: str | None = None) -> asyncpg.Pool:
    """Create the connection pool. Safe to call multiple times (idempotent).

    Args:
        dsn: PostgreSQL connection string. If None, reads from settings.
    """
    global _pool
    if _pool is not None:
        return _pool

    if dsn is None:
        from backend.config import get_settings
        dsn = get_settings().DATABASE_URL

    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        init=_init_connection,  # register pgvector on every connection
    )
    return _pool  # type: ignore[return-value]


async def get_pool() -> asyncpg.Pool:
    """Return the existing pool or initialize if not yet created."""
    global _pool
    if _pool is None:
        return await init_pool()
    return _pool


async def close_pool() -> None:
    """Gracefully close the pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
