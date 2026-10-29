"""
Compass — regressions for handoff-kit, agent batch-submit skill, skill dedupe and input caps.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from backend.memory.career import (
    approve_application_batch,
    create_application_batch,
    get_career_application_by_id,
    get_or_create_career_application,
    update_career_application,
)
from backend.memory.radar import upsert_opportunity
from backend.models_career import CareerApplicationStatus, SubmissionResultItem
from backend.services.career_submission import compute_batch_content_hash, generate_batch_approval_token
from backend.skills.handlers import career as skill_career

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
        "Fixes Corp", "Backend Intern", f"https://fixes.test/careers/{uuid.uuid4().hex}"
    )


async def _approved_app(client: AsyncClient, headers: dict) -> tuple[int, str]:
    # Batch approval requires a validated resume + cover letter, so seed a master with real identity.
    seeded = await client.put(
        "/api/career/resumes/master",
        headers=headers,
        json={
            "full_name": "Fixes Tester",
            "email": "fixes@example.com",
            "skills": ["Python"],
            "education": [{"institution": "Test University", "degree": "B.Tech", "end_year": 2027}],
        },
    )
    assert seeded.status_code == 200
    opp_id = await _new_opportunity()
    app_id = (await client.post(f"/api/career/applications/{opp_id}", headers=headers)).json()["id"]
    await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"status": "READY_FOR_APPROVAL"}
    )
    prep = await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})
    batch_id = prep.json()["batch_id"]
    ok = await client.post(
        f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id}
    )
    assert ok.status_code == 200
    return app_id, batch_id


# 1. handoff-kit GET must not revoke approval ------------------------------------

@pytest.mark.asyncio
async def test_handoff_kit_get_does_not_revoke_approved_application(client: AsyncClient):
    headers = await _guest_headers(client)
    app_id, batch_id = await _approved_app(client, headers)
    before = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert before["status"] == "APPROVED_FOR_SUBMISSION"

    kit = await client.get(f"/api/career/applications/{app_id}/handoff-kit", headers=headers)

    assert kit.status_code == 200
    after = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert after["status"] == "APPROVED_FOR_SUBMISSION"
    batch = (await client.get(f"/api/career/batches/{batch_id}", headers=headers)).json()
    assert batch["status"] == "APPROVED"


# 2. agent skill submit enforces claim / lock / validation -------------------------

async def _approved_batch_for(user_id: str) -> str:
    opp_id = await _new_opportunity()
    app = await get_or_create_career_application(user_id, opp_id)
    batch_id = await create_application_batch(user_id, [app.id])
    fresh = await get_career_application_by_id(app.id, user_id)
    token = generate_batch_approval_token(
        user_id=user_id,
        batch_id=batch_id,
        application_ids=[app.id],
        content_hash=compute_batch_content_hash([fresh.model_dump()]),
        expires_in_seconds=3600,
    )
    assert await approve_application_batch(batch_id, user_id, token)
    return batch_id


@pytest.mark.asyncio
async def test_skill_submit_concurrent_calls_execute_once(client: AsyncClient, monkeypatch):
    await _guest_headers(client)  # ensures DB initialised
    user_id = f"skill-user-{uuid.uuid4().hex[:8]}"
    batch_id = await _approved_batch_for(user_id)
    calls = []

    async def fake_execute(uid, batch, method):
        calls.append(batch["id"])
        await asyncio.sleep(0.2)
        return [SubmissionResultItem(
            application_id=0, company_name="C", role_title="R", status="SUBMITTED",
            submission_method="MANUAL_HANDOFF", message="ok",
        )]

    monkeypatch.setattr(skill_career, "execute_batch_submission", fake_execute)
    args = {"user_id": user_id, "batch_id": batch_id}

    r1, r2 = await asyncio.gather(
        skill_career.handle_submit_approved_application_batch(args),
        skill_career.handle_submit_approved_application_batch(args),
    )

    assert len(calls) == 1
    assert sorted([r1["success"], r2["success"]]) == [False, True]


@pytest.mark.asyncio
async def test_skill_submit_bad_method_returns_friendly_error(client: AsyncClient):
    await _guest_headers(client)
    user_id = f"skill-user-{uuid.uuid4().hex[:8]}"
    batch_id = await _approved_batch_for(user_id)

    res = await skill_career.handle_submit_approved_application_batch(
        {"user_id": user_id, "batch_id": batch_id, "preferred_method": "carrier_pigeon"}
    )

    assert res["success"] is False
    assert "preferred_method" in res["error"]


@pytest.mark.asyncio
async def test_skill_cover_letter_bad_opportunity_id_returns_error():
    res = await skill_career.handle_draft_cover_letter({"user_id": "u", "opportunity_id": "abc"})
    assert res["success"] is False


# 3. target_company search is scoped to the user ----------------------------------

@pytest.mark.asyncio
async def test_skill_cover_letter_company_search_passes_user_id(monkeypatch):
    seen = {}

    async def fake_all(**kwargs):
        seen.update(kwargs)
        return [], 0

    monkeypatch.setattr(skill_career, "get_all_opportunities", fake_all)
    res = await skill_career.handle_draft_cover_letter({"user_id": "scoped-user", "target_company": "Acme"})

    assert res["success"] is False
    assert seen.get("user_id") == "scoped-user"


# 4. explicit clearing of approved_at ---------------------------------------------

@pytest.mark.asyncio
async def test_update_career_application_can_clear_approved_at(client: AsyncClient):
    await _guest_headers(client)
    user_id = f"clear-user-{uuid.uuid4().hex[:8]}"
    app = await get_or_create_career_application(user_id, await _new_opportunity())
    await update_career_application(app.id, user_id, {"approved_at": datetime.now(timezone.utc)})
    assert (await get_career_application_by_id(app.id, user_id)).approved_at is not None

    await update_career_application(app.id, user_id, {"approved_at": None})

    assert (await get_career_application_by_id(app.id, user_id)).approved_at is None


@pytest.mark.asyncio
async def test_revoking_approval_via_patch_clears_approved_at(client: AsyncClient):
    headers = await _guest_headers(client)
    app_id, _ = await _approved_app(client, headers)
    assert (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()["approved_at"]

    r = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"status": "READY_FOR_APPROVAL"}
    )

    assert r.status_code == 200
    assert r.json()["approved_at"] is None


# 5. skill dedupe -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_add_dedupes_case_insensitively_and_upgrades_learning(client: AsyncClient):
    headers = await _guest_headers(client)
    learn = await client.post("/api/career/skills/add", headers=headers, json={"skill": "Docker", "category": "learning"})
    assert learn.status_code == 200
    dup = await client.post("/api/career/skills/add", headers=headers, json={"skill": "docker", "category": "learning"})
    assert dup.status_code == 200

    ver = await client.post(
        "/api/career/skills/add", headers=headers,
        json={"skill": "DOCKER", "category": "verified", "evidence_note": "Shipped a compose stack"},
    )
    assert ver.status_code == 200
    again = await client.post(
        "/api/career/skills/add", headers=headers,
        json={"skill": "docker", "category": "verified", "evidence_note": "Shipped a compose stack"},
    )
    assert again.status_code == 200

    master = (await client.get("/api/career/resumes/master", headers=headers)).json()
    content = master["content"]
    assert [s for s in content["skills"] if s.lower() == "docker"] == ["DOCKER"]
    assert not [s for s in content["learning_skills"] if s.lower() == "docker"]
    assert content["evidence_notes"]["DOCKER"] == "Shipped a compose stack"


@pytest.mark.asyncio
async def test_verified_add_of_existing_skill_records_new_evidence(client: AsyncClient):
    headers = await _guest_headers(client)
    first = await client.post(
        "/api/career/skills/add", headers=headers,
        json={"skill": "Rust", "category": "verified", "evidence_note": "first"},
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/career/skills/add", headers=headers,
        json={"skill": "rust", "category": "verified", "evidence_note": "second"},
    )
    assert second.status_code == 200

    content = (await client.get("/api/career/resumes/master", headers=headers)).json()["content"]
    assert content["evidence_notes"]["Rust"] == "second"
    assert len([s for s in content["skills"] if s.lower() == "rust"]) == 1


# 6. input caps -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oversized_inputs_are_rejected(client: AsyncClient):
    headers = await _guest_headers(client)
    opp_id = await _new_opportunity()
    app_id = (await client.post(f"/api/career/applications/{opp_id}", headers=headers)).json()["id"]

    skill = await client.post("/api/career/skills/add", headers=headers, json={"skill": "x" * 500})
    notes = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"private_notes": "n" * 100000}
    )
    answers = await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"form_answers": {"q": "a" * 200000}}
    )
    desc = await client.get(
        f"/api/career/opportunities/{opp_id}/job-analysis", headers=headers, params={"custom_desc": "d" * 30000}
    )

    assert skill.status_code == 422
    assert notes.status_code == 422
    assert answers.status_code == 422
    assert desc.status_code == 422


@pytest.mark.asyncio
async def test_resume_parse_raw_text_is_capped(client: AsyncClient):
    headers = await _guest_headers(client)
    resp = await client.post("/api/career/resumes/parse-upload", headers=headers, json={"raw_text": "a" * 250000})
    assert resp.status_code == 422
