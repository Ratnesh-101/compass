#!/usr/bin/env python3
"""
Audit script: Detect legacy synthetic fallback embeddings in memory_chunks.

Identifies rows where the vector matches the historical sinusoidal pseudo-random
formula: sin(seed + i * 0.17).

By default, runs in READ-ONLY report mode. Modifying rows requires the explicit flag
`--flag-reindex` and requires interactive confirmation for any remote database host.
"""

import sys
import os
import argparse
import asyncio
from urllib.parse import urlparse
from typing import List, Dict, Any

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import get_settings
from backend.services.embeddings import is_historical_fallback_embedding
import asyncpg


async def audit_fallback_embeddings(database_url: str, apply_flag: bool = False):
    parsed_url = urlparse(database_url)
    db_host = parsed_url.hostname or "unknown"
    db_port = parsed_url.port or 5432
    db_name = (parsed_url.path or "").lstrip("/")

    print("======================================================================")
    print("COMPASS MEMORY CHUNKS EMBEDDING AUDIT")
    print("======================================================================")
    print(f"Target Database Host : {db_host}")
    print(f"Target Database Port : {db_port}")
    print(f"Target Database Name : {db_name}")
    print(f"Execution Mode       : {'MUTATING (--flag-reindex)' if apply_flag else 'READ-ONLY (Report Mode)'}")
    print("======================================================================\n")

    conn = await asyncpg.connect(database_url)
    try:
        # Check if needs_reindex column exists, add if missing when in mutating mode
        has_reindex_col = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'memory_chunks' AND column_name = 'needs_reindex'
            )
            """
        )

        rows = await conn.fetch(
            "SELECT id, domain, project_id, content, embedding, source, tags, created_at, user_id FROM memory_chunks"
        )
        total = len(rows)
        fallback_rows: List[Dict[str, Any]] = []

        for r in rows:
            content = r["content"] or ""
            raw_emb = r["embedding"]
            if raw_emb is None:
                continue

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

        print(f"Total memory_chunks rows scanned : {total}")
        print(f"Detected legacy synthetic rows   : {len(fallback_rows)}")
        print(f"Clean (real or embedding-free)   : {total - len(fallback_rows)}\n")

        if fallback_rows:
            print("Identified Synthetic Fallback Chunks:")
            for item in fallback_rows:
                print(f"  - ID: {item['id']} | Domain: {item['domain']} | User: {item['user_id']} | Source: {item['source']}")
                print(f"    Content: {item['preview']}")

            if apply_flag:
                is_local = db_host in ("localhost", "127.0.0.1", "::1", "")
                if not is_local:
                    print(f"\n[WARNING] Target database host '{db_host}' is a REMOTE production/cloud database!")
                    confirm = input(f"Type 'yes' to flag {len(fallback_rows)} rows as needs_reindex in remote DB: ")
                    if confirm.strip().lower() != "yes":
                        print("Confirmation aborted. No changes made.")
                        return

                if not has_reindex_col:
                    await conn.execute("ALTER TABLE memory_chunks ADD COLUMN IF NOT EXISTS needs_reindex BOOLEAN NOT NULL DEFAULT FALSE;")

                ids_to_flag = [item["id"] for item in fallback_rows]
                await conn.execute(
                    """
                    UPDATE memory_chunks
                    SET needs_reindex = TRUE,
                        tags = array_append(COALESCE(tags, ARRAY[]::TEXT[]), 'needs_reindex')
                    WHERE id = ANY($1::int[])
                    """,
                    ids_to_flag,
                )
                print(f"\n[SUCCESS] Flagged {len(ids_to_flag)} rows with needs_reindex=TRUE and tag 'needs_reindex'.")
                print("These rows are now safely excluded from vector retrieval until re-embedded.")
            else:
                print("\n[NOTE] Running in READ-ONLY report mode. Zero database mutations performed.")
                print("To mark these rows so search_chunks excludes them, re-run with: --flag-reindex")
        else:
            print("[CLEAN] Zero legacy fallback embeddings detected.")

    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Audit and manage legacy fallback embeddings in memory_chunks.")
    parser.add_argument(
        "--flag-reindex",
        action="store_true",
        help="Mark detected fallback rows with needs_reindex=TRUE (requires confirmation for non-local hosts).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Custom database connection URL (defaults to DATABASE_URL environment variable).",
    )
    args = parser.parse_args()

    database_url = args.db_url or os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL") or get_settings().DATABASE_URL
    asyncio.run(audit_fallback_embeddings(database_url, apply_flag=args.flag_reindex))


if __name__ == "__main__":
    main()
