import asyncio
import os
import sys
from pathlib import Path
import asyncpg

async def main():
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        print("ERROR: No database URL provided via DATABASE_URL or TEST_DATABASE_URL environment variable.", file=sys.stderr)
        sys.exit(1)
    print("Connecting to database...")
    conn = await asyncpg.connect(dsn)
    schema_sql = Path("backend/memory/schema.sql").read_text(encoding="utf-8")
    print("Applying backend/memory/schema.sql...")
    await conn.execute(schema_sql)
    await conn.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(main())
