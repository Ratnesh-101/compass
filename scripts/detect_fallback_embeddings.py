#!/usr/bin/env python3
"""
Audit script: Detect legacy synthetic fallback embeddings in memory_chunks.

Identifies rows where the vector matches the historical sinusoidal pseudo-random
formula: sin(seed + i * 0.17).
Does NOT delete any data. Reports IDs, domains, and proposed safe cleanup actions.
"""

import sys
import os
import asyncio
from typing import List, Dict, Any

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import get_settings
from backend.services.embeddings import is_historical_fallback_embedding
import asyncpg


async def audit_fallback_embeddings(database_url: str):
    print("Connecting to database...")
    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            "SELECT id, domain, project_id, content, embedding, source, tags, created_at, user_id FROM memory_chunks"
        )
        total = len(rows)
        fallback_rows: List[Dict[str, Any]] = []

        for r in rows:
            content = r["content"] or ""
            raw_emb = r["embedding"]
            # Convert asyncpg pgvector type to list of floats if needed
            if hasattr(raw_emb, "tolist"):
                vec = raw_emb.tolist()
            elif isinstance(raw_emb, (list, tuple)):
                vec = [float(x) for x in raw_emb]
            elif isinstance(raw_emb, str):
                vec = [float(x.strip()) for x in raw_emb.strip("[]").split(",") if x.strip()]
            else:
                vec = [float(x) for x in list(raw_emb)]

            if is_historical_fallback_embedding(vec, content):
                fallback_rows.append({
                    "id": r["id"],
                    "domain": r["domain"],
                    "source": r["source"],
                    "user_id": r["user_id"],
                    "created_at": str(r["created_at"]),
                    "preview": content[:60] + "..." if len(content) > 60 else content,
                })

        print("\n=== MEMORY CHUNKS EMBEDDING AUDIT REPORT ===")
        print(f"Total memory_chunks rows: {total}")
        print(f"Detected legacy synthetic fallback rows: {len(fallback_rows)}")
        print(f"Clean (real or non-synthetic) rows: {total - len(fallback_rows)}")

        if fallback_rows:
            print("\nIdentified Synthetic Fallback Rows:")
            for item in fallback_rows:
                print(f"  - ID: {item['id']} | Domain: {item['domain']} | Source: {item['source']} | User: {item['user_id']}")
                print(f"    Preview: {item['preview']}")

            print("\n=== PROPOSED NON-DESTRUCTIVE CLEANUP PLAN ===")
            print("1. DO NOT DELETE user text content.")
            print("2. Add tag 'needs_reembedding' to these rows.")
            print("3. When a live Nebius API key is configured, execute a batch re-embedding")
            print("   script that regenerates vectors using Qwen/Qwen3-Embedding-8B.")
            print("4. Alternatively, NULL out the embedding column so vector similarity skips them")
            print("   until re-indexed, while preserving the text and user metadata.")
        else:
            print("\nNo synthetic fallback embeddings found!")

    finally:
        await conn.close()


if __name__ == "__main__":
    db_url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL") or get_settings().DATABASE_URL
    asyncio.run(audit_fallback_embeddings(db_url))
