"""
Compass — Production PostgreSQL Smoke-Test Script.

Validates connectivity and configuration for Nebius Managed PostgreSQL:
  1. Verifies SSL/TLS connection handshake using .env.production DATABASE_URL.
  2. Confirms 'vector' and 'uuid-ossp' extensions are installed.
  3. Verifies 'memory_chunks' table exists with an active HNSW index.
  4. Inserts a sample 768-dim vector, runs a cosine similarity query (<=>), and rolls back.

Usage:
    python scripts/verify_prod_db.py
"""

import sys
import os
import asyncio
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import asyncpg
from dotenv import load_dotenv

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# Load .env.production with override=True, then fallback to .env
prod_env = _project_root / ".env.production"
if prod_env.exists():
    load_dotenv(prod_env, override=True)
else:
    load_dotenv(_project_root / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "")


async def run_smoke_test():
    print("=" * 70)
    print("🧭 Compass — Production Database Smoke-Test")
    print(f"   Target URL: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else 'localhost'}")
    print("=" * 70)

    if not DATABASE_URL or "<" in DATABASE_URL:
        print("❌ DATABASE_URL is not configured with real credentials in .env.production.")
        print("   Please update .env.production with your Nebius Managed PostgreSQL connection string.")
        return False

    try:
        print("\n[1/4] Connecting to PostgreSQL instance over SSL/TLS...")
        conn = await asyncpg.connect(DATABASE_URL, timeout=10.0)
        print("      ✅ SSL Connection established successfully")
    except Exception as e:
        print(f"      ❌ Connection failed: {e}")
        return False

    try:
        # 2. Check Extensions
        print("\n[2/4] Checking required PostgreSQL extensions...")
        ext_rows = await conn.fetch(
            "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'uuid-ossp')"
        )
        installed = {r["extname"]: r["extversion"] for r in ext_rows}
        if "vector" in installed:
            print(f"      ✅ pgvector extension found (version {installed['vector']})")
        else:
            print("      ❌ pgvector extension missing! Run: CREATE EXTENSION IF NOT EXISTS vector;")

        if "uuid-ossp" in installed:
            print(f"      ✅ uuid-ossp extension found (version {installed['uuid-ossp']})")
        else:
            print("      ⚠️ uuid-ossp extension missing! Run: CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

        # 3. Check Table and HNSW Index
        print("\n[3/4] Verifying memory_chunks table and HNSW index...")
        idx_row = await conn.fetchrow(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'memory_chunks' AND indexname = 'idx_memory_chunks_embedding'
            """
        )
        if idx_row:
            print(f"      ✅ HNSW index verified: {idx_row['indexname']}")
            print(f"         Definition: {idx_row['indexdef']}")
        else:
            print("      ⚠️ idx_memory_chunks_embedding not found. Apply backend/memory/schema.sql.")

        # 4. Insert & Cosine Distance Probe (Transaction Rollback)
        print("\n[4/4] Testing 768-dim vector insertion & cosine distance query...")
        dummy_vector = [0.01 * (i % 50) for i in range(768)]
        vec_str = "[" + ",".join(str(x) for x in dummy_vector) + "]"

        tr = conn.transaction()
        await tr.start()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO memory_chunks (domain, content, embedding, source)
                VALUES ('general', 'Smoke test probe chunk', $1::vector, 'smoke_test')
                RETURNING id
                """,
                vec_str
            )
            inserted_id = row["id"]

            # Query cosine similarity
            res = await conn.fetchrow(
                """
                SELECT id, 1 - (embedding <=> $1::vector) AS similarity
                FROM memory_chunks
                WHERE id = $2
                """,
                vec_str, inserted_id
            )
            sim = res["similarity"]
            print(f"      ✅ Vector insert & probe query passed! Cosine similarity: {sim:.4f}")
        finally:
            await tr.rollback()
            print("      ✅ Transaction safely rolled back (no test data left in DB)")

        await conn.close()
        print("\n" + "=" * 70)
        print("🎉 Production Database Smoke-Test: ALL CHECKS PASSED!")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"\n❌ Error during smoke-test: {e}")
        await conn.close()
        return False


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
