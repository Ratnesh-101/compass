"""
Compass — application pipeline honesty regressions.

Covers: identity seeding of the first master, Re-Tailor linking, un-invented handoff answers,
read-only handoff-kit GET, batch readiness gate + resume-bound approval hash, auto-prepare
never overwriting user work, mark-applied transition validation, deadline clearing,
no invented tailored summary, prepare race, and radar profile 422 validation.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from backend.memory.career import (
    get_career_application_by_id,
    get_or_create_career_application,
    list_resumes,
    update_career_application,
)
from backend.memory.radar import get_opportunity_by_id, upsert_opportunity
from backend.models_career import ResumeContent
from backend.models_radar import UserOpportunityProfileIn
from backend.services.career_resume import (
    build_default_master_from_profile,
    tailor_resume_for_opportunity,
)
from backend.services.career_submission import (
    compute_batch_content_hash,
    generate_manual_application_package,
)

ATTEST = {
    "attestation_confirmed": True,
    "work_auth_confirmed": True,
    "legal_statements_accepted": True,
}
VALID_MASTER = {
    "full_name": "Honesty Tester",
    "email": "honesty@example.com",
    "skills": ["Python", "FastAPI"],
    "summary": "Final-year student who builds backend services.",
    "education": [{"institution": "Test University", "degree": "B.Tech", "end_year": 2027}],
}


def _user_headers() -> dict:
    return {"x-user-id": f"honesty-{uuid.uuid4().hex[:8]}@compass.internal"}


async def _new_opp() -> int:
    return await upsert_opportunity(
        "Honesty Corp", "Backend Intern", f"https://honesty.test/careers/{uuid.uuid4().hex}"
    )


async def _ready_app(client: AsyncClient, headers: dict) -> tuple[int, int]:
    """Valid master + prepared application (READY_FOR_REVIEW, resume, cover letter)."""
    put = await client.put("/api/career/resumes/master", headers=headers, json=VALID_MASTER)
    assert put.status_code == 200
    opp_id = await _new_opp()
    prep = await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})
    assert prep.status_code == 200
    body = prep.json()
    assert body["status"] == "READY_FOR_REVIEW"
    return opp_id, body["id"]


# 1. identity seeding / validation failure surfaced ------------------------------

@pytest.mark.asyncio
async def test_prepare_seeds_master_email_and_surfaces_missing_name(client: AsyncClient):
    headers = _user_headers()
    opp_id = await _new_opp()

    resp = await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["resume"]["content"]["email"] == headers["x-user-id"]
    assert body["resume"]["content"]["full_name"] == ""  # never invented
    assert body["resume"]["validation_status"] == "VALIDATION_FAILED"
    assert "Full name" in body["missing_fields"]
    assert body["status"] == "RESUME_VALIDATION_FAILED"  # not READY_FOR_REVIEW


@pytest.mark.asyncio
async def test_skills_add_seeds_identity_in_first_master(client: AsyncClient):
    headers = _user_headers()
    resp = await client.post(
        "/api/career/skills/add", headers=headers, json={"skill": "Rust", "category": "learning"}
    )
    assert resp.status_code == 200
    master = (await client.get("/api/career/resumes/master", headers=headers)).json()
    assert master["content"]["email"] == headers["x-user-id"]


def test_default_master_with_unknown_grad_year_does_not_pass_empty_string():
    profile = UserOpportunityProfileIn(university="Test University", degree="B.Tech")
    content = build_default_master_from_profile(profile, user_name="A B", email="a@b.co")
    assert content.education[0].end_year is None


# 2. Re-Tailor links to the application ------------------------------------------

@pytest.mark.asyncio
async def test_tailor_with_application_id_links_new_resume(client: AsyncClient):
    headers = _user_headers()
    opp_id, app_id = await _ready_app(client, headers)
    before = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()["resume_id"]

    resp = await client.post(
        "/api/career/resumes/tailor", headers=headers, json={"opportunity_id": opp_id, "application_id": app_id}
    )

    assert resp.status_code == 200
    new_id = resp.json()["id"]
    assert new_id != before
    after = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert after["resume_id"] == new_id


@pytest.mark.asyncio
async def test_tailor_without_application_id_leaves_application_unchanged(client: AsyncClient):
    headers = _user_headers()
    opp_id, app_id = await _ready_app(client, headers)
    before = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()["resume_id"]

    resp = await client.post("/api/career/resumes/tailor", headers=headers, json={"opportunity_id": opp_id})

    assert resp.status_code == 200
    after = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert after["resume_id"] == before


@pytest.mark.asyncio
async def test_tailor_with_foreign_application_id_is_404_and_does_not_link(client: AsyncClient):
    owner = _user_headers()
    opp_id, app_id = await _ready_app(client, owner)
    attacker = _user_headers()
    before = (await client.get(f"/api/career/applications/{app_id}", headers=owner)).json()["resume_id"]

    resp = await client.post(
        "/api/career/resumes/tailor", headers=attacker, json={"opportunity_id": opp_id, "application_id": app_id}
    )

    assert resp.status_code == 404
    after = (await client.get(f"/api/career/applications/{app_id}", headers=owner)).json()
    assert after["resume_id"] == before


# 3. handoff package / kit never invent answers ----------------------------------

def test_manual_package_does_not_invent_answers():
    app = SimpleNamespace(form_answers={}, cover_letter=None)
    pkg = generate_manual_application_package(app, {"company_name": "C", "role_title": "R"}, {"content": {}})
    answers = pkg["prefilled_answers"]
    assert answers["work_authorization"] is None
    assert answers["availability"] is None
    assert answers["current_degree"] is None
    for field in ("Work authorization declaration", "Availability", "Current degree"):
        assert field in pkg["missing_fields"]


def test_profile_defaults_do_not_assert_work_authorization_or_arrangements():
    profile = UserOpportunityProfileIn()
    assert profile.work_authorization is None
    assert profile.preferred_work_arrangements == []


@pytest.mark.asyncio
async def test_kit_unknown_answers_are_none_and_checklist_is_honest(client: AsyncClient):
    headers = _user_headers()
    _, app_id = await _ready_app(client, headers)
    assert (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()["cover_letter"]

    kit = (await client.get(f"/api/career/applications/{app_id}/handoff-kit", headers=headers)).json()

    assert kit["common_answers"]["work_authorization"] is None
    assert kit["common_answers"]["notice_or_availability"] is None
    assert "work_authorization" in kit["missing_profile_fields"]
    assert "notice_or_availability" in kit["missing_profile_fields"]
    assert kit["checklist"]["cover_letter_reviewed"] is False  # a draft existing is not a review
    assert kit["checklist"]["questions_answered"] is False


@pytest.mark.asyncio
async def test_kit_get_is_read_only(client: AsyncClient):
    headers = _user_headers()
    _, app_id = await _ready_app(client, headers)

    kit = await client.get(f"/api/career/applications/{app_id}/handoff-kit", headers=headers)

    assert kit.status_code == 200
    app = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert app["status"] == "READY_FOR_REVIEW"


@pytest.mark.asyncio
async def test_kit_export_block_uses_the_applications_own_resume(client: AsyncClient):
    # Guest: tailored resume has no name/email, but the master is fixed up afterwards.
    resp = await client.post("/api/guest/session")
    headers = {"x-guest-token": resp.json()["guest_token"]}
    opp_id = await _new_opp()
    prep = await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})
    app_id = prep.json()["id"]
    assert (await client.put("/api/career/resumes/master", headers=headers, json=VALID_MASTER)).status_code == 200

    kit = (await client.get(f"/api/career/applications/{app_id}/handoff-kit", headers=headers)).json()

    assert kit["is_export_blocked"] is True
    assert kit["checklist"]["resume_attached"] is False
    assert kit["block_reason"]
    assert "Complete your profile" not in kit["block_reason"]


# 5. batch readiness gate + approval bound to the resume version -----------------

@pytest.mark.asyncio
async def test_batch_approve_rejects_unready_applications(client: AsyncClient):
    headers = _user_headers()
    opp_id = await _new_opp()
    app_id = (await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})).json()
    batch_id = app_id["batch_id"]
    bare_app = app_id["applications"][0]["id"]

    resp = await client.post(
        f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id}
    )

    assert resp.status_code == 409
    body = resp.json()
    assert str(bare_app) in body["detail"]
    assert body["not_ready"][0]["application_id"] == bare_app
    reasons = " ".join(body["not_ready"][0]["reasons"])
    assert "resume" in reasons.lower() and "cover letter" in reasons.lower()


@pytest.mark.asyncio
async def test_batch_approve_rejects_resume_that_failed_validation(client: AsyncClient):
    headers = _user_headers()  # first master has no name, so the tailored resume fails validation
    opp_id = await _new_opp()
    await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})
    batch = (await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})).json()

    resp = await client.post(
        f"/api/career/batches/{batch['batch_id']}/approve", headers=headers, json={**ATTEST, "batch_id": batch["batch_id"]}
    )

    assert resp.status_code == 409
    assert "VALIDATION_FAILED" in " ".join(resp.json()["not_ready"][0]["reasons"])


@pytest.mark.asyncio
async def test_batch_approve_foreign_batch_is_404(client: AsyncClient):
    owner = _user_headers()
    opp_id, _ = await _ready_app(client, owner)
    batch = (await client.post("/api/career/batches/prepare", headers=owner, json={"opportunity_ids": [opp_id]})).json()

    resp = await client.post(
        f"/api/career/batches/{batch['batch_id']}/approve",
        headers=_user_headers(),
        json={**ATTEST, "batch_id": batch["batch_id"]},
    )

    assert resp.status_code == 404


def test_content_hash_changes_when_resume_stamp_changes():
    base = {"id": 1, "opportunity_id": 2, "resume_id": 3, "cover_letter": "x", "form_answers": {}}
    h1 = compute_batch_content_hash([{**base, "resume_stamp": "v1@2026-01-01T00:00:00"}])
    h2 = compute_batch_content_hash([{**base, "resume_stamp": "v1@2026-01-02T00:00:00"}])
    assert h1 != h2


@pytest.mark.asyncio
async def test_editing_resume_after_approval_invalidates_submission(client: AsyncClient):
    headers = _user_headers()
    opp_id, app_id = await _ready_app(client, headers)
    batch = (await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})).json()
    batch_id = batch["batch_id"]
    appr = await client.post(f"/api/career/batches/{batch_id}/approve", headers=headers, json={**ATTEST, "batch_id": batch_id})
    assert appr.status_code == 200
    token = appr.json()["approval_token"]
    app = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    resume = (await client.get(f"/api/career/resumes/{app['resume_id']}", headers=headers)).json()
    content = {**resume["content"], "summary": "Edited after approval."}

    await asyncio.sleep(0.01)
    put = await client.put(
        f"/api/career/resumes/{resume['id']}", headers=headers, json={"title": resume["title"], "content": content}
    )
    assert put.status_code == 200

    sub = await client.post(
        f"/api/career/batches/{batch_id}/submit", headers=headers, json={"batch_id": batch_id, "approval_token": token}
    )
    assert sub.status_code == 403
    assert "modified" in sub.json()["detail"].lower()


# 6. auto-prepare never overwrites user work --------------------------------------

async def _run_auto_prepare(user_id: str, opps: list, master_content: ResumeContent) -> dict:
    from backend.services import career_auto_prepare as cap

    profile = UserOpportunityProfileIn(auto_prepare_strongest_matches=True, grad_year=2027, degree="B.Tech")
    with patch("backend.memory.radar.get_user_opportunity_profile", AsyncMock(return_value=profile)), \
         patch("backend.memory.radar.get_user_saved_opportunities", AsyncMock(return_value=opps)), \
         patch("backend.memory.career.get_master_resume", AsyncMock(return_value=SimpleNamespace(content=master_content))), \
         patch.object(cap, "evaluate_eligibility", return_value=("ELIGIBLE", "ok", [])):
        return await cap.execute_auto_prepare_for_user(user_id)


def _auto_master() -> ResumeContent:
    return ResumeContent(**VALID_MASTER)


@pytest.mark.asyncio
async def test_auto_prepare_skips_existing_cover_letter_notes_and_progressed_status(client: AsyncClient):
    await client.post("/api/guest/session")  # ensure DB initialised
    user_id = f"auto-{uuid.uuid4().hex[:8]}"
    opps, apps = [], {}
    for kind in ("letter", "notes", "submitted"):
        opp_id = await _new_opp()
        app = await get_or_create_career_application(user_id, opp_id)
        opps.append(await get_opportunity_by_id(opp_id))
        apps[kind] = app.id
    await update_career_application(apps["letter"], user_id, {"cover_letter": "My own letter."})
    await update_career_application(apps["notes"], user_id, {"private_notes": "my notes"})
    await update_career_application(apps["submitted"], user_id, {"status": "SUBMITTED"})

    result = await _run_auto_prepare(user_id, opps, _auto_master())

    assert result["prepared_count"] == 0
    assert all(d["status"] == "skipped_existing_work" for d in result["drafts"])
    letter = await get_career_application_by_id(apps["letter"], user_id)
    assert letter.cover_letter == "My own letter." and letter.resume_id is None
    notes = await get_career_application_by_id(apps["notes"], user_id)
    assert notes.private_notes == "my notes" and notes.resume_id is None
    submitted = await get_career_application_by_id(apps["submitted"], user_id)
    assert submitted.status.value == "SUBMITTED" and submitted.resume_id is None


@pytest.mark.asyncio
async def test_auto_prepare_does_not_reprepare_when_user_edited_notes_tag(client: AsyncClient):
    await client.post("/api/guest/session")
    user_id = f"auto-{uuid.uuid4().hex[:8]}"
    opp_id = await _new_opp()
    opp = await get_opportunity_by_id(opp_id)
    first = await _run_auto_prepare(user_id, [opp], _auto_master())
    assert first["prepared_count"] == 1
    app = await get_career_application_by_id(first["drafts"][0]["application_id"], user_id)
    await update_career_application(app.id, user_id, {"private_notes": "tag removed by user"})

    second = await _run_auto_prepare(user_id, [opp], _auto_master())

    assert second["prepared_count"] == 0
    again = await get_career_application_by_id(app.id, user_id)
    assert again.resume_id == app.resume_id


# 7. mark-applied / track-external transitions ------------------------------------

@pytest.mark.asyncio
async def test_mark_applied_from_saved_is_rejected(client: AsyncClient):
    headers = _user_headers()
    opp_id = await _new_opp()
    app_id = (await client.post("/api/career/batches/prepare", headers=headers, json={"opportunity_ids": [opp_id]})).json()["applications"][0]["id"]

    mark = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)
    track = await client.post("/api/career/track-external-application", headers=headers, params={"opportunity_id": opp_id})

    assert mark.status_code == 409 and track.status_code == 409
    app = (await client.get(f"/api/career/applications/{app_id}", headers=headers)).json()
    assert app["status"] == "SAVED" and app["submitted_at"] is None


@pytest.mark.asyncio
async def test_mark_applied_keeps_existing_deadline(client: AsyncClient):
    headers = _user_headers()
    _, app_id = await _ready_app(client, headers)
    mine = (date.today() + timedelta(days=90)).isoformat()
    assert (await client.patch(
        f"/api/career/applications/{app_id}", headers=headers, json={"target_deadline": mine}
    )).status_code == 200

    mark = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)

    assert mark.status_code == 200
    assert mark.json()["status"] == "SUBMITTED"
    assert mark.json()["target_deadline"] == mine


@pytest.mark.asyncio
async def test_mark_applied_fills_empty_deadline_with_utc_followup(client: AsyncClient):
    headers = _user_headers()
    _, app_id = await _ready_app(client, headers)

    mark = await client.post(f"/api/career/applications/{app_id}/mark-applied", headers=headers)

    expected = (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()
    assert mark.json()["target_deadline"] == expected


# 8. PATCH deadline clearing and cover letter ------------------------------------

@pytest.mark.asyncio
async def test_patch_clear_target_deadline_and_persist_cover_letter(client: AsyncClient):
    headers = _user_headers()
    _, app_id = await _ready_app(client, headers)
    day = (date.today() + timedelta(days=30)).isoformat()
    set_resp = await client.patch(f"/api/career/applications/{app_id}", headers=headers, json={"target_deadline": day})
    assert set_resp.json()["target_deadline"] == day

    cleared = await client.patch(
        f"/api/career/applications/{app_id}",
        headers=headers,
        json={"clear_target_deadline": True, "cover_letter": "Edited letter body."},
    )

    assert cleared.status_code == 200
    body = cleared.json()
    assert body["target_deadline"] is None
    assert body["cover_letter"] == "Edited letter body."


@pytest.mark.asyncio
async def test_patch_cover_letter_is_owner_scoped(client: AsyncClient):
    owner = _user_headers()
    _, app_id = await _ready_app(client, owner)

    resp = await client.patch(
        f"/api/career/applications/{app_id}", headers=_user_headers(), json={"cover_letter": "hijack"}
    )

    assert resp.status_code == 404
    assert (await client.get(f"/api/career/applications/{app_id}", headers=owner)).json()["cover_letter"] != "hijack"


# 9. tailored summary is never invented --------------------------------------------

@pytest.mark.asyncio
async def test_tailored_summary_uses_master_summary_or_stays_empty():
    opp = await get_opportunity_by_id(await _new_opp())
    with_summary, _, _ = tailor_resume_for_opportunity(ResumeContent(**VALID_MASTER), opp)
    assert with_summary.summary == VALID_MASTER["summary"]

    no_summary = {k: v for k, v in VALID_MASTER.items() if k != "summary"}
    tailored, _, _ = tailor_resume_for_opportunity(ResumeContent(**no_summary), opp)
    assert not tailored.summary
    assert "Undergraduate" not in (tailored.summary or "")


# 10. prepare race -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_prepares_leave_a_single_tailored_resume(client: AsyncClient):
    headers = _user_headers()
    assert (await client.put("/api/career/resumes/master", headers=headers, json=VALID_MASTER)).status_code == 200
    opp_id = await _new_opp()
    user_id = headers["x-user-id"]

    r1, r2 = await asyncio.gather(
        client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id}),
        client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id}),
    )

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["resume_id"] == r2.json()["resume_id"]
    tailored = [r for r in await list_resumes(user_id) if not r.is_master and r.opportunity_id == opp_id]
    assert len(tailored) == 1


@pytest.mark.asyncio
async def test_link_resume_if_unlinked_only_links_once(client: AsyncClient):
    from backend.memory.career import link_resume_if_unlinked, upsert_master_resume
    from backend.models_career import ResumeContent

    await client.post("/api/guest/session")
    user_id = f"link-{uuid.uuid4().hex[:8]}"
    opp_id = await _new_opp()
    r1 = await upsert_master_resume(user_id, ResumeContent(full_name="Tester 1"))
    r2 = await upsert_master_resume(f"{user_id}_alt", ResumeContent(full_name="Tester 2"))
    app = await get_or_create_career_application(user_id, opp_id)
    first = await link_resume_if_unlinked(app.id, user_id, r1.id)
    second = await link_resume_if_unlinked(app.id, user_id, r2.id)
    assert first is not None and first.resume_id == r1.id
    assert second is None
    assert (await get_career_application_by_id(app.id, user_id)).resume_id == r1.id


# 11. radar profile validation -----------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"grad_year": 2050},
        {"grad_year": 1999},
        {"academic_year": 9},
        {"cgpa": 11, "cgpa_scale": 10},
        {"cgpa": 5, "cgpa_scale": 7},
        {"cgpa": -1},
    ],
)
async def test_profile_put_rejects_out_of_range_with_422(client: AsyncClient, bad):
    resp = await client.put("/api/opportunities/profile", headers=_user_headers(), json=bad)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_profile_put_accepts_valid_values(client: AsyncClient):
    resp = await client.put(
        "/api/opportunities/profile",
        headers=_user_headers(),
        json={"academic_year": 3, "grad_year": 2027, "cgpa": 8.5, "cgpa_scale": 10},
    )
    assert resp.status_code == 200
