"""
Verify that backend/main.py fulfills docs/api_contract.md and boots cleanly.
Uses FastAPI TestClient with httpx.
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)
TOKEN = "dev-token"
AUTH_HEADER = {"Authorization": f"Bearer {TOKEN}"}

def run_tests():
    print("[*] Testing Compass API Shell against api_contract.md...")

    # 1. Health check (unauthenticated)
    res = client.get("/health")
    assert res.status_code == 200, f"Health check failed: {res.status_code}"
    body = res.json()
    assert body["status"] == "ok"
    assert "db_connected" in body
    assert "database" in body
    print("  ✅ GET /health (unauthenticated) -> 200 OK")

    # 2. Auth check (unauthorized requests return 401)
    res = client.get("/dashboard")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print("  ✅ GET /dashboard (unauthenticated) -> 401 Unauthorized")

    # 3. POST /chat
    res = client.post("/chat", headers=AUTH_HEADER, json={"message": "Hello Compass!"})
    assert res.status_code == 200, f"POST /chat failed: {res.status_code}"
    body = res.json()
    assert "conversation_id" in body
    assert "response" in body
    assert body["skill_used"] == "chat"
    print("  ✅ POST /chat -> 200 OK")

    conv_id = body["conversation_id"]

    # 4. GET /conversations/{id}/messages
    res = client.get(f"/conversations/{conv_id}/messages", headers=AUTH_HEADER)
    assert res.status_code == 200, f"GET messages failed: {res.status_code}"
    body = res.json()
    assert "messages" in body
    assert len(body["messages"]) >= 2
    print("  ✅ GET /conversations/{id}/messages -> 200 OK")

    # 5. GET /projects
    res = client.get("/projects", headers=AUTH_HEADER)
    assert res.status_code == 200
    body = res.json()
    assert "projects" in body
    assert len(body["projects"]) > 0
    print("  ✅ GET /projects -> 200 OK")

    # 6. GET /tasks
    res = client.get("/tasks?domain=hackathon", headers=AUTH_HEADER)
    assert res.status_code == 200
    body = res.json()
    assert "tasks" in body
    print("  ✅ GET /tasks -> 200 OK")

    # 7. GET /dashboard
    res = client.get("/dashboard", headers=AUTH_HEADER)
    assert res.status_code == 200
    body = res.json()
    assert "domains" in body
    assert "hackathon" in body["domains"]
    assert "coursework" in body["domains"]
    assert "code" in body["domains"]
    assert "general" in body["domains"]
    assert "total_open_tasks" in body
    assert "total_projects" in body
    print("  ✅ GET /dashboard -> 200 OK")

    # 8. GET /memory/timeline
    res = client.get("/memory/timeline", headers=AUTH_HEADER)
    assert res.status_code == 200
    body = res.json()
    assert "entries" in body
    assert "total" in body
    assert "has_more" in body
    print("  ✅ GET /memory/timeline -> 200 OK")

    # 9. GET /admin/usage
    res = client.get("/admin/usage", headers=AUTH_HEADER)
    assert res.status_code == 200
    body = res.json()
    assert "total_input_tokens" in body
    assert "by_model" in body
    print("  ✅ GET /admin/usage -> 200 OK")

    print("\n🎉 ALL API CONTRACT ENDPOINTS VALIDATED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
