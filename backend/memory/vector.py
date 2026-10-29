"""
Compass — Vector Operations for Memory Chunks.

Handles generating 768-dim embeddings via Nebius Token Factory (Qwen/Qwen3-Embedding-8B)
and querying or storing chunks in PostgreSQL with pgvector cosine similarity.
"""

import logging
from typing import List, Optional, Dict, Any, Union
import asyncpg
from asyncpg.pool import PoolConnectionProxy
from backend.config import get_settings
from backend.services.embeddings import get_embedding

logger = logging.getLogger("compass.memory.vector")
settings = get_settings()

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]


def compute_content_hash(content: str) -> str:
    """Normalize text content (trim, lower, collapse whitespace) and compute SHA-256 hash."""
    import hashlib
    normalized = " ".join(content.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def store_chunk(
    conn: DbConn,
    content: str,
    domain: str = "general",
    project_id: Optional[int] = None,
    source: Optional[str] = None,
    tags: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Store text content along with its 768-dim vector in memory_chunks with strict deduplication via content_hash.

    If the embedding API is unavailable, skips writing to memory_chunks and marks status as pending_retry.
    """
    content_hash = compute_content_hash(content)
    embedding = await get_embedding(content)

    if embedding is None:
        logger.warning(
            f"Embedding service unavailable for content_hash={content_hash[:8]}. "
            f"Skipping write to memory_chunks and marking pending retry."
        )
        return {
            "status": "pending_retry",
            "reason": "embedding_unavailable",
            "content": content,
            "domain": domain,
            "project_id": project_id,
            "source": source,
            "tags": tags or [],
            "user_id": user_id,
            "content_hash": content_hash,
        }

    row = await conn.fetchrow(
        """
        INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags, user_id, content_hash)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (user_id, content_hash) DO UPDATE
        SET source = COALESCE(EXCLUDED.source, memory_chunks.source),
            tags = EXCLUDED.tags
        RETURNING id, domain, project_id, content, source, tags, user_id, created_at
        """,
        domain, project_id, content, embedding, source, tags or [], user_id, content_hash
    )
    return dict(row) if row else {}


async def search_chunks(
    conn: DbConn,
    query: str,
    domain: Optional[str] = None,
    limit: int = 5,
    user_id: Optional[str] = None,
    query_vec: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Search memory chunks by cosine similarity with per-account isolation.

    If query_vec is not provided and embedding generation fails, skips vector retrieval and returns empty list.
    """
    if not user_id:
        return []

    if query_vec is None:
        query_vec = await get_embedding(query)

    if query_vec is None:
        logger.warning("Vector retrieval skipped: embedding service is unavailable for query.")
        return []

    if domain:
        rows = await conn.fetch(
            """
            SELECT id, domain, project_id, content, source, tags, created_at, user_id,
                   1 - (embedding <=> $1) AS similarity
            FROM memory_chunks
            WHERE domain = $2 AND user_id = $3
            ORDER BY embedding <=> $1 ASC
            LIMIT $4
            """,
            query_vec, domain, user_id, limit
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, domain, project_id, content, source, tags, created_at, user_id,
                   1 - (embedding <=> $1) AS similarity
            FROM memory_chunks
            WHERE user_id = $2
            ORDER BY embedding <=> $1 ASC
            LIMIT $3
            """,
            query_vec, user_id, limit
        )

    return [dict(r) for r in rows]
