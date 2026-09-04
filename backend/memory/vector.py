"""
Compass — Vector Operations for Memory Chunks.

Handles generating 768-dim embeddings via Nebius Token Factory (Qwen/Qwen3-Embedding-8B)
and querying or storing chunks in PostgreSQL with pgvector cosine similarity.
"""

from typing import List, Optional, Dict, Any
import asyncpg
from openai import OpenAI
from backend.config import get_settings

settings = get_settings()


def get_embedding(text: str) -> List[float]:
    """Generate a 768-dimensional embedding via Nebius Token Factory with Matryoshka truncation."""
    client = OpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
    )
    resp = client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=text,
        dimensions=settings.EMBEDDING_DIMENSION,
    )
    return resp.data[0].embedding


async def store_chunk(
    conn: asyncpg.Connection,
    content: str,
    domain: str = "general",
    project_id: Optional[int] = None,
    source: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store text content along with its 768-dim vector in memory_chunks."""
    embedding = get_embedding(content)

    row = await conn.fetchrow(
        """
        INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, domain, project_id, content, source, tags, created_at
        """,
        domain, project_id, content, embedding, source, tags or []
    )
    return dict(row) if row else {}


async def search_chunks(
    conn: asyncpg.Connection,
    query: str,
    domain: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Search memory chunks by cosine similarity using the HNSW index."""
    query_vec = get_embedding(query)

    if domain:
        rows = await conn.fetch(
            """
            SELECT id, domain, project_id, content, source, tags, created_at,
                   1 - (embedding <=> $1) AS similarity
            FROM memory_chunks
            WHERE domain = $2
            ORDER BY embedding <=> $1 ASC
            LIMIT $3
            """,
            query_vec, domain, limit
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, domain, project_id, content, source, tags, created_at,
                   1 - (embedding <=> $1) AS similarity
            FROM memory_chunks
            ORDER BY embedding <=> $1 ASC
            LIMIT $2
            """,
            query_vec, limit
        )

    return [dict(r) for r in rows]
