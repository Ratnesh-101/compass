"""Compass's own bookkeeping in form_answers must not knock an approved application back to review.

Clearing the personal deadline stores an internal marker in form_answers. That is not content the user
reviewed, so it must not invalidate an approval; a real change to an answer still must.
"""

import uuid

import pytest
from httpx import AsyncClient

from backend.memory.career import reviewed_answers, update_career_application
from backend.memory.radar import upsert_opportunity

APPROVED = "APPROVED_FOR_SUBMISSION"
READY = "READY_FOR_REVIEW"
VALID_MASTER = {
    "full_name": "Marker Tester",
    "email": "marker@example.com",
    "skills": ["Python"],
    "education": [{"institution": "Test University", "degree": "B.Tech", "end_year": 2027}],
}


def test_reviewed_answers_ignores_only_internal_markers():
    assert reviewed_answers({"why": "x", "auto_deadline": "2026-12-01", "deadline_cleared_by_user": True}) == {"why": "x"}
    assert reviewed_answers('{"why": "x", "auto_deadline": "d"}') == {"why": "x"}
    assert reviewed_answers(None) == {}
    assert reviewed_answers("not json") == {}
    assert reviewed_answers({"why": "x"}) != reviewed_answers({"why": "y"})


async def _approved_application(client: AsyncClient, headers: dict) -> int:
    assert (await client.put("/api/career/resumes/master", headers=headers, json=VALID_MASTER)).status_code == 200
    opp_id = await upsert_opportunity(
        f"Marker Corp {uuid.uuid4().hex[:8]}", "Backend Intern", f"https://marker.test/careers/{uuid.uuid4().hex}"
    )
    prep = await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})
    assert prep.status_code == 200
    app_id = prep.json()["id"]
    updated = await update_career_application(app_id, headers["x-user-id"], {"status": APPROVED})
    assert updated is not None and updated.status.value == APPROVED
    return app_id


async def _status(client: AsyncClient, headers: dict, app_id: int) -> str:
    resp = await client.get("/api/career/applications", headers=headers)
    assert resp.status_code == 200
    return next(a for a in resp.json() if a["id"] == app_id)["status"]


@pytest.mark.asyncio
async def test_clearing_the_deadline_keeps_an_approved_application_approved(client: AsyncClient):
    headers = {"x-user-id": f"marker-{uuid.uuid4().hex[:8]}@compass.internal"}
    app_id = await _approved_application(client, headers)

    resp = await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"clear_target_deadline": True})

    assert resp.status_code == 200
    assert (resp.json()["form_answers"] or {}).get("deadline_cleared_by_user") is True
    assert await _status(client, headers, app_id) == APPROVED


@pytest.mark.asyncio
async def test_a_real_answer_change_still_invalidates_the_approval(client: AsyncClient):
    headers = {"x-user-id": f"marker-{uuid.uuid4().hex[:8]}@compass.internal"}
    app_id = await _approved_application(client, headers)

    resp = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"form_answers": {"why_this_role": "A new claim after approval."}}
    )

    assert resp.status_code == 200
    assert await _status(client, headers, app_id) == READY


@pytest.mark.asyncio
async def test_a_cover_letter_change_still_invalidates_the_approval(client: AsyncClient):
    headers = {"x-user-id": f"marker-{uuid.uuid4().hex[:8]}@compass.internal"}
    app_id = await _approved_application(client, headers)

    resp = await client.post(
        f"/api/career/applications/{app_id}/cover-letter", headers=headers, json={"cover_letter": "Changed after approval."}
    )

    assert resp.status_code == 200
    assert await _status(client, headers, app_id) == READY
