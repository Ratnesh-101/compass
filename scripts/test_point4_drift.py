import os
import sys
import asyncio
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Enforce isolated test branch DB — NEVER hardcode credentials; use env vars.
TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    print("ERROR: TEST_DATABASE_URL environment variable is not set.", file=sys.stderr)
    sys.exit(1)
os.environ["DATABASE_URL"] = TEST_URL

from backend.memory.db import get_pool
from backend.skills.handlers.web import handle_verify_deadline

async def main():
    pool = await get_pool()
    # Check baseline tasks
    baseline_ids = [1, 2, 3, 4, 5, 6, 8, 43, 44, 45]
    print(f"Checking {len(baseline_ids)} baseline tasks on test branch DB...\n")
    
    for tid in baseline_ids:
        res = await handle_verify_deadline({"task_id": tid}, pool)
        if not res.get("success"):
            print(f"Task {tid}: skipped or error: {res.get('summary')}")
            continue
        task = res["data"]["task"]
        results = res["data"].get("results", [])
        print(f"Task {tid}: \"{task.get('title')}\"")
        print(f"  Stored due: {task.get('due_date')}")
        print(f"  Live results retrieved: {len(results)}")
        if results:
            print(f"  Top source: {results[0].get('title')} ({results[0].get('url')})")
            print(f"  Snippet: {results[0].get('content')[:120]}...")
        print()

if __name__ == "__main__":
    asyncio.run(main())
