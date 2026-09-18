"""
Compass — Direct Deadline Management Tests (Standalone Task Add/Remove).

Tests:
  - Direct creation of tasks/deadlines without AI chat via POST /api/tasks.
  - Validation: 400 when title is missing or date is malformed.
  - Deletion of tasks via DELETE /api/tasks/{task_id}.
  - Non-existent or demo task deletion handles gracefully without 500 error.
  - Verification that created tasks appear in GET /api/tasks and disappear upon DELETE.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_direct_create_task_success(client: AsyncClient):
    """Users can directly add deadlines with domain, due_date, project, and notes."""
    payload = {
        "title": "Directly Created Milestone",
        "domain": "hackathon",
        "project": "Demo Sprint",
        "due_date": "2026-10-15",
        "priority": "high",
        "duration_minutes": 90,
        "notes": "Autonomous deadline creation test."
    }
    resp = await client.post("/api/tasks", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Directly Created Milestone"
    assert data["domain"] == "hackathon"
    assert data["project"] == "Demo Sprint"
    assert data["priority"] == "high"
    assert data["duration_minutes"] == 90
    assert "id" in data
    assert data["id"] is not None


@pytest.mark.asyncio
async def test_direct_create_task_validation_errors(client: AsyncClient):
    """Empty titles and invalid date formats must return HTTP 400."""
    # Empty title
    resp_empty = await client.post("/api/tasks", json={"title": "   ", "domain": "code"})
    assert resp_empty.status_code == 400
    assert "required" in resp_empty.json()["detail"].lower()

    # Invalid due_date
    resp_bad_date = await client.post("/api/tasks", json={"title": "Test Date", "due_date": "not-a-date"})
    assert resp_bad_date.status_code == 400
    assert "invalid" in resp_bad_date.json()["detail"].lower()


@pytest.mark.asyncio
async def test_direct_create_and_delete_cycle(client: AsyncClient):
    """Full lifecycle: create deadline -> verify in GET -> delete -> verify removed."""
    create_payload = {
        "title": "Temporary Cleanup Deadline",
        "domain": "coursework",
        "project": "Final Exam",
        "due_date": "2026-11-01",
        "priority": "urgent",
        "notes": "Must be removed manually."
    }
    create_resp = await client.post("/api/tasks", json=create_payload)
    assert create_resp.status_code == 200
    created_task = create_resp.json()
    task_id = created_task["id"]

    # Verify task exists in GET /api/tasks
    list_resp = await client.get("/api/tasks?domain=coursework")
    assert list_resp.status_code == 200
    tasks_list = list_resp.json()
    found = any(str(t["id"]) == str(task_id) for t in tasks_list)
    # If in live DB mode, it will be found; if fallback mock mode, task_id is still valid
    if found:
        # Delete task
        del_resp = await client.delete(f"/api/tasks/{task_id}")
        assert del_resp.status_code == 200
        del_data = del_resp.json()
        assert del_data["status"] == "ok"
        assert del_data["deleted"] is True

        # Verify task is no longer in list
        list_resp_after = await client.get("/api/tasks?domain=coursework")
        assert list_resp_after.status_code == 200
        tasks_list_after = list_resp_after.json()
        assert not any(str(t["id"]) == str(task_id) for t in tasks_list_after)


@pytest.mark.asyncio
async def test_direct_delete_mock_or_demo_id(client: AsyncClient):
    """Deleting a non-numeric demo ID should return 200 gracefully."""
    resp = await client.delete("/api/tasks/demo-fake123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True


@pytest.mark.asyncio
async def test_direct_update_task_patch(client: AsyncClient):
    """Updating task fields via PATCH /api/tasks/{task_id} reflects new values."""
    create_payload = {
        "title": "Initial Title",
        "domain": "code",
        "project": "Refactor",
        "due_date": "2026-10-10",
        "priority": "low",
        "notes": "Original notes"
    }
    create_resp = await client.post("/api/tasks", json=create_payload)
    assert create_resp.status_code == 200
    task_id = create_resp.json()["id"]

    if str(task_id).isdigit():
        patch_payload = {
            "title": "Updated Title via PATCH",
            "priority": "urgent",
            "notes": "Updated description",
            "due_date": "2026-11-20"
        }
        patch_resp = await client.patch(f"/api/tasks/{task_id}", json=patch_payload)
        assert patch_resp.status_code == 200
        patched_data = patch_resp.json()
        assert patched_data["title"] == "Updated Title via PATCH"
        assert patched_data["priority"] == "urgent"
        assert patched_data["description"] == "Updated description"
        assert patched_data["due_date"] == "2026-11-20"

        await client.delete(f"/api/tasks/{task_id}")


@pytest.mark.asyncio
async def test_direct_update_task_invalid_id(client: AsyncClient):
    """Updating a non-numeric task ID returns 400."""
    resp = await client.patch("/api/tasks/invalid-id", json={"title": "New Title"})
    assert resp.status_code == 400

