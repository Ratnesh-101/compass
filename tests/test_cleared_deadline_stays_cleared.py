"""
Compass — a personal deadline the user cleared must stay cleared.

The workspace calls POST /applications/prepare every time it opens. Before the fix, prepare saw an
empty target_deadline and silently re-created the automatic apply-by date (and its Timeline task).
"""

import uuid

import pytest
from httpx import AsyncClient

from backend.memory.radar import upsert_opportunity

MARKER = "deadline_cleared_by_user"
VALID_MASTER = {
    "full_name": "Deadline Tester",
    "email": "deadline@example.com",
    "skills": ["Python", "FastAPI"],
    "education": [{"institution": "Test University", "degree": "B.Tech", "end_year": 2027}],
}


def _user_headers() -> dict:
    return {"x-user-id": f"deadline-{uuid.uuid4().hex[:8]}@compass.internal"}


async def _new_opp() -> tuple[int, str]:
    company = f"Deadline Corp {uuid.uuid4().hex[:8]}"
    opp_id = await upsert_opportunity(company, "Backend Intern", f"https://deadline.test/careers/{uuid.uuid4().hex}")
    return opp_id, company


async def _prepare(client: AsyncClient, headers: dict, opp_id: int) -> dict:
    resp = await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})
    assert resp.status_code == 200
    return resp.json()


async def _apply_tasks(client: AsyncClient, headers: dict, company: str) -> list[dict]:
    resp = await client.get("/api/tasks", headers=headers)
    assert resp.status_code == 200
    return [t for t in resp.json() if t["title"].startswith("Apply:") and company in t["title"]]


async def _setup(client: AsyncClient, headers: dict) -> tuple[int, str]:
    put = await client.put("/api/career/resumes/master", headers=headers, json=VALID_MASTER)
    assert put.status_code == 200
    return await _new_opp()


@pytest.mark.asyncio
async def test_fresh_application_gets_the_automatic_deadline(client: AsyncClient):
    headers = _user_headers()
    opp_id, company = await _setup(client, headers)

    body = await _prepare(client, headers, opp_id)

    assert body["target_deadline"] is not None
    assert body["form_answers"].get("auto_deadline") == body["target_deadline"]
    assert MARKER not in body["form_answers"]
    assert len(await _apply_tasks(client, headers, company)) == 1


@pytest.mark.asyncio
async def test_cleared_deadline_is_not_restored_by_prepare(client: AsyncClient):
    headers = _user_headers()
    opp_id, company = await _setup(client, headers)
    first = await _prepare(client, headers, opp_id)
    app_id = first["id"]
    # The user also deletes the Timeline task, then empties the date.
    for task in await _apply_tasks(client, headers, company):
        assert (await client.delete(f"/api/tasks/{task['id']}", headers=headers)).status_code == 200
    assert await _apply_tasks(client, headers, company) == []

    cleared = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"clear_target_deadline": True}
    )
    assert cleared.status_code == 200
    assert cleared.json()["target_deadline"] is None
    assert cleared.json()["form_answers"].get(MARKER) is True

    again = await _prepare(client, headers, opp_id)
    third = await _prepare(client, headers, opp_id)

    assert again["id"] == app_id
    assert again["target_deadline"] is None and third["target_deadline"] is None
    assert again["form_answers"].get(MARKER) is True
    assert await _apply_tasks(client, headers, company) == []  # no second Timeline task


@pytest.mark.asyncio
async def test_clear_keeps_other_answers_and_survives_answer_edits(client: AsyncClient):
    headers = _user_headers()
    opp_id, _ = await _setup(client, headers)
    app_id = (await _prepare(client, headers, opp_id))["id"]
    await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"form_answers": {"why_us": "I like it"}})

    cleared = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"clear_target_deadline": True}
    )
    assert cleared.json()["form_answers"].get("why_us") == "I like it"

    # Saving answers again from a client that does not know the marker must not drop it.
    edited = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"form_answers": {"why_us": "Edited"}}
    )
    assert edited.status_code == 200
    assert edited.json()["form_answers"].get(MARKER) is True
    assert (await _prepare(client, headers, opp_id))["target_deadline"] is None


@pytest.mark.asyncio
async def test_new_deadline_removes_the_marker_and_is_kept(client: AsyncClient):
    headers = _user_headers()
    opp_id, _ = await _setup(client, headers)
    app_id = (await _prepare(client, headers, opp_id))["id"]
    await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"clear_target_deadline": True})

    chosen = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"target_deadline": "2031-03-15"}
    )

    assert chosen.status_code == 200
    assert chosen.json()["target_deadline"] == "2031-03-15"
    assert MARKER not in chosen.json()["form_answers"]
    after = await _prepare(client, headers, opp_id)
    assert after["target_deadline"] == "2031-03-15"
    assert MARKER not in after["form_answers"]


@pytest.mark.asyncio
async def test_other_user_cannot_read_or_clear_the_deadline(client: AsyncClient):
    owner = _user_headers()
    attacker = _user_headers()
    opp_id, _ = await _setup(client, owner)
    first = await _prepare(client, owner, opp_id)
    app_id, deadline = first["id"], first["target_deadline"]
    assert deadline is not None

    read = await client.get(f"/api/career/applications/{app_id}", headers=attacker)
    clear = await client.patch(
        f"/api/career/applications/{app_id}", headers=attacker, json={"clear_target_deadline": True}
    )

    assert read.status_code == 404
    assert clear.status_code == 404
    after = (await client.get(f"/api/career/applications/{app_id}", headers=owner)).json()
    assert after["target_deadline"] == deadline
    assert MARKER not in after["form_answers"]
