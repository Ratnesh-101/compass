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
os.environ["TEST_DATABASE_URL"] = TEST_URL

from backend.memory.db import get_pool
from backend.skills.handlers.web import handle_verify_deadline
from backend.skills.handlers.tasks import handle_add_task, handle_edit_task

async def main():
    pool = await get_pool()
    
    # 1. Create a task with a deliberately drifted date on TEST BRANCH ONLY
    print("Creating test task with drifted date (2026-10-15 instead of 2026-10-30)...")
    add_res = await handle_add_task({
        "title": "Nebius x NVIDIA Global AI Hackathon submission",
        "domain": "hackathon",
        "due_date": "2026-10-15",
        "priority": "urgent",
    }, pool)
    task_id = add_res["data"]["id"]
    print(f"Created task ID {task_id} with stored due_date: 2026-10-15")
    
    # 2. Run verify_deadline
    print(f"\nRunning handle_verify_deadline for task {task_id}...")
    res = await handle_verify_deadline({"task_id": task_id}, pool)
    
    print("Success:", res.get("success"))
    print("Summary:", res.get("summary"))
    print("Stored due:", res.get("data", {}).get("task", {}).get("due_date"))
    print("Citations found:", res.get("data", {}).get("citations", []))
    
    # Check what snippets were retrieved
    results = res.get("data", {}).get("results", [])
    print(f"\nRetrieved {len(results)} live search result(s):")
    devpost_found = False
    for r in results:
        print(f"  Source: {r.get('title')} ({r.get('url')})")
        content = r.get("content", "")
        if "Oct 30" in content or "October 30" in content:
            devpost_found = True
            print(f"  >>> EVIDENCE OF REAL DEADLINE: {content[:160]}...")
    
    print("\nDrift Analysis:")
    if devpost_found:
        print("  [DRIFT DETECTED]")
        print("  Stored date in DB : 2026-10-15")
        print("  Official Live Web : October 30, 2026 @ 10:00am PDT (from nebiusglobalaihackathon.devpost.com)")
        print("  Difference        : 15 days drift!")
    
    # 3. Clean up / Revert test task on test branch
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)
        print(f"\nCleaned up temporary test task {task_id} from test branch DB.")

if __name__ == "__main__":
    asyncio.run(main())
