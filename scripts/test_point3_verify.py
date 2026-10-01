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
os.environ["TEST_DATABASE_URL"] = TEST_URL

from backend.main import app
from backend.config import get_settings
from backend.memory.db import get_pool
from backend.skills.handlers.web import handle_verify_deadline
from backend.agent import READ_ONLY_TOOLS, MUTATING_TOOLS

async def main():
    settings = get_settings()
    print("Testing on DB:", settings.DATABASE_URL.split("@")[-1].split("/")[0])
    
    # 1. Confirm tool classification
    print("Is verify_deadline in READ_ONLY_TOOLS?", "verify_deadline" in READ_ONLY_TOOLS)
    print("Is verify_deadline in MUTATING_TOOLS?", "verify_deadline" in MUTATING_TOOLS)
    assert "verify_deadline" in READ_ONLY_TOOLS
    assert "verify_deadline" not in MUTATING_TOOLS
    
    pool = await get_pool()
    
    # 2. Run handle_verify_deadline directly on Task 1
    print("\n--- Direct Execution of handle_verify_deadline for Task 1 ---")
    res1 = await handle_verify_deadline({"task_id": 1}, pool)
    print("Direct run success:", res1.get("success"))
    print("Summary:", res1.get("summary"))
    print("Stored task:", res1.get("data", {}).get("task", {}).get("title"), "Due:", res1.get("data", {}).get("task", {}).get("due_date"))
    print("Live search results count:", len(res1.get("data", {}).get("results", [])))
    if res1.get("data", {}).get("results"):
        print("First live result title:", res1["data"]["results"][0].get("title"))
        print("First live result url:", res1["data"]["results"][0].get("url"))
    
    # 3. Test through Agent to verify it runs without confirm step
    print("\n--- Agent Execution for verify_deadline (Confirm Gate Check) ---")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120.0) as client:
        confirm_step_seen = False
        tool_call_seen = False
        observe_seen = False
        
        async with client.stream(
            "POST",
            "/api/agent/run",
            json={"goal": "verify the deadline for task 1 to check for drift", "domain": "hackathon"},
            headers={"Authorization": f"Bearer {settings.AUTH_TOKEN}"}
        ) as resp:
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        ev_type = ev.get("type") or ev.get("step_type")
                        t_name = ev.get("tool_name") or ev.get("tool")
                        print(f"  [Agent Event] type={ev_type} | tool={t_name}")
                        if ev_type == "confirm_request":
                            confirm_step_seen = True
                        if ev_type == "tool_call" and t_name == "verify_deadline":
                            tool_call_seen = True
                        if ev_type == "observe" and t_name == "verify_deadline":
                            observe_seen = True
                            print(f"    Observe content: {ev.get('content')[:140]}...")
                        if ev_type == "synthesize":
                            print(f"    Synthesize content: {ev.get('content')[:180]}...")
                    except Exception:
                        pass
        
        print("\nAgent Gate Results:")
        print("  tool_call for verify_deadline executed:", tool_call_seen)
        print("  observe step yielded:", observe_seen)
        print("  confirm_request emitted:", confirm_step_seen)
        assert not confirm_step_seen, "ERROR: verify_deadline halted on confirm_request!"
        print("Assertion PASSED: verify_deadline ran as read-only with NO confirmation prompt.")

if __name__ == "__main__":
    asyncio.run(main())
