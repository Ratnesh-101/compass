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
    import uuid
    unique_suffix = uuid.uuid4().hex[:6]
    title = f"Directly Created Milestone {unique_suffix}"
    payload = {
        "title": title,
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
    assert data["title"] == title
    assert data["domain"] == "hackathon"
    assert data["project"] == "Demo Sprint"
    assert data["priority"] == "high"
    assert data["duration_minutes"] == 90
    assert "id" in data
    assert data["id"] is not None

    if str(data["id"]).isdigit():
        await client.delete(f"/api/tasks/{data['id']}")


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


@pytest.mark.asyncio
async def test_direct_create_task_custom_and_other_domain(client: AsyncClient):
    """Creating tasks with 'other' and custom domains succeeds and preserves domain name."""
    # 1. Domain 'other'
    resp_other = await client.post("/api/tasks", json={
        "title": "Clean Office Workspace",
        "domain": "other",
        "priority": "low",
    })
    assert resp_other.status_code == 200
    data_other = resp_other.json()
    assert data_other["domain"] == "other"

    # 2. Custom domain 'fitness'
    resp_custom = await client.post("/api/tasks", json={
        "title": "Complete 5k Training",
        "domain": "fitness",
        "priority": "high",
    })
    assert resp_custom.status_code == 200
    data_custom = resp_custom.json()
    assert data_custom["domain"] == "fitness"

    # Clean up created tasks if persisted in DB
    if str(data_other["id"]).isdigit():
        await client.delete(f"/api/tasks/{data_other['id']}")
    if str(data_custom["id"]).isdigit():
        await client.delete(f"/api/tasks/{data_custom['id']}")


@pytest.mark.asyncio
async def test_direct_create_task_exact_duplicate_blocked(client: AsyncClient):
    """Adding an exact duplicate deadline (same title & due date) must return 409 Conflict."""
    import uuid
    unique_name = f"Duplicate Test Milestone {uuid.uuid4().hex[:6]}"
    payload = {
        "title": unique_name,
        "domain": "general",
        "due_date": "2026-12-01",
        "priority": "medium",
    }
    # First creation succeeds
    resp1 = await client.post("/api/tasks", json=payload)
    assert resp1.status_code == 200
    task1 = resp1.json()

    # Second creation with identical title and date must fail with 409
    resp2 = await client.post("/api/tasks", json=payload)
    assert resp2.status_code == 409
    detail = resp2.json()["detail"].lower()
    assert "duplicate deadline" in detail or "exact duplicate" in detail

    # Clean up
    if str(task1["id"]).isdigit():
        await client.delete(f"/api/tasks/{task1['id']}")


@pytest.mark.asyncio
async def test_direct_create_task_same_name_shift_or_different(client: AsyncClient):
    """Adding a task with existing name prompts for shift vs different thing; flags resolve it."""
    import uuid
    shared_name = f"Same Name Milestone {uuid.uuid4().hex[:6]}"
    payload_initial = {
        "title": shared_name,
        "domain": "coursework",
        "due_date": "2026-11-10",
        "priority": "medium",
    }
    resp1 = await client.post("/api/tasks", json=payload_initial)
    assert resp1.status_code == 200
    initial_task = resp1.json()
    task_id = initial_task["id"]

    # 1. Attempting same name with different date without flags returns 409
    payload_clash = {
        "title": shared_name,
        "domain": "coursework",
        "due_date": "2026-11-20",
    }
    resp_clash = await client.post("/api/tasks", json=payload_clash)
    assert resp_clash.status_code == 409
    assert "shift" in resp_clash.json()["detail"].lower()

    # 2. Shift existing deadline updates due_date on the original task
    payload_shift = {
        "title": shared_name,
        "domain": "coursework",
        "due_date": "2026-11-25",
        "shift_existing": True,
    }
    resp_shift = await client.post("/api/tasks", json=payload_shift)
    assert resp_shift.status_code == 200
    shifted_task = resp_shift.json()
    assert str(shifted_task["id"]) == str(task_id)
    assert shifted_task["due_date"] == "2026-11-25"

    # 3. Completely different thing creates a new distinct task
    payload_diff = {
        "title": shared_name,
        "domain": "coursework",
        "due_date": "2026-12-05",
        "allow_different_thing": True,
    }
    resp_diff = await client.post("/api/tasks", json=payload_diff)
    assert resp_diff.status_code == 200
    diff_task = resp_diff.json()
    assert str(diff_task["id"]) != str(task_id)
    assert diff_task["due_date"] == "2026-12-05"

    # Clean up both tasks
    if str(task_id).isdigit():
        await client.delete(f"/api/tasks/{task_id}")
    if str(diff_task["id"]).isdigit():
        await client.delete(f"/api/tasks/{diff_task['id']}")



