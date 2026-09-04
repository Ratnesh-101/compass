import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import asyncio
import asyncpg
from backend.config import get_settings


async def verify_hnsw():
    dsn = get_settings().DATABASE_URL
    print(f"Connecting to Neon to check HNSW index...")
    conn = await asyncpg.connect(dsn)
    try:
        # Check pgvector extension
        ext = await conn.fetchval("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
        print(f"pgvector extension: active (version {ext})")

        # Check existing indexes on memory_chunks
        rows = await conn.fetch("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'memory_chunks';
        """)
        print(f"Indexes on memory_chunks ({len(rows)} found):")
        has_hnsw = False
        for r in rows:
            print(f"  • {r['indexname']}: {r['indexdef']}")
            if "hnsw" in r['indexdef'].lower():
                has_hnsw = True

        if not has_hnsw:
            print("Creating HNSW index on memory_chunks(embedding vector_cosine_ops)...")
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding 
                ON memory_chunks USING hnsw (embedding vector_cosine_ops);
            """)
            print("[OK] HNSW index created successfully!")
        else:
            print("[OK] HNSW index (vector_cosine_ops) is confirmed active!")


    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(verify_hnsw())
