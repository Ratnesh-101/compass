#!/usr/bin/env python3
"""
Compass — Standalone Idempotent Migration for Parked Thoughts ("Park it" shelf).

Applies the `parked_thoughts` table and indexes to any target Neon / Postgres database.
Safe to run multiple times.

Usage:
    python scripts/migrate_parked_thoughts.py
    python scripts/migrate_parked_thoughts.py --url "postgresql://..."
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv()

import asyncpg

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS parked_thoughts (
    id                 SERIAL        PRIMARY KEY,
    user_id            TEXT          NOT NULL DEFAULT 'default_user',
    conversation_id    TEXT,
    text               TEXT          NOT NULL,
    status             TEXT          NOT NULL DEFAULT 'parked',
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_parked_thoughts_user_status ON parked_thoughts(user_id, status);
CREATE INDEX IF NOT EXISTS idx_parked_thoughts_conversation ON parked_thoughts(conversation_id);
"""


async def run_migration(database_url: str) -> None:
    print(f"Connecting to database: {database_url[:30]}...")
    conn = await asyncpg.connect(database_url)
    try:
        print("Applying migration for parked_thoughts...")
        await conn.execute(MIGRATION_SQL)
        print("✅ Migration applied successfully!")
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Run parked thoughts schema migration")
    parser.add_argument("--url", help="Database URL (defaults to DATABASE_URL in .env)")
    args = parser.parse_args()

    db_url = args.url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set and no --url provided.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_migration(db_url))


if __name__ == "__main__":
    main()
