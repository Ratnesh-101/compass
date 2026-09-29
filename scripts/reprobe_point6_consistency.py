import os
import sys
import asyncio
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

# Enforce isolated test branch DB — NEVER hardcode credentials; use env vars.
TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    print("ERROR: TEST_DATABASE_URL environment variable is not set.", file=sys.stderr)
    sys.exit(1)
os.environ["DATABASE_URL"] = TEST_URL

from backend.memory.db import get_pool
from backend.skills.handlers.web import handle_verify_deadline, handle_ingest_url

async def main():
    pool = await get_pool()
    
    print("=" * 60)
    print("CONSISTENCY RUNS FOR: ingest_url (3 runs)")
    print("=" * 60)
    target_url = "https://nebiusglobalaihackathon.devpost.com/details/dates"
    
    for i in range(1, 4):
        t0 = time.perf_counter()
        res = await handle_ingest_url({"url": target_url, "domain": "hackathon"}, pool)
        elapsed = time.perf_counter() - t0
        success = res.get("success")
        chunks = res.get("data", {}).get("chunks_stored", 0)
        flagged = res.get("data", {}).get("injection_flagged", False)
        print(f"Run {i}: success={success} | chunks_stored={chunks} | injection_flagged={flagged} | elapsed={elapsed:.2f}s")
        print(f"       summary: {res.get('summary')}")
    
    print("\n" + "=" * 60)
    print("CONSISTENCY RUNS FOR: verify_deadline (3 runs)")
    print("=" * 60)
    # Check baseline task 1 (Draft API specs, due 2026-09-06)
    for i in range(1, 4):
        t0 = time.perf_counter()
        res = await handle_verify_deadline({"task_id": 1}, pool)
        elapsed = time.perf_counter() - t0
        success = res.get("success")
        results_count = len(res.get("data", {}).get("results", []))
        stored_due = res.get("data", {}).get("task", {}).get("due_date")
        print(f"Run {i}: success={success} | results_retrieved={results_count} | stored_due={stored_due} | elapsed={elapsed:.2f}s")
        print(f"       summary: {res.get('summary')}")

if __name__ == "__main__":
    asyncio.run(main())
