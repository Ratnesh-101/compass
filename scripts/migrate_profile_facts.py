#!/usr/bin/env python3
"""
Compass — Standalone Idempotent Migration for Profile Facts.

Applies the `user_profile_facts` table and index to any target Neon / Postgres database.
Safe to run multiple times.

Usage:
    python scripts/migrate_profile_facts.py
    python scripts/migrate_profile_facts.py --url "postgresql://..."
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv()

import asyncpg

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS user_profile_facts (
    id                 SERIAL        PRIMARY KEY,
    user_id            TEXT          NOT NULL DEFAULT 'default_user',
    key                TEXT          NOT NULL,
    value              TEXT          NOT NULL,
    source_message_id  INTEGER       REFERENCES messages(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE(user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_user_profile_facts_user ON user_profile_facts(user_id);
"""


async def run_migration(database_url: str) -> None:
    print(f"Connecting to database: {database_url[:30]}...")
    conn = await asyncpg.connect(database_url)
    try:
        print("Applying migration for user_profile_facts...")
        await conn.execute(MIGRATION_SQL)
        print("✅ Migration applied successfully!")
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Run profile facts schema migration")
    parser.add_argument("--url", help="Database URL (defaults to DATABASE_URL in .env)")
    args = parser.parse_args()

    db_url = args.url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set and no --url provided.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run_migration(db_url))


if __name__ == "__main__":
    main()
