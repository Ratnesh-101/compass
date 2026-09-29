import os
import sys
import asyncio
import json
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Enforce isolated test branch DB — NEVER hardcode credentials; use env vars.
TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    print("ERROR: TEST_DATABASE_URL environment variable is not set.", file=sys.stderr)
    sys.exit(1)
os.environ["DATABASE_URL"] = TEST_URL

from backend.main import app
from backend.config import get_settings
from backend.memory.db import get_pool

async def main():
    settings = get_settings()
    print("Testing on DB:", settings.DATABASE_URL.split("@")[-1].split("/")[0])
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        before_count = await conn.fetchval("SELECT count(*) FROM memory_chunks")
        print("Count before agent run:", before_count)
    
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120.0) as client:
        # Step 1: Stream POST /api/agent/run to trigger ingest_url
        confirm_step = None
        run_id = None
        
        async with client.stream(
            "POST",
            "/api/agent/run",
            json={"goal": "remember this page: https://nebiusglobalaihackathon.devpost.com/details/dates", "domain": "hackathon"},
            headers={"Authorization": f"Bearer {settings.AUTH_TOKEN}"}
        ) as resp:
            print("POST /api/agent/run status:", resp.status_code)
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        ev_type = ev.get("type") or ev.get("step_type")
                        t_name = ev.get("tool_name") or ev.get("tool")
                        print(f"  [Turn 1 Event] type={ev_type} | tool={t_name}")
                        if ev.get("run_id"):
                            run_id = ev.get("run_id")
                        if ev_type == "confirm_request":
                            confirm_step = ev
                    except Exception:
                        pass
        
        print("\n--- Turn 1 Summary ---")
        print("Run ID:", run_id)
        if confirm_step:
            print("CONFIRM_REQUEST HALT DETECTED:")
            print("  tool_name:", confirm_step.get("tool_name") or confirm_step.get("tool"))
            print("  tool_args:", json.dumps(confirm_step.get("tool_args") or confirm_step.get("args"), indent=2))
        
        # Verify ZERO DB writes before confirmation
        async with pool.acquire() as conn:
            mid_count = await conn.fetchval("SELECT count(*) FROM memory_chunks")
            print("\nCount before confirm call (must equal before_count):", mid_count)
            assert mid_count == before_count, f"DB write occurred before confirmation! {mid_count} != {before_count}"
            print("Assertion PASSED: Zero DB writes before confirmation.")
        
        if run_id and confirm_step:
            print(f"\nResuming run {run_id} with action='approve' via POST /api/agent/run...")
            async with client.stream(
                "POST",
                "/api/agent/run",
                json={
                    "run_id": run_id,
                    "action": "approve",
                    "goal": "remember this page: https://nebiusglobalaihackathon.devpost.com/details/dates",
                },
                headers={"Authorization": f"Bearer {settings.AUTH_TOKEN}"}
            ) as resp2:
                print("POST /api/agent/run (resume) status:", resp2.status_code)
                async for line in resp2.aiter_lines():
                    line = line.strip()
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        try:
                            ev = json.loads(raw)
                            ev_type = ev.get("type") or ev.get("step_type")
                            t_name = ev.get("tool_name") or ev.get("tool")
                            print(f"  [Turn 2 Event] type={ev_type} | tool={t_name}")
                            if ev_type == "observe":
                                print(f"    Observe content: {ev.get('content')[:160]}...")
                            elif ev_type == "synthesize":
                                print(f"    Synthesize content: {ev.get('content')[:200]}...")
                        except Exception:
                            pass
            
            # Check DB count after confirmation
            async with pool.acquire() as conn:
                after_count = await conn.fetchval("SELECT count(*) FROM memory_chunks")
                print(f"\nCount after confirm call: {after_count} (was {mid_count})")
                new_rows = await conn.fetch(
                    "SELECT id, domain, content, source, tags, created_at FROM memory_chunks WHERE source LIKE '%devpost%' ORDER BY id DESC LIMIT 5"
                )
                print(f"Found {len(new_rows)} new memory chunk(s) for devpost in memory_chunks:")
                for r in new_rows:
                    print(f"  [ID {r['id']}] domain={r['domain']}, source={r['source']}, tags={r['tags']}")
                    print(f"    Preview: {r['content'][:140]}...\n")

if __name__ == "__main__":
    asyncio.run(main())
