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
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    row = await conn.fetchrow(
        """
        INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags)
        VALUES ($1, $2, $3, $4::vector, $5, $6)
        RETURNING id, domain, project_id, content, source, tags, created_at
        """,
        domain, project_id, content, vec_str, source, tags or []
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
    vec_str = "[" + ",".join(str(x) for x in query_vec) + "]"

    if domain:
        rows = await conn.fetch(
            """
            SELECT id, domain, project_id, content, source, tags, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM memory_chunks
            WHERE domain = $2
            ORDER BY embedding <=> $1::vector ASC
            LIMIT $3
            """,
            vec_str, domain, limit
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, domain, project_id, content, source, tags, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM memory_chunks
            ORDER BY embedding <=> $1::vector ASC
            LIMIT $2
            """,
            vec_str, limit
        )

    return [dict(r) for r in rows]
