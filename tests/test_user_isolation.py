"""
Tests for account selection, user memory isolation, and Google OAuth account prompt.
"""

import pytest
from httpx import AsyncClient
from backend.services.oauth import generate_google_oauth_url, is_google_oauth_configured


@pytest.mark.asyncio
async def test_oauth_prompt_has_select_account():
    """Verify that Google OAuth authorization URL forces account selection so users aren't auto-logged into the wrong Google account."""
    url = generate_google_oauth_url(login_hint="kumarinandan911@gmail.com")
    assert "prompt=select_account" in url
    assert "login_hint=kumarinandan911%40gmail.com" in url


@pytest.mark.asyncio
async def test_account_selection_and_task_isolation(client: AsyncClient):
    """Verify that tasks created by User A are isolated from User B."""
    import uuid
    unique_title = f"User A Private Milestone {uuid.uuid4().hex[:6]}"
    user_a = "kumarinandan911@gmail.com"
    user_b = "himynameisratnesh12@gmail.com"

    # User A creates a task
    res_a = await client.post(
        "/api/tasks",
        json={"title": unique_title, "domain": "code"},
        headers={"x-user-id": user_a},
    )
    assert res_a.status_code == 200
    task_a = res_a.json()
    task_a_id = task_a["id"]

    # User B lists tasks - should NOT contain User A's task
    res_b_list = await client.get("/api/tasks", headers={"x-user-id": user_b})
    assert res_b_list.status_code == 200
    b_tasks = res_b_list.json()
    assert not any(str(t.get("id")) == str(task_a_id) for t in b_tasks)

    # User A lists tasks - should contain their task
    res_a_list = await client.get("/api/tasks", headers={"x-user-id": user_a})
    assert res_a_list.status_code == 200
    a_tasks = res_a_list.json()
    assert any(str(t.get("id")) == str(task_a_id) for t in a_tasks)

    # Cleanup
    await client.delete(f"/api/tasks/{task_a_id}", headers={"x-user-id": user_a})


@pytest.mark.asyncio
async def test_select_account_endpoint(client: AsyncClient):
    """Test switching active account via POST /api/auth/select-account."""
    target = "kumarinandan911@gmail.com"
    res = await client.post("/api/auth/select-account", json={"email": target})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["user_id"] == target
    assert data["email"] == target


@pytest.mark.asyncio
async def test_unconfigured_oauth_endpoint(client: AsyncClient):
    """When GOOGLE_CLIENT_ID is not configured, /api/calendar/connect returns status: not_configured."""
    if not is_google_oauth_configured():
        res = await client.get("/api/calendar/connect?redirect=false")
        assert res.status_code == 200
        data = res.json()
        assert data["configured"] is False
        assert data["status"] == "not_configured"
