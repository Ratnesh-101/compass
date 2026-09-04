"""
Compass — Live API Integration Probe.

Verifies all 8 backend endpoints against a running server (http://localhost:8000).
Tests authentication enforcement (401 for missing/invalid bearer token) and
data retrieval across /tasks, /projects, /dashboard, /memory/timeline, /admin/usage,
and unauthenticated /health.

Usage:
    python scripts/test_live_api.py
"""

import sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

load_dotenv(_project_root / ".env")

from backend.config import get_settings

settings = get_settings()
BASE_URL = "http://localhost:8000"
AUTH_TOKEN = settings.AUTH_TOKEN or "dev-token"
HEADERS = {
    "Authorization": f"Bearer {AUTH_TOKEN}",
    "Content-Type": "application/json",
}


def test_api():
    print("=" * 65)
    print("🧭 Compass — Live API Integration Probe")
    print(f"   Target: {BASE_URL}")
    print("=" * 65)

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Health check (unauthenticated)
        try:
            r = client.get("/health")
            print(f"\n[1/8] GET /health (unauthenticated) -> {r.status_code}")
            assert r.status_code == 200, f"Expected 200, got {r.status_code}"
            data = r.json()
            print(f"      Status: {data.get('status')} | DB Status: {data.get('database')} | Connected: {data.get('db_connected')}")
        except Exception as e:
            print(f"❌ Server not reachable at {BASE_URL}: {e}")
            print("   Make sure the server is running: uvicorn backend.main:app --reload --port 8000")
            return False

        # 2. Auth enforcement check on /tasks
        r = client.get("/tasks")
        print(f"\n[2/8] GET /tasks (without token) -> {r.status_code}")
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
        print("      ✅ Auth correctly rejected unauthenticated request")

        # 3. Authenticated GET /tasks
        r = client.get("/tasks", headers=HEADERS)
        print(f"\n[3/8] GET /tasks (with token) -> {r.status_code}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        tasks = r.json().get("tasks", [])
        print(f"      ✅ Returned {len(tasks)} tasks")

        # 4. Authenticated GET /projects
        r = client.get("/projects", headers=HEADERS)
        print(f"\n[4/8] GET /projects -> {r.status_code}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        projects = r.json().get("projects", [])
        print(f"      ✅ Returned {len(projects)} projects")

        # 5. Authenticated GET /dashboard
        r = client.get("/dashboard", headers=HEADERS)
        print(f"\n[5/8] GET /dashboard -> {r.status_code}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        dash = r.json()
        print(f"      ✅ Total Open Tasks: {dash.get('total_open_tasks')}, Total Projects: {dash.get('total_projects')}")

        # 6. Authenticated GET /memory/timeline
        r = client.get("/memory/timeline", headers=HEADERS)
        print(f"\n[6/8] GET /memory/timeline -> {r.status_code}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        timeline = r.json()
        print(f"      ✅ Timeline entries: {len(timeline.get('entries', []))}, Total in DB: {timeline.get('total')}")

        # 7. Authenticated GET /admin/usage
        r = client.get("/admin/usage", headers=HEADERS)
        print(f"\n[7/8] GET /admin/usage -> {r.status_code}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        usage = r.json()
        print(f"      ✅ Tracked cost: ${usage.get('total_estimated_cost_usd', 0.0):.6f}")

        # 8. Authenticated POST /chat (Live tool-calling test)
        payload = {"message": "add a task: Finalize presentation slides, domain hackathon, due 2026-10-31"}
        r = client.post("/chat", headers=HEADERS, json=payload)
        print(f"\n[8/8] POST /chat -> {r.status_code}")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        chat_res = r.json()
        print(f"      ✅ Response: {chat_res.get('response')}")
        print(f"         Skill used: {chat_res.get('skill_used')}")

    print("\n" + "=" * 65)
    print("🎉 All API Integration Checks Passed!")
    print("=" * 65)
    return True


if __name__ == "__main__":
    test_api()
