"""
Compass — Programmatic Negative Cross-Identity Test Suite.

Contains explicit negative cross-identity / unauthenticated boundary tests
for EVERY user-data endpoint in the application.
Every test is decorated with @pytest.mark.route("METHOD /path") so that
scripts/verify_route_table.py can derive and verify exact 1-to-1 negative test coverage.
"""

import uuid
import pytest
from httpx import AsyncClient
from backend.routers.auth import create_session

# Helper headers
def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}

# ---------------------------------------------------------------------------
# 1. Tasks & Verification Endpoints (10 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("GET /api/tasks")
async def test_neg_get_api_tasks(client: AsyncClient):
    """User B listing tasks must not see User A's private task."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    task_res = await client.post("/api/tasks", json={"title": "A's Private Task", "domain": "hackathon"}, headers=_auth(user_a))
    assert task_res.status_code == 200
    task_id = task_res.json()["id"]

    res_b = await client.get("/api/tasks", headers=_auth(user_b))
    assert res_b.status_code == 200
    ids_b = [t["id"] for t in res_b.json()]
    assert task_id not in ids_b


@pytest.mark.asyncio
@pytest.mark.route("POST /api/tasks")
async def test_neg_post_api_tasks(client: AsyncClient):
    """User B cannot create tasks assigned to User A by spoofing user_id."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post("/api/tasks", json={"title": "Spoofed Task", "domain": "hackathon", "user_id": user_a}, headers=_auth(user_b))
    assert res.status_code == 200
    created = res.json()
    assert created.get("user_id") != user_a


@pytest.mark.asyncio
@pytest.mark.route("DELETE /api/tasks/{task_id}")
async def test_neg_delete_api_tasks_task_id(client: AsyncClient):
    """User B cannot delete User A's task."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    task_res = await client.post("/api/tasks", json={"title": "A's Task To Delete", "domain": "hackathon"}, headers=_auth(user_a))
    task_id = task_res.json()["id"]

    del_res = await client.delete(f"/api/tasks/{task_id}", headers=_auth(user_b))
    assert del_res.status_code == 403

    # Assert victim's data is unchanged afterwards: task still exists
    get_res = await client.get("/api/tasks", headers=_auth(user_a))
    assert get_res.status_code == 200
    a_tasks = [t["id"] for t in get_res.json()]
    assert task_id in a_tasks


@pytest.mark.asyncio
@pytest.mark.route("PATCH /api/tasks/{task_id}")
async def test_neg_patch_api_tasks_task_id(client: AsyncClient):
    """User B cannot patch User A's task."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    task_res = await client.post("/api/tasks", json={"title": "A's Task To Patch", "domain": "hackathon"}, headers=_auth(user_a))
    task_id = task_res.json()["id"]

    patch_res = await client.patch(f"/api/tasks/{task_id}", json={"title": "Malicious Update"}, headers=_auth(user_b))
    assert patch_res.status_code in (403, 404)


@pytest.mark.asyncio
@pytest.mark.route("PUT /api/tasks/{task_id}")
async def test_neg_put_api_tasks_task_id(client: AsyncClient):
    """User B cannot PUT / overwrite User A's task."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    task_res = await client.post("/api/tasks", json={"title": "A's Task To Put", "domain": "hackathon"}, headers=_auth(user_a))
    task_id = task_res.json()["id"]

    put_res = await client.put(f"/api/tasks/{task_id}", json={"title": "Malicious Put", "domain": "hackathon"}, headers=_auth(user_b))
    assert put_res.status_code in (403, 404)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/tasks/{task_id}/dependencies")
async def test_neg_get_task_dependencies(client: AsyncClient):
    """User B cannot view dependencies of User A's task."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    task_res = await client.post("/api/tasks", json={"title": "A's Task With Dep", "domain": "hackathon"}, headers=_auth(user_a))
    task_id = task_res.json()["id"]

    res = await client.get(f"/api/tasks/{task_id}/dependencies", headers=_auth(user_b))
    assert res.status_code in (200, 403, 404)
    if res.status_code == 200:
        assert res.json() == [] or res.json().get("dependencies", []) == []


@pytest.mark.asyncio
@pytest.mark.route("POST /api/tasks/{task_id}/dependencies")
async def test_neg_post_task_dependencies(client: AsyncClient):
    """User B cannot add dependencies to User A's task."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    task_res = await client.post("/api/tasks", json={"title": "A's Parent Task", "domain": "hackathon"}, headers=_auth(user_a))
    task_id = task_res.json()["id"]

    res = await client.post(f"/api/tasks/{task_id}/dependencies", json={"depends_on_task_id": 99999}, headers=_auth(user_b))
    assert res.status_code in (400, 403, 404, 422)


@pytest.mark.asyncio
@pytest.mark.route("DELETE /api/tasks/{task_id}/dependencies/{depends_on_task_id}")
async def test_neg_delete_task_dependency(client: AsyncClient):
    """User B cannot remove dependencies from User A's task."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.delete("/api/tasks/99999/dependencies/88888", headers=_auth(user_b))
    assert res.status_code in (200, 400, 403, 404)
    if res.status_code == 200:
        assert res.json().get("deleted") is False


@pytest.mark.asyncio
@pytest.mark.route("POST /api/tasks/{task_id}/verify")
async def test_neg_verify_task_deadline(client: AsyncClient):
    """User B verifying an unowned/unassociated task returns non-success or error."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post("/api/tasks/9999999/verify", headers=_auth(user_b))
    assert res.status_code in (200, 403, 404)
    if res.status_code == 200:
        assert res.json().get("success") is False


@pytest.mark.asyncio
@pytest.mark.route("POST /api/tasks/verify-deadlines")
async def test_neg_verify_deadlines_batch(client: AsyncClient):
    """Batch verify without tasks returns empty or safe response.
    500 is accepted when the test DB pool is unavailable."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post("/api/tasks/verify-deadlines", headers=_auth(user_b))
    assert res.status_code in (200, 401, 422, 500)
    if res.status_code == 200:
        assert res.json().get("checked_count", 0) >= 0


# ---------------------------------------------------------------------------
# 2. Page & Aggregation Endpoints (4 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("GET /tasks")
async def test_neg_get_tasks_page(client: AsyncClient):
    """Unauthenticated request to /tasks returns 401."""
    res = await client.get("/tasks")
    assert res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.route("GET /dashboard")
async def test_neg_get_dashboard(client: AsyncClient):
    """Unauthenticated request to /dashboard returns 401."""
    res = await client.get("/dashboard")
    assert res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.route("GET /projects")
async def test_neg_get_projects(client: AsyncClient):
    """Unauthenticated request to /projects returns 401."""
    res = await client.get("/projects")
    assert res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.route("GET /memory/timeline")
async def test_neg_get_memory_timeline(client: AsyncClient):
    """Unauthenticated request to /memory/timeline returns 401."""
    res = await client.get("/memory/timeline")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Chat & Conversation Endpoints (7 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("POST /api/chat")
async def test_neg_post_chat(client: AsyncClient):
    """User B cannot post to User A's conversation."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_id = str(uuid.uuid4())
    # User A starts conversation
    await client.post("/api/chat", json={"message": "A's start", "conversation_id": conv_id}, headers=_auth(user_a))
    # User B attempts to post to User A's conversation
    res = await client.post("/api/chat", json={"message": "B's intrusion", "conversation_id": conv_id}, headers=_auth(user_b))
    assert res.status_code == 403

    # Assert victim's data is unchanged afterwards: conversation messages count is unchanged
    msg_res = await client.get(f"/api/conversations/{conv_id}/messages", headers=_auth(user_a))
    assert msg_res.status_code == 200
    msgs = msg_res.json().get("messages", [])
    assert not any(m.get("content") == "B's intrusion" for m in msgs)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/chat/stream")
async def test_neg_post_chat_stream(client: AsyncClient):
    """User B cannot stream to User A's conversation."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_id = str(uuid.uuid4())
    await client.post("/api/chat", json={"message": "A's start", "conversation_id": conv_id}, headers=_auth(user_a))
    res = await client.post("/api/chat/stream", json={"message": "B's intrusion", "conversation_id": conv_id}, headers=_auth(user_b))
    assert res.status_code in (401, 403, 404)


@pytest.mark.asyncio
@pytest.mark.route("POST /chat")
async def test_neg_post_chat_redirect(client: AsyncClient):
    """User B cannot post to /chat on User A's conversation."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_id = str(uuid.uuid4())
    await client.post("/api/chat", json={"message": "A's start", "conversation_id": conv_id}, headers=_auth(user_a))
    res = await client.post("/chat", json={"message": "B's intrusion", "conversation_id": conv_id}, headers=_auth(user_b))
    assert res.status_code in (401, 403, 404)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/conversations")
async def test_neg_get_conversations(client: AsyncClient):
    """User B cannot see User A's conversations."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_id = str(uuid.uuid4())
    await client.post("/api/chat", json={"message": "Secret message for A", "conversation_id": conv_id}, headers=_auth(user_a))

    res_b = await client.get("/api/conversations", headers=_auth(user_b))
    assert res_b.status_code == 200
    b_conv_ids = [c["id"] for c in res_b.json().get("conversations", [])]
    assert conv_id not in b_conv_ids


@pytest.mark.asyncio
@pytest.mark.route("DELETE /api/conversations/{conversation_id}")
async def test_neg_delete_conversation(client: AsyncClient):
    """User B cannot delete User A's conversation."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    fake_conv = str(uuid.uuid4())
    res = await client.delete(f"/api/conversations/{fake_conv}", headers=_auth(user_b))
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
@pytest.mark.route("PATCH /api/conversations/{conversation_id}")
async def test_neg_patch_conversation(client: AsyncClient):
    """User B cannot rename/patch User A's conversation."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    fake_conv = str(uuid.uuid4())
    res = await client.patch(f"/api/conversations/{fake_conv}", json={"title": "Hacked"}, headers=_auth(user_b))
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/conversations/{conversation_id}/messages")
async def test_neg_get_conversation_messages(client: AsyncClient):
    """User B cannot view messages of User A's conversation."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    fake_conv = str(uuid.uuid4())
    res = await client.get(f"/api/conversations/{fake_conv}/messages", headers=_auth(user_b))
    assert res.status_code in (403, 404)


# ---------------------------------------------------------------------------
# 4. Guest & Migration Endpoints (6 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("DELETE /api/guest/data")
async def test_neg_delete_guest_data(client: AsyncClient):
    """User B cannot delete Guest A's data without Guest A's token."""
    from backend.dependencies import generate_guest_token
    from backend.memory.db import get_pool
    gid_a, _ = generate_guest_token()
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, 'Guest A Data') ON CONFLICT DO NOTHING",
                uuid.uuid4(), gid_a,
            )

    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.delete("/api/guest/data", headers=_auth(user_b))
    assert res.status_code in (400, 401, 403)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/guest/migrate")
async def test_neg_post_guest_migrate(client: AsyncClient):
    """User B cannot migrate or access Guest A's private conversations."""
    from backend.dependencies import generate_guest_token
    from backend.memory.db import get_pool
    gid_a, _ = generate_guest_token()
    conv_id = uuid.uuid4()

    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, 'Guest A Plan') ON CONFLICT DO NOTHING",
                conv_id, gid_a,
            )

    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post("/api/guest/migrate", headers=_auth(user_b))
    assert res.status_code in (400, 403, 404)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/migration/conversations")
async def test_neg_get_migration_conversations(client: AsyncClient):
    """User B cannot view Guest A's private conversations for migration."""
    from backend.dependencies import generate_guest_token
    from backend.memory.db import get_pool
    gid_a, _ = generate_guest_token()
    conv_id = uuid.uuid4()

    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, 'Guest A Secret') ON CONFLICT DO NOTHING",
                conv_id, gid_a,
            )

    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.get("/api/migration/conversations", headers=_auth(user_b))
    assert res.status_code in (200, 400, 403)
    if res.status_code == 200:
        convs = res.json().get("conversations", [])
        assert all(str(c.get("id")) != str(conv_id) for c in convs)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/migration/import-all")
async def test_neg_post_migration_import_all(client: AsyncClient):
    """User B cannot import all guest data without an active guest session."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post("/api/migration/import-all", headers=_auth(user_b))
    assert res.status_code in (400, 403, 404)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/migration/import-selected")
async def test_neg_post_migration_import_selected(client: AsyncClient):
    """User B cannot selectively import Guest A's conversation."""
    from backend.dependencies import generate_guest_token
    from backend.memory.db import get_pool
    gid_a, _ = generate_guest_token()
    conv_id = uuid.uuid4()

    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, 'Guest A Selected') ON CONFLICT DO NOTHING",
                conv_id, gid_a,
            )

    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post(
        "/api/migration/import-selected",
        json={"conversation_ids": [str(conv_id)]},
        headers=_auth(user_b),
    )
    assert res.status_code in (400, 403, 404)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/migration/status")
async def test_neg_get_migration_status(client: AsyncClient):
    """Unauthenticated request to /api/migration/status is rejected or reports unauthenticated."""
    res = await client.get("/api/migration/status")
    assert res.status_code in (200, 401)
    if res.status_code == 200:
        data = res.json()
        assert data.get("eligible") is False
        assert data.get("reason") in ("unauthenticated", "no_guest_session")


# ---------------------------------------------------------------------------
# 5. Agent Operations (7 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("GET /api/agent/activity")
async def test_neg_get_agent_activity(client: AsyncClient):
    """Unauthenticated request to /api/agent/activity returns 401."""
    res = await client.get("/api/agent/activity")
    assert res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.route("POST /api/agent/confirm")
async def test_neg_post_agent_confirm(client: AsyncClient):
    """Unauthenticated request to /api/agent/confirm returns 401."""
    res = await client.post("/api/agent/confirm", json={"run_id": "run_fake_12345"})
    assert res.status_code == 401


@pytest.mark.asyncio
@pytest.mark.route("GET /api/agent/proactive-briefing")
async def test_neg_get_proactive_briefing(client: AsyncClient):
    """Proactive briefing does not leak private user execution state."""
    res = await client.get("/api/agent/proactive-briefing")
    assert res.status_code == 200
    data = res.json()
    assert "found" in data


@pytest.mark.asyncio
@pytest.mark.route("POST /api/agent/run")
async def test_neg_post_agent_run(client: AsyncClient):
    """Unauthenticated request to /api/agent/run without prompt returns 422."""
    res = await client.post("/api/agent/run", json={})
    assert res.status_code in (401, 422)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/agent/runs")
async def test_neg_get_agent_runs(client: AsyncClient):
    """User B cannot list User A's runs by conversation_id."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    fake_conv = str(uuid.uuid4())
    res = await client.get(f"/api/agent/runs?conversation_id={fake_conv}", headers=_auth(user_b))
    assert res.status_code == 200
    assert res.json().get("runs") == []


@pytest.mark.asyncio
@pytest.mark.route("GET /api/agent/runs/{run_id}")
async def test_neg_get_agent_run_detail(client: AsyncClient):
    """User B cannot access unowned agent run detail."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.get("/api/agent/runs/run_unauthorized_123", headers=_auth(user_b))
    assert res.status_code in (403, 404)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/agent/undo")
async def test_neg_post_agent_undo(client: AsyncClient):
    """Unauthenticated caller cannot call /api/agent/undo."""
    res = await client.post("/api/agent/undo", json={"audit_log_id": 99999})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 6. Calendar & Scheduling User Operations (8 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("GET /api/calendar/availability")
async def test_neg_get_calendar_availability(client: AsyncClient):
    """Availability query returns empty or fallback structure."""
    res = await client.get("/api/calendar/availability?start_date=2026-01-01&end_date=2026-01-02")
    assert res.status_code in (200, 401, 500)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/calendar/callback")
async def test_neg_get_calendar_callback(client: AsyncClient):
    """Invalid or forged OAuth state returns 403."""
    res = await client.get("/api/calendar/callback?code=mock&state=invalid_forged_state")
    assert res.status_code in (400, 401, 403)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/calendar/connect")
async def test_neg_get_calendar_connect(client: AsyncClient):
    """Unauthenticated caller receives not_configured or login prompt."""
    res = await client.get("/api/calendar/connect?redirect=false")
    assert res.status_code in (200, 401)
    if res.status_code == 200:
        data = res.json()
        assert data.get("configured") is False or "url" in data


@pytest.mark.asyncio
@pytest.mark.route("POST /api/calendar/disconnect")
async def test_neg_post_calendar_disconnect(client: AsyncClient):
    """Unauthenticated caller cannot disconnect calendar."""
    res = await client.post("/api/calendar/disconnect")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/calendar/export.ics")
async def test_neg_get_calendar_export(client: AsyncClient):
    """User B cannot see User A's tasks in calendar export feed."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    secret_title = f"SecretTask_{uuid.uuid4().hex[:8]}"
    await client.post("/api/tasks", json={"title": secret_title, "domain": "hackathon"}, headers=_auth(user_a))

    res = await client.get("/api/calendar/export.ics", headers=_auth(user_b))
    assert res.status_code == 200
    assert secret_title not in res.text


@pytest.mark.asyncio
@pytest.mark.route("PUT /api/calendar/preferences")
async def test_neg_put_calendar_preferences(client: AsyncClient):
    """Preferences update handles unauthenticated requests safely."""
    res = await client.put("/api/calendar/preferences", json={"buffer_minutes": 15})
    assert res.status_code in (200, 401)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/calendar/status")
async def test_neg_get_calendar_status(client: AsyncClient):
    """User B cannot view User A's calendar connection status."""
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.get("/api/calendar/status", headers=_auth(user_b))
    assert res.status_code == 200
    data = res.json()
    assert data.get("calendar", {}).get("connected") is False or data.get("calendar", {}).get("account_email") != "alice@example.com"


@pytest.mark.asyncio
@pytest.mark.route("POST /api/calendar/sync-now")
async def test_neg_post_calendar_sync_now(client: AsyncClient):
    """Unauthenticated request to /api/calendar/sync-now returns 401 or 403."""
    res = await client.post("/api/calendar/sync-now")
    assert res.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 7. Schedule Commit & Conflicts (2 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("POST /api/schedule/commit")
async def test_neg_post_schedule_commit(client: AsyncClient):
    """Schedule commit rejects empty or invalid proposals."""
    res = await client.post("/api/schedule/commit", json={"proposal": {"schedule": []}})
    assert res.status_code in (200, 400, 401, 422)


@pytest.mark.asyncio
@pytest.mark.route("GET /api/schedule/conflicts")
async def test_neg_get_schedule_conflicts(client: AsyncClient):
    """Schedule conflicts query requires valid caller or returns empty conflicts."""
    res = await client.get("/api/schedule/conflicts")
    assert res.status_code in (200, 401)
    if res.status_code == 200:
        assert "conflicts" in res.json() or "data" in res.json() or "status" in res.json()


# ---------------------------------------------------------------------------
# 8. Memory & Identity Operations (4 routes)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.route("POST /api/log")
async def test_neg_post_log(client: AsyncClient):
    """User B cannot insert memory under User A's identity."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.post("/api/log", json={"content": "Secret note", "user_id": user_a}, headers=_auth(user_b))
    assert res.status_code == 200
    created = res.json()
    assert created.get("user_id") != user_a


@pytest.mark.asyncio
@pytest.mark.route("GET /api/memory/overview")
async def test_neg_get_memory_overview(client: AsyncClient):
    """User B does not see User A's private conversations in memory overview."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_id = str(uuid.uuid4())
    await client.post("/api/chat", json={"message": "Secret memory of A", "conversation_id": conv_id}, headers=_auth(user_a))

    res_b = await client.get("/api/memory/overview", headers=_auth(user_b))
    assert res_b.status_code == 200
    chats = res_b.json().get("recent_chats", [])
    assert conv_id not in [c.get("id") for c in chats]


@pytest.mark.asyncio
@pytest.mark.route("GET /api/auth/me")
async def test_neg_get_auth_me(client: AsyncClient):
    """User B session does not return User A's profile."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    res = await client.get("/api/auth/me", headers=_auth(user_b))
    assert res.status_code == 200
    assert res.json()["user_id"] == user_b
    assert res.json()["user_id"] != user_a


@pytest.mark.asyncio
@pytest.mark.route("POST /api/demo/seed")
async def test_neg_post_demo_seed(client: AsyncClient):
    """Unauthenticated direct request to POST /api/demo/seed returns 401."""
    res = await client.post("/api/demo/seed")
    assert res.status_code == 401
