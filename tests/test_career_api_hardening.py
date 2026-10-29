"""
Compass — Career API hardening regression tests.

Covers batch approval status guards, route ordering, status-transition guards on
mark-applied / track-external, opportunity existence checks, error-detail leakage,
cover-letter input validation, and prepare-without-downgrade.
"""

import uuid

import pytest
from httpx import AsyncClient

from backend.memory.radar import upsert_opportunity

ATTEST = {
    "attestation_confirmed": True,
    "work_auth_confirmed": True,
    "legal_statements_accepted": True,
}


async def _guest_headers(client: AsyncClient) -> dict:
    resp = await client.post("/api/guest/session")
    assert resp.status_code == 200
    return {"x-guest-token": resp.json()["guest_token"]}


async def _new_opportunity() -> int:
    return await upsert_opportunity(
        "Hardening Corp",
        "Backend Intern",
        f"https://hardening.test/careers/{uuid.uuid4().hex}",
    )


async def _seed_valid_master(client: AsyncClient, headers: dict) -> None:
    """A master with real identity + education, so prepared resumes pass validation (READY_FOR_REVIEW)."""
    resp = await client.put(
        "/api/career/resumes/master",
        headers=headers,
        json={
            "full_name": "Hardening Tester",
            "email": "hardening@example.com",
            "skills": ["Python", "FastAPI"],
            "education": [{"institution": "Test University", "degree": "B.Tech", "end_year": 2027}],
        },
    )
    assert resp.status_code == 200


async def _new_app(client: AsyncClient, headers: dict) -> tuple[int, int]:
    await _seed_valid_master(client, headers)
    opp_id = await _new_opportunity()
    resp = await client.post(f"/api/career/applications/{opp_id}", headers=headers)
    assert resp.status_code == 200
    return opp_id, resp.json()["id"]


# 1. Batch approval guards -------------------------------------------------

@pytest.mark.asyncio
async def test_reapproving_submitted_batch_is_rejected(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id, app_id = await _new_app(client, headers)
    patch = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"status": "READY_FOR_APPROVAL"}
    )
    assert patch.status_code == 200
    prep = await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})
    batch_id = prep.json()["batch_id"]
    first = await client.post(f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id})
    assert first.status_code == 200
    sub = await client.post(f"/api/career/batches/{batch_id}/submit", headers=headers, json={"batch_id": batch_id})
    assert sub.status_code == 200
    before = (await client.get(f"/api/career/batches/{batch_id}", headers=headers)).json()

    again = await client.post(f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id})

    assert again.status_code == 409
    after = (await client.get(f"/api/career/batches/{batch_id}", headers=headers)).json()
    assert after["status"] == before["status"] != "APPROVED"
    assert after["approval_token"] == before["approval_token"]


@pytest.mark.asyncio
async def test_batch_approval_does_not_reset_submitted_application(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id, app_id = await _new_app(client, headers)
    prep = await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})
    batch_id = prep.json()["batch_id"]
    applied = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)
    assert applied.status_code == 200

    approve = await client.post(f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id})

    assert approve.status_code == 200
    app = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert app["status"] == "SUBMITTED"


# 2. Route ordering ---------------------------------------------------------

@pytest.mark.asyncio
async def test_original_documents_route_not_shadowed_by_resume_id(client: AsyncClient):
    headers = await _guest_headers(client)
    resp = await client.get("/api/career/resumes/original-documents", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


# 3. Status transition guards -----------------------------------------------

@pytest.mark.asyncio
async def test_mark_applied_and_track_external_reject_withdrawn(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id, app_id = await _new_app(client, headers)
    w = await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"status": "WITHDRAWN"})
    assert w.status_code == 200

    mark = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)
    track = await client.post(
        "/api/career/track-external-application", headers=headers, params={"opportunity_id": opp_id}
    )

    assert mark.status_code == 409
    assert track.status_code == 409
    app = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert app["status"] == "WITHDRAWN"


@pytest.mark.asyncio
async def test_mark_applied_is_idempotent_and_keeps_submitted_at(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id, app_id = await _new_app(client, headers)
    first = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)
    assert first.status_code == 200
    second = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)
    third = await client.post(
        "/api/career/track-external-application", headers=headers, params={"opportunity_id": opp_id}
    )

    assert second.status_code == 200 and third.status_code == 200
    assert second.json()["submitted_at"] == first.json()["submitted_at"]
    assert third.json()["submitted_at"] == first.json()["submitted_at"]


@pytest.mark.asyncio
async def test_mark_applied_rejects_interview_stage(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id, app_id = await _new_app(client, headers)
    assert (await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)).status_code == 200
    for st in ("INTERVIEW",):
        r = await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"status": st})
        assert r.status_code == 200

    mark = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)

    assert mark.status_code == 409
    app = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert app["status"] == "INTERVIEW"


# 4. Opportunity existence / batch input caps ---------------------------------

@pytest.mark.asyncio
async def test_track_external_unknown_opportunity_returns_404(client: AsyncClient):
    headers = await _guest_headers(client)
    resp = await client.post(
        "/api/career/track-external-application", headers=headers, params={"opportunity_id": 987654321}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_prepare_unknown_opportunity_returns_404(client: AsyncClient):
    headers = await _guest_headers(client)
    resp = await client.post(
        "/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [987654321]}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_batch_prepare_dedupes_and_caps_opportunity_ids(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id = await _new_opportunity()
    dup = await client.post(
        "/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id, opp_id]}
    )
    assert dup.status_code == 200
    assert dup.json()["total_count"] == 1

    too_many = await client.post(
        "/api/career/batches/prepare", headers=headers, json={"opportunity_ids": list(range(1, 200))}
    )
    assert too_many.status_code == 422


# 5. Error detail leakage ------------------------------------------------------

@pytest.mark.asyncio
async def test_submit_failure_does_not_leak_internal_error(client: AsyncClient, monkeypatch):
    from backend.routers import career as career_router

    async def boom(*args, **kwargs):
        raise RuntimeError("postgres://secret-dsn-leak")

    monkeypatch.setattr(career_router, "execute_batch_submission", boom)
    headers = await _guest_headers(client)
    opp_id, app_id = await _new_app(client, headers)
    await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"status": "READY_FOR_APPROVAL"})
    batch_id = (
        await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})
    ).json()["batch_id"]
    assert (await client.post(f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id})).status_code == 200

    resp = await client.post(f"/api/career/batches/{batch_id}/submit", headers=headers, json={"batch_id": batch_id})

    assert resp.status_code == 500
    assert "secret-dsn-leak" not in resp.text
    batch = (await client.get(f"/api/career/batches/{batch_id}", headers=headers)).text
    assert "secret-dsn-leak" not in batch


# 6. Cover letter validation -----------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"cover_letter": None}, {"cover_letter": ["a"]}, {"cover_letter": "x" * 20001}, {}])
async def test_cover_letter_rejects_bad_input(client: AsyncClient, payload):
    headers = await _guest_headers(client)
    _, app_id = await _new_app(client, headers)
    resp = await client.post(f"/api/career/applications/{app_id}/cover-letter", headers=headers, json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cover_letter_accepts_valid_text(client: AsyncClient):
    headers = await _guest_headers(client)
    _, app_id = await _new_app(client, headers)
    resp = await client.post(
        f"/api/career/applications/{app_id}/cover-letter", headers=headers, json={"cover_letter": "Hello"}
    )
    assert resp.status_code == 200
    assert resp.json()["cover_letter"] == "Hello"


# 7. Prepare must not downgrade --------------------------------------------------

@pytest.mark.asyncio
async def test_prepare_does_not_downgrade_submitted_application(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id = await _new_opportunity()
    # Batch prepare creates a bare application with no resume attached.
    prep = await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})
    app_id = prep.json()["applications"][0]["id"]
    # SAVED cannot jump straight to SUBMITTED any more; reach a state that may be marked applied.
    assert (await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"status": "READY_FOR_REVIEW"}
    )).status_code == 200
    assert (await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)).status_code == 200

    resp = await client.post(
        "/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "SUBMITTED"
