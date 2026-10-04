"""
Tests for account selection, user memory isolation, and Google OAuth account prompt.
"""

import pytest
from httpx import AsyncClient
from backend.services.oauth import generate_google_oauth_url, is_google_oauth_configured


@pytest.mark.asyncio
async def test_oauth_prompt_has_select_account():
    """Verify that Google OAuth authorization URL forces account selection so users aren't auto-logged into the wrong Google account."""
    url = generate_google_oauth_url(login_hint="alice@example.com")
    assert "prompt=select_account" in url
    assert "login_hint=alice%40example.com" in url


@pytest.mark.asyncio
async def test_account_selection_and_task_isolation(client: AsyncClient):
    """Verify that tasks created by User A are isolated from User B."""
    import uuid
    from backend.routers.auth import create_session

    unique_title = f"User A Private Milestone {uuid.uuid4().hex[:6]}"
    user_a = "alice@example.com"
    user_b = "bob@example.com"
    auth_a = {"Authorization": f"Bearer {create_session(user_a)}"}
    auth_b = {"Authorization": f"Bearer {create_session(user_b)}"}

    # User A creates a task
    res_a = await client.post(
        "/api/tasks",
        json={"title": unique_title, "domain": "code"},
        headers=auth_a,
    )
    assert res_a.status_code == 200
    task_a = res_a.json()
    task_a_id = task_a["id"]

    # User B lists tasks - should NOT contain User A's task
    res_b_list = await client.get("/api/tasks", headers=auth_b)
    assert res_b_list.status_code == 200
    b_tasks = res_b_list.json()
    assert not any(str(t.get("id")) == str(task_a_id) for t in b_tasks)

    # User A lists tasks - should contain their task
    res_a_list = await client.get("/api/tasks", headers=auth_a)
    assert res_a_list.status_code == 200
    a_tasks = res_a_list.json()
    assert any(str(t.get("id")) == str(task_a_id) for t in a_tasks)

    # Cleanup
    await client.delete(f"/api/tasks/{task_a_id}", headers=auth_a)


@pytest.mark.asyncio
async def test_select_account_endpoint_deleted(client: AsyncClient):
    """Verify that insecure uncredentialed POST /api/auth/select-account is deleted and returns 404."""
    target = "alice@example.com"
    res = await client.post("/api/auth/select-account", json={"email": target})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_unconfigured_oauth_endpoint(client: AsyncClient):
    """When GOOGLE_CLIENT_ID is not configured, /api/calendar/connect returns status: not_configured."""
    if not is_google_oauth_configured():
        res = await client.get("/api/calendar/connect?redirect=false")
        assert res.status_code == 200
        data = res.json()
        assert data["configured"] is False
        assert data["status"] == "not_configured"
