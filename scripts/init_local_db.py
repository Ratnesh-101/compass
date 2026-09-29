import asyncio
import asyncpg
from pathlib import Path

async def main():
    dsn = "postgresql://compass:compass@localhost:5432/compass"
    print(f"Connecting to local Postgres at {dsn}...")
    conn = await asyncpg.connect(dsn)
    schema_sql = Path("backend/memory/schema.sql").read_text(encoding="utf-8")
    print("Applying backend/memory/schema.sql...")
    await conn.execute(schema_sql)
    await conn.close()
    print("Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(main())
