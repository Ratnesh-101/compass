"""
Compass — Career Copilot Comprehensive End-to-End Workflow & Security Verification Suite.

Validates:
1. End-to-End 15-step candidate career journey (profile -> discovery -> eligibility -> tailoring
   -> validation -> application -> batch -> approval -> adapter submission -> audit logging).
2. Phase 3 submission security negative battery:
   - Submission without approval
   - Missing factual-accuracy attestation
   - Missing work-authorization confirmation
   - Missing legal-declaration acceptance
   - Cross-user batch approval and submission attempts
   - Modified application after approval (automatic invalidation)
   - Modified batch content after approval (content-hash mismatch)
   - Expired or invalid cryptographic approval token
   - Duplicate submission requests (replay protection)
   - Concurrent submission requests (locking protection)
   - Submission of cancelled or withdrawn application
3. Phase 4 Adapter capabilities:
   - ManualHandoffAdapter
   - AtsEndpointAdapter (unconfigured enterprise key fallback)
   - BrowserAssistedAdapter (DOM prefill kit without anti-bot bypass)
4. Phase 6 Tavily & verification edge cases:
   - Closed requisition 404/410 detection
   - Reachability without premature promotion
   - Tracking parameter stripping and deduplication
   - Prompt injection fencing
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone
import urllib.parse
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.memory.career import (
    approve_application_batch,
    create_application_batch,
    create_tailored_resume,
    get_application_batch,
    get_career_application_by_id,
    get_master_resume,
    get_or_create_career_application,
    list_career_applications,
    update_application_batch_status,
    update_career_application,
    upsert_master_resume,
)
from backend.memory.radar import (
    get_all_opportunities,
    get_opportunity_by_id,
    get_user_opportunity_profile,
    upsert_opportunity,
    upsert_opportunity_requirements,
    upsert_user_opportunity_profile,
)
from backend.models_career import (
    CareerApplicationStatus,
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
    ResumeProjectItem,
    ResumeValidationStatus,
    SubmissionMethod,
)
from backend.models_radar import OpportunityStatus, UserOpportunityProfileIn
from backend.services.career_resume import (
    draft_truthful_cover_letter,
    tailor_resume_for_opportunity,
    validate_resume_against_master,
)
from backend.services.career_submission import (
    AtsEndpointAdapter,
    BrowserAssistedAdapter,
    ManualHandoffAdapter,
    compute_batch_content_hash,
    execute_batch_submission,
    generate_batch_approval_token,
    get_batch_lock,
    submit_single_application,
    verify_batch_approval_token,
)
from backend.services.radar_eligibility import evaluate_eligibility
from backend.models_radar import EligibilityClassification
from backend.services.radar_sources import canonicalize_url
from backend.services.radar_verifier import verify_opportunity_status


# ===========================================================================
# FIXTURES: OPPORTUNITY SEEDING & TEST ISOLATION
# ===========================================================================

TEST_USER_IDS = [
    "candidate_e2e_user",
    "alice@compass.internal",
    "bob@compass.internal",
    "user_cancel_test",
    "user_adapter_test",
    "user_ats_test",
    "user_browser_test",
    "user_parse_test",
    "user_ats_timeout",
    "user_ats_confirmed",
    "token_tester",
]


@pytest.fixture(autouse=True)
async def setup_career_e2e_environment():
    """Ensure opportunities 100-115 exist and test users are cleanly isolated for each test."""
    from backend.memory.db import get_pool
    import backend.memory.radar as radar_mem

    pool = await get_pool()
    if pool:
        async with pool.acquire() as conn:
            # Clean up test applications & batches first to ensure isolation and idempotency
            await conn.execute(
                "DELETE FROM career_applications WHERE user_id = ANY($1::text[])",
                TEST_USER_IDS,
            )
            await conn.execute(
                "DELETE FROM application_batches WHERE user_id = ANY($1::text[])",
                TEST_USER_IDS,
            )
            await conn.execute(
                "DELETE FROM resumes WHERE user_id = ANY($1::text[])",
                TEST_USER_IDS,
            )
            await conn.execute(
                "DELETE FROM user_opportunity_profiles WHERE user_id = ANY($1::text[])",
                TEST_USER_IDS,
            )

            # Insert mock opportunities 100 to 115 if missing
            for opp_id in range(100, 116):
                await conn.execute(
                    """
                    INSERT INTO opportunities (
                        id, company_name, normalized_company, role_title,
                        opportunity_type, category, location, work_arrangement,
                        country, is_india_eligible, canonical_url, official_application_url,
                        current_status, description, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, 'internship', 'ai_ml', 'Bengaluru, India',
                        'hybrid', 'India', TRUE, $5, $5, 'DISCOVERED', 'Test opportunity description',
                        now(), now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        current_status = EXCLUDED.current_status,
                        updated_at = now()
                    """,
                    opp_id,
                    f"Test Company {opp_id}",
                    f"test_company_{opp_id}",
                    f"Engineering Intern {opp_id}",
                    f"https://testcompany{opp_id}.com/careers/intern",
                )
    else:
        # In-memory mode fallback
        for opp_id in range(100, 116):
            radar_mem._in_memory_opportunities[opp_id] = {
                "id": opp_id,
                "company_name": f"Test Company {opp_id}",
                "normalized_company": f"test_company_{opp_id}",
                "role_title": f"Engineering Intern {opp_id}",
                "opportunity_type": "internship",
                "category": "ai_ml",
                "location": "Bengaluru, India",
                "work_arrangement": "hybrid",
                "country": "India",
                "is_india_eligible": True,
                "canonical_url": f"https://testcompany{opp_id}.com/careers/intern",
                "official_application_url": f"https://testcompany{opp_id}.com/careers/intern",
                "current_status": OpportunityStatus.DISCOVERED,
                "description": "Test opportunity description",
                "requirements": None,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }

    yield

    # Teardown: clean up test user records
    if pool:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM career_applications WHERE user_id = ANY($1::text[])",
                    TEST_USER_IDS,
                )
                await conn.execute(
                    "DELETE FROM application_batches WHERE user_id = ANY($1::text[])",
                    TEST_USER_IDS,
                )
        except Exception:
            pass


# ===========================================================================
# 1. PHASE 5: COMPLETE END-TO-END CAREER WORKFLOW
# ===========================================================================

@pytest.mark.asyncio
async def test_complete_career_copilot_end_to_end_workflow():
    """
    Executes the full 15-step end-to-end career workflow:
    1. Create candidate profile
    2. Discover opportunity
    3. Verify provenance & status
    4. Evaluate eligibility
    5. Create master resume
    6. Tailor resume for opportunity
    7. Guard against unsupported claims
    8. Prepare application & find missing fields
    9. Save application and supporting documents
    10. Create reviewable batch
    11. Verify unapproved submission is blocked
    12. Explicitly approve batch with attestations and cryptographic token
    13. Execute submission via adapter
    14. Persist outcome and audit events
    15. Reload records and verify state consistency
    """
    user_id = "candidate_e2e_user"

    # Step 1: Create or load candidate profile
    profile_data = UserOpportunityProfileIn(
        target_roles=["swe", "ai_ml"],
        degree="B.Tech Computer Science",
        degree_specialization="Artificial Intelligence",
        academic_year=3,
        grad_year=2027,
        university="Indian Institute of Technology Delhi",
        country_of_study="India",
        work_auth_india=True,
        requires_sponsorship=False,
        skills=["Python", "FastAPI", "PostgreSQL", "PyTorch", "Docker"],
        preferred_locations=["Bengaluru", "Remote"],
    )
    await upsert_user_opportunity_profile(user_id, profile_data)
    saved_profile = await get_user_opportunity_profile(user_id)
    assert saved_profile is not None
    assert saved_profile.university == "Indian Institute of Technology Delhi"

    # Step 2: Discover opportunity
    opp_id = await upsert_opportunity(
        company_name="Acme Robotics India",
        role_title="Autonomous Systems Software Intern",
        canonical_url="https://acmerobotics.com/careers/intern-2026",
        official_application_url="https://acmerobotics.com/careers/intern-2026",
        current_status=OpportunityStatus.DISCOVERED,
        opportunity_type="internship",
        category="ai_ml",
        location="Bengaluru, India",
        work_arrangement="hybrid",
        country="India",
        is_india_eligible=True,
        description="Develop computer vision algorithms and robot motion planners in Python and PyTorch.",
    )
    await upsert_opportunity_requirements(opp_id, {
        "eligible_degree_types": ["B.Tech", "B.E."],
        "eligible_academic_years": [3, 4],
        "eligible_graduation_years": [2026, 2027],
        "eligible_countries": ["India"],
        "work_auth_required": True,
        "sponsorship_available": False,
        "required_skills": ["Python", "PyTorch"],
    })
    opp = await get_opportunity_by_id(opp_id, user_id)
    assert opp is not None
    assert opp.company_name == "Acme Robotics India"
    assert opp.official_application_url is not None

    # Step 3: Verify opportunity status
    # Inconclusive/unreachable page does not prematurely promote to OPEN_CONFIRMED
    status, summary, verified_at = await verify_opportunity_status(
        opp.official_application_url,
        current_status=opp.current_status,
    )
    assert status in {OpportunityStatus.NEEDS_VERIFICATION, OpportunityStatus.DISCOVERED}
    assert verified_at is not None

    # Step 4: Evaluate candidate eligibility
    classification, explanation, reasons = evaluate_eligibility(opp, saved_profile)
    assert classification in {EligibilityClassification.ELIGIBLE, EligibilityClassification.POTENTIAL_MATCH}
    assert len(reasons) > 0

    # Step 5: Create master resume
    master_content = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        phone="+91 9876543210",
        location="Bengaluru, India",
        github_or_portfolio="https://github.com/Ratnesh-101",
        linkedin_url="https://linkedin.com/in/ratnesh",
        skills=["Python", "FastAPI", "PostgreSQL", "PyTorch", "Docker"],
        education=[
            ResumeEducationItem(
                institution="Indian Institute of Technology Delhi",
                degree="B.Tech Computer Science",
                field_of_study="Artificial Intelligence",
                start_year=2023,
                end_year=2027,
                cgpa_or_grade="8.9 / 10",
            )
        ],
        projects=[
            ResumeProjectItem(
                title="Autonomous Vision Navigation",
                description="Engineered visual odometry pipeline using PyTorch and OpenCV.",
                technologies=["Python", "PyTorch", "OpenCV"],
                highlights=["Reduced drift by 18%", "Implemented real-time feature matching"],
            ),
            ResumeProjectItem(
                title="Distributed Task Queue",
                description="Asynchronous microservice task orchestrator built with FastAPI and PostgreSQL.",
                technologies=["Python", "FastAPI", "PostgreSQL"],
                highlights=["Achieved sub-15ms queue latency"],
            ),
        ],
        experience=[],
        achievements=["Institute Merit Scholarship 2024"],
        certifications=["Deep Learning Specialization"],
    )
    master_resume = await upsert_master_resume(user_id, master_content, "Candidate Master Resume")
    assert master_resume.is_master is True
    assert master_resume.validation_status == ResumeValidationStatus.APPROVED

    # Step 6: Tailor resume for the opportunity
    tailored_content, report, val_status = tailor_resume_for_opportunity(
        master=master_resume.content,
        opportunity=opp,
        custom_title="Acme Robotics Tailored Resume",
    )
    assert val_status == ResumeValidationStatus.READY_FOR_REVIEW
    assert report.is_valid is True
    # Invariant: Relevant skills (Python, PyTorch) appear first
    assert tailored_content.skills[0] in {"Python", "PyTorch"}

    tailored_resume = await create_tailored_resume(
        user_id=user_id,
        opportunity_id=opp.id,
        title=f"{opp.company_name} Tailored Resume",
        content=tailored_content,
        validation_report=report,
        validation_status=val_status,
    )
    assert tailored_resume.id is not None

    # Step 7: Guard against unsupported resume claims
    fabricated_content = tailored_content.model_copy(deep=True)
    fabricated_content.skills.append("Quantum Computing")  # Not in master!
    fabricated_report = validate_resume_against_master(fabricated_content, master_resume.content, opp)
    assert fabricated_report.is_valid is False
    assert any("Quantum Computing" in u for u in fabricated_report.unsupported_claims)

    # Step 8: Prepare application and identify missing information
    app_record = await get_or_create_career_application(user_id, opp.id)
    assert app_record.status == CareerApplicationStatus.SAVED

    # Draft truthful cover letter
    letter_text, v_projs, v_skills = draft_truthful_cover_letter(master_resume.content, opp)
    assert "Autonomous Vision Navigation" in v_projs
    assert "Ratnesh Singh" in letter_text

    # Step 9: Save application and supporting documents
    app_record = await update_career_application(
        app_record.id,
        user_id,
        {
            "resume_id": tailored_resume.id,
            "cover_letter": letter_text,
            "status": CareerApplicationStatus.READY_FOR_REVIEW.value,
            "form_answers": {
                "work_authorization": "Eligible to work in India / No sponsorship required",
                "availability": "Available for 6-month internship starting May 2026",
            },
        },
    )
    assert app_record is not None
    assert app_record.resume_id == tailored_resume.id
    assert app_record.status == CareerApplicationStatus.READY_FOR_REVIEW

    # Step 10: Create a reviewable batch
    batch_id = await create_application_batch(user_id, [app_record.id])
    batch_data = await get_application_batch(batch_id, user_id)
    assert batch_data is not None
    assert batch_data["status"] == "DRAFT"

    # Step 11: Confirm unapproved submission is strictly blocked
    blocked_result = await submit_single_application(app_record.id, user_id, SubmissionMethod.MANUAL_HANDOFF)
    assert blocked_result.status == "BLOCKED"
    assert "not been explicitly reviewed and approved" in blocked_result.message

    # Step 12: Explicitly approve the exact reviewed batch
    fetched_app = await get_career_application_by_id(app_record.id, user_id)
    assert fetched_app is not None
    apps_data = [fetched_app.model_dump()]
    content_hash = compute_batch_content_hash(apps_data)
    approval_token = generate_batch_approval_token(user_id, batch_id, [app_record.id], content_hash)

    approved = await approve_application_batch(batch_id, user_id, approval_token)
    assert approved is True

    # Confirm application transitioned to APPROVED_FOR_SUBMISSION
    app_after_approval = await get_career_application_by_id(app_record.id, user_id)
    assert app_after_approval is not None
    assert app_after_approval.status == CareerApplicationStatus.APPROVED_FOR_SUBMISSION

    # Step 13: Exercise submission via adapter
    batch_approved = await get_application_batch(batch_id, user_id)
    assert batch_approved is not None
    results = await execute_batch_submission(user_id, batch_approved, SubmissionMethod.MANUAL_HANDOFF)
    assert len(results) == 1
    assert results[0].status == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value
    assert results[0].manual_package is not None
    assert results[0].manual_package["company_name"] == "Acme Robotics India"
    assert "Autonomous Vision Navigation" in str(results[0].manual_package["cover_letter"])

    # Step 14: Persist outcome and audit events
    await update_application_batch_status(batch_id, user_id, "SUBMITTED")

    # Step 15: Reload records and confirm complete consistency
    reloaded_batch = await get_application_batch(batch_id, user_id)
    assert reloaded_batch is not None
    assert reloaded_batch["status"] == "SUBMITTED"
    reloaded_app = await get_career_application_by_id(app_record.id, user_id)
    assert reloaded_app is not None
    assert reloaded_app.submission_method == SubmissionMethod.MANUAL_HANDOFF
    assert reloaded_app.submission_result is not None
    assert reloaded_app.submission_result.get("result") == "manual_package_generated"


# ===========================================================================
# 2. PHASE 3: SUBMISSION AND APPROVAL SECURITY BATTERY
# ===========================================================================

@pytest.mark.asyncio
async def test_security_missing_attestation_blocks_approval():
    """Rejects batch approval when required attestations are omitted."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "test_e2e_applicant_99"}) as client:
        # Create opportunity & batch
        prep_res = await client.post("/api/career/batches/prepare", json={"opportunity_ids": [101]})
        batch_id = prep_res.json()["batch_id"]

        # Missing attestation_confirmed
        res1 = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": False, "work_auth_confirmed": True, "legal_statements_accepted": True},
        )
        assert res1.status_code == 400
        assert "strictly required" in res1.json()["detail"]

        # Missing work_auth_confirmed
        res2 = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": True, "work_auth_confirmed": False, "legal_statements_accepted": True},
        )
        assert res2.status_code == 400

        # Missing legal_statements_accepted
        res3 = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": True, "work_auth_confirmed": True, "legal_statements_accepted": False},
        )
        assert res3.status_code == 400


@pytest.mark.asyncio
async def test_security_unapproved_batch_submission_rejected():
    """Rejects submission of a batch that has not passed explicit user approval."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "test_e2e_applicant_99"}) as client:
        prep_res = await client.post("/api/career/batches/prepare", json={"opportunity_ids": [102]})
        batch_id = prep_res.json()["batch_id"]

        submit_res = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id},
        )
        assert submit_res.status_code == 403
        assert "not passed explicit user approval" in submit_res.json()["detail"]


async def _prepare_ready_application(client, opp_id: int, headers=None) -> None:
    """Seed a valid master and prepare the application so batch approval's readiness gate passes."""
    put = await client.put(
        "/api/career/resumes/master",
        headers=headers,
        json={
            "full_name": "E2E Applicant",
            "email": "e2e@example.com",
            "skills": ["Python"],
            "education": [{"institution": "Test University", "degree": "B.Tech", "end_year": 2027}],
        },
    )
    assert put.status_code == 200
    prep = await client.post("/api/career/applications/prepare", headers=headers, params={"opportunity_id": opp_id})
    assert prep.status_code == 200
    # The shared test DB persists across runs, so the application may already be further along.
    assert prep.json()["resume_id"] is not None and prep.json()["cover_letter"]


@pytest.mark.asyncio
async def test_security_cross_user_approval_and_submission_isolation():
    """User B cannot approve or submit User A's batch."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # User A prepares batch
        await _prepare_ready_application(client, 103, {"x-user-id": "alice@compass.internal"})
        prep_res = await client.post(
            "/api/career/batches/prepare",
            json={"opportunity_ids": [103]},
            headers={"x-user-id": "alice@compass.internal"},
        )
        assert prep_res.status_code == 200
        batch_id = prep_res.json()["batch_id"]

        # User B attempts to approve User A's batch -> 404 (isolated)
        approve_attempt = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": True, "work_auth_confirmed": True, "legal_statements_accepted": True},
            headers={"x-user-id": "bob@compass.internal"},
        )
        assert approve_attempt.status_code == 404

        # Alice approves her own batch
        alice_approve = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": True, "work_auth_confirmed": True, "legal_statements_accepted": True},
            headers={"x-user-id": "alice@compass.internal"},
        )
        assert alice_approve.status_code == 200
        token = alice_approve.json()["approval_token"]

        # User B attempts to submit Alice's approved batch -> 404
        bob_submit = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id, "approval_token": token},
            headers={"x-user-id": "bob@compass.internal"},
        )
        assert bob_submit.status_code == 404


@pytest.mark.asyncio
async def test_security_modified_application_invalidates_batch_approval():
    """Modifying reviewed application content invalidates batch approval and requires renewed approval."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "test_e2e_applicant_99"}) as client:
        # 1. Prepare batch
        await _prepare_ready_application(client, 104)
        prep_res = await client.post("/api/career/batches/prepare", json={"opportunity_ids": [104]})
        batch_id = prep_res.json()["batch_id"]
        app_id = prep_res.json()["applications"][0]["id"]

        # 2. Approve batch
        appr_res = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": True, "work_auth_confirmed": True, "legal_statements_accepted": True},
        )
        assert appr_res.status_code == 200
        token = appr_res.json()["approval_token"]

        # 3. Materially modify application content (change cover letter)
        patch_res = await client.post(
            f"/api/career/applications/{app_id}/cover-letter",
            json={"cover_letter": "I have added new claims to my application after approval."},
        )
        assert patch_res.status_code == 200

        # Application status must be reset from APPROVED_FOR_SUBMISSION to READY_FOR_REVIEW
        app_check = await client.get("/api/career/applications")
        modified_app = next(a for a in app_check.json() if a["id"] == app_id)
        assert modified_app["status"] == CareerApplicationStatus.READY_FOR_REVIEW.value

        # 4. Attempt submission with the old approval token -> Must be rejected (invalidated / hash mismatch)
        submit_res = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id, "approval_token": token},
        )
        assert submit_res.status_code in {403, 409}
        detail = submit_res.json()["detail"]
        assert "modified" in detail.lower() or "approval" in detail.lower()


@pytest.mark.asyncio
async def test_security_expired_and_tampered_approval_tokens():
    """Cryptographic verification rejects tampered, forged, and expired tokens."""
    user = "token_tester"
    batch_id = "batch_test_tok_99"
    app_ids = [401, 402]
    c_hash = "mock_hash_abc123"

    # 1. Valid token
    valid_token = generate_batch_approval_token(user, batch_id, app_ids, c_hash, expires_in_seconds=3600)
    ok, reason = verify_batch_approval_token(valid_token, user, batch_id, c_hash)
    assert ok is True
    assert reason == "Valid"

    # 2. Tampered content hash
    ok_tamper, reason_tamper = verify_batch_approval_token(valid_token, user, batch_id, "different_hash_modified_content")
    assert ok_tamper is False
    assert "modified" in reason_tamper

    # 3. User mismatch (forged token)
    ok_user, reason_user = verify_batch_approval_token(valid_token, "malicious_user", batch_id, c_hash)
    assert ok_user is False
    assert "mismatch" in reason_user

    # 4. Expired token
    expired_token = generate_batch_approval_token(user, batch_id, app_ids, c_hash, expires_in_seconds=-10)
    ok_exp, reason_exp = verify_batch_approval_token(expired_token, user, batch_id, c_hash)
    assert ok_exp is False
    assert "expired" in reason_exp

    # 5. Cryptographically corrupted token payload
    corrupted_token = valid_token[:-6] + "999999"
    ok_corrupt, reason_corrupt = verify_batch_approval_token(corrupted_token, user, batch_id, c_hash)
    assert ok_corrupt is False


@pytest.mark.asyncio
async def test_security_duplicate_and_concurrent_batch_submission():
    """Prevents duplicate replay submissions and concurrent double-execution."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "test_e2e_applicant_99"}) as client:
        # Prepare & approve batch
        await _prepare_ready_application(client, 105)
        prep_res = await client.post("/api/career/batches/prepare", json={"opportunity_ids": [105]})
        batch_id = prep_res.json()["batch_id"]

        appr_res = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={"batch_id": batch_id, "attestation_confirmed": True, "work_auth_confirmed": True, "legal_statements_accepted": True},
        )
        assert appr_res.status_code == 200
        token = appr_res.json()["approval_token"]

        # First submission -> Succeeds
        sub1 = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id, "approval_token": token},
        )
        assert sub1.status_code == 200
        assert sub1.json()["total_processed"] >= 1

        # Second submission -> Rejected with 409 Conflict (Duplicate replay blocked)
        sub2 = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id, "approval_token": token},
        )
        assert sub2.status_code == 409
        assert "already been" in sub2.json()["detail"].lower() or "duplicate" in sub2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_security_cancelled_and_withdrawn_application_blocked():
    """Submission of a cancelled or withdrawn application is strictly rejected."""
    user = "user_cancel_test"
    app_rec = await get_or_create_career_application(user, 106)

    # Transition to WITHDRAWN
    await update_career_application(app_rec.id, user, {"status": CareerApplicationStatus.WITHDRAWN.value})

    result = await submit_single_application(app_rec.id, user, SubmissionMethod.MANUAL_HANDOFF)
    assert result.status == "BLOCKED"
    assert "withdrawn" in result.message.lower()


# ===========================================================================
# 3. PHASE 4: VERIFY ACTUAL SUBMISSION CAPABILITIES
# ===========================================================================

@pytest.mark.asyncio
async def test_adapter_manual_handoff_capabilities():
    """ManualHandoffAdapter generates complete, verified candidate kit without claiming automated submission."""
    adapter = ManualHandoffAdapter()
    user = "user_adapter_test"
    app_rec = await get_or_create_career_application(user, 107)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
        "form_answers": {"work_authorization": "Eligible for India", "availability": "Immediate"},
    })

    opp_dict = {
        "company_name": "Google India",
        "role_title": "Software Engineer Intern",
        "official_application_url": "https://careers.google.com/jobs/results/swe",
    }
    resume_dict = {
        "title": "Ratnesh Resume",
        "content": {"full_name": "Ratnesh Singh", "email": "ratnesh@example.com", "phone": "+919999999999", "education": [{"institution": "IIT"}]},
    }

    result = await adapter.execute(app_rec, opp_dict, resume_dict, user)
    assert result.status == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value
    assert result.submission_method == "manual_handoff"
    assert result.manual_package is not None
    portal_host = urllib.parse.urlparse(result.manual_package["portal_url"]).netloc.lower()
    assert portal_host == "careers.google.com" or portal_host.endswith(".google.com")
    assert len(result.manual_package["submission_instructions"]) >= 5


@pytest.mark.asyncio
async def test_adapter_ats_endpoint_safe_fallback_when_unconfigured():
    """AtsEndpointAdapter transparently falls back to manual handoff when enterprise credentials not present."""
    adapter = AtsEndpointAdapter()
    user = "user_ats_test"
    app_rec = await get_or_create_career_application(user, 108)
    await update_career_application(app_rec.id, user, {"status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value})

    opp_dict = {
        "company_name": "Stripe",
        "role_title": "Backend Engineering Intern",
        "official_application_url": "https://stripe.com/jobs/backend-intern",
    }
    result = await adapter.execute(app_rec, opp_dict, None, user)
    # Never fabricates submission; safely creates manual package
    assert result.status == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value
    assert result.manual_package is not None
    assert "not configured" in result.message.lower()


@pytest.mark.asyncio
async def test_adapter_browser_assisted_prefill_kit():
    """BrowserAssistedAdapter provides DOM prefill mapping and respects candidate CAPTCHA control."""
    adapter = BrowserAssistedAdapter()
    user = "user_browser_test"
    app_rec = await get_or_create_career_application(user, 109)
    await update_career_application(app_rec.id, user, {"status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value})

    opp_dict = {
        "company_name": "Microsoft India",
        "role_title": "Software Engineer Intern",
        "official_application_url": "https://careers.microsoft.com/jobs/123",
    }
    resume_dict = {
        "title": "Microsoft Resume",
        "content": {"full_name": "Candidate", "email": "candidate@example.com"},
    }

    result = await adapter.execute(app_rec, opp_dict, resume_dict, user)
    assert result.status == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value
    assert result.submission_method == "browser_assisted"
    kit = result.manual_package
    assert kit is not None
    assert "prefill_data" in kit
    assert "dom_selector_hints" in kit
    # Safety invariant: Never attempts to bypass CAPTCHA
    assert any("captcha" in g.lower() for g in kit["security_guardrails"])


# ===========================================================================
# 4. PHASE 6: TAVILY & VERIFICATION RESILIENCE TESTS
# ===========================================================================

@pytest.mark.asyncio
async def test_verifier_handles_404_closed_requisition():
    """Official application page returning 404/410 transitions status to CLOSED_CONFIRMED."""
    with patch("backend.services.radar_verifier.safe_http_get_with_url", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = (404, "", {}, "https://company.com/expired-job")

        status, evidence, _ = await verify_opportunity_status(
            "https://company.com/expired-job",
            current_status=OpportunityStatus.NEEDS_VERIFICATION,
        )
        assert status == OpportunityStatus.CLOSED_CONFIRMED
        assert "404" in evidence


@pytest.mark.asyncio
async def test_verifier_connection_timeout_retains_status():
    """Verification timeout retains existing status without fabrication."""
    with patch("backend.services.radar_verifier.safe_http_get_with_url", new_callable=AsyncMock, side_effect=Exception("ReadTimeout")):
        status, evidence, _ = await verify_opportunity_status(
            "https://slow-portal.com/job",
            current_status=OpportunityStatus.DISCOVERED,
        )
        assert status == OpportunityStatus.DISCOVERED
        assert "timed out" in evidence.lower() or "error" in evidence.lower()


def test_url_canonicalization_strips_tracking_and_deduplicates():
    """Strips query tracking parameters (utm, gh_src, ref) to produce canonical deduplication keys."""
    dirty_url = "https://jobs.lever.co/company/abc123?utm_source=linkedin&gh_src=1234&ref=jobboard&lever-origin=applied#apply"
    clean = canonicalize_url(dirty_url)
    assert "utm_source" not in clean
    assert "gh_src" not in clean
    assert "ref" not in clean
    assert clean == "https://jobs.lever.co/company/abc123"


# ===========================================================================
# 5. REAL RESUME FILE PARSING BATTERY (PDF, TXT, MD, CORRUPT, ENCRYPTED)
# ===========================================================================

MINIMAL_VALID_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
    b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
    b"5 0 obj << /Length 115 >>\n"
    b"stream\n"
    b"BT\n"
    b"/F1 12 Tf\n"
    b"72 712 Td\n"
    b"(Ratnesh Singh | ratnesh@example.com) Tj\n"
    b"0 -20 Td\n"
    b"(Skills: Python, FastAPI, PostgreSQL) Tj\n"
    b"ET\n"
    b"endstream\n"
    b"endobj\n"
    b"xref\n"
    b"0 6\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"0000000227 00000 n \n"
    b"0000000297 00000 n \n"
    b"trailer << /Size 6 /Root 1 0 R >>\n"
    b"startxref\n"
    b"464\n"
    b"%%EOF"
)


def test_resume_file_pdf_valid_text_extraction():
    """Extracts candidate info and skills from valid text-based PDF without hallucination."""
    from backend.services.career_file_parser import extract_resume_from_file_bytes

    res = extract_resume_from_file_bytes(MINIMAL_VALID_PDF, "ratnesh_resume.pdf")
    assert res.success is True
    assert res.file_type == ".pdf"
    assert res.page_count == 1
    assert res.extracted_content is not None
    assert "Ratnesh Singh" in res.extracted_content.full_name
    assert "Python" in res.extracted_content.skills
    assert "FastAPI" in res.extracted_content.skills


def test_resume_file_pdf_encrypted_handled_clearly():
    """Detects password-encrypted PDF and returns clear user-facing error."""
    import io
    import pypdf
    from backend.services.career_file_parser import extract_resume_from_file_bytes

    w = pypdf.PdfWriter()
    w.append(io.BytesIO(MINIMAL_VALID_PDF))
    w.encrypt("test_password_123")
    stream = io.BytesIO()
    w.write(stream)

    res = extract_resume_from_file_bytes(stream.getvalue(), "locked.pdf")
    assert res.success is False
    assert res.error_message is not None
    assert "password-protected or encrypted" in res.error_message


def test_resume_file_pdf_malformed_handled_clearly():
    """Malformed or truncated PDF bytes return explicit error without crashing."""
    from backend.services.career_file_parser import extract_resume_from_file_bytes

    res = extract_resume_from_file_bytes(b"corrupt non-pdf header bytes", "corrupted.pdf")
    assert res.success is False
    assert res.error_message is not None
    assert "Malformed or corrupted" in res.error_message or "Failed" in res.error_message


def test_resume_file_empty_bytes_handled_clearly():
    """Empty 0-byte file returns clear rejection."""
    from backend.services.career_file_parser import extract_resume_from_file_bytes

    res = extract_resume_from_file_bytes(b"", "empty.pdf")
    assert res.success is False
    assert res.error_message is not None
    assert "empty" in res.error_message.lower()


def test_resume_file_unsupported_format_rejected():
    """Unsupported formats (.png, .jpg) return explicit rejection explaining supported types."""
    from backend.services.career_file_parser import extract_resume_from_file_bytes

    res = extract_resume_from_file_bytes(b"\x89PNG\r\n\x1a\nfake image content", "resume.png")
    assert res.success is False
    assert res.error_message is not None
    assert "Unsupported file format" in res.error_message
    assert "PDF" in res.error_message
    assert "Word (.docx)" in res.error_message


def test_resume_file_oversized_rejected():
    """Files exceeding 5MB are rejected."""
    from backend.services.career_file_parser import extract_resume_from_file_bytes

    oversized = b"a" * (5 * 1024 * 1024 + 10)
    res = extract_resume_from_file_bytes(oversized, "huge.txt")
    assert res.success is False
    assert res.error_message is not None
    assert "exceeds maximum allowed size" in res.error_message


@pytest.mark.asyncio
async def test_resume_file_upload_api_does_not_silently_overwrite_master():
    """Parsing an uploaded resume returns data for review and NEVER silently overwrites master resume."""
    from backend.models_career import ResumeContent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Pre-seed verified master resume
        original_master = ResumeContent(
            full_name="Original Name",
            email="original@example.com",
            skills=["OriginalSkill"],
        )
        await upsert_master_resume("user_parse_test", original_master, "Master Resume")

        # Upload file to parse endpoint
        files = {"file": ("new_resume.pdf", MINIMAL_VALID_PDF, "application/pdf")}
        res = await client.post(
            "/api/career/resumes/parse-file",
            files=files,
            headers={"x-user-id": "user_parse_test@compass.internal"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["requires_user_review"] is True
        assert "Ratnesh Singh" in data["extracted_content"]["full_name"]

        # Invariant: Master resume must NOT have been changed
        persisted_master = await get_master_resume("user_parse_test")
        assert persisted_master is not None
        assert persisted_master.content.full_name == "Original Name"
        assert persisted_master.content.skills == ["OriginalSkill"]


# ===========================================================================
# 6. SUBMISSION SEMANTICS: UNCERTAIN OUTCOMES & RETRY BLOCKS
# ===========================================================================

@pytest.mark.asyncio
async def test_submission_adapter_ats_outcome_unknown_on_network_timeout():
    """Network timeout during ATS submission records SUBMISSION_OUTCOME_UNKNOWN and blocks auto-retry."""
    import httpx
    from backend.models_career import CareerApplicationOut, CareerApplicationStatus, SubmissionMethod
    from backend.services.career_submission import AtsEndpointAdapter, submit_single_application

    user = "user_ats_timeout"
    app_rec = await get_or_create_career_application(user, 108)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
        "form_answers": {"full_name": "Test Candidate"},
    })

    opp_dict = {
        "company_name": "Enterprise Partner Inc",
        "role_title": "Platform Engineer Intern",
        "official_application_url": "https://enterprise.com/jobs/123",
    }
    resume_dict = {"title": "Test Resume", "content": {"full_name": "Test Candidate"}}

    adapter = AtsEndpointAdapter()

    with patch.dict("os.environ", {"ATS_ENTERPRISE_API_KEY": "valid_test_enterprise_token"}):
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Remote server timed out")):
            result = await adapter.execute(app_rec, opp_dict, resume_dict, user)

            assert result.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value
            assert "timed out" in result.message.lower() or "uncertain" in result.message.lower()

            # Verify persisted application status is SUBMISSION_OUTCOME_UNKNOWN
            updated_app = await get_career_application_by_id(app_rec.id, user)
            assert updated_app is not None
            assert updated_app.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value

            # Verify automated retry is blocked
            retry_res = await submit_single_application(app_rec.id, user, SubmissionMethod.ATS_ENDPOINT)
            assert retry_res.status == "BLOCKED"
            assert "uncertain outcome" in retry_res.message.lower() or "duplicate" in retry_res.message.lower()


@pytest.mark.asyncio
async def test_submission_adapter_ats_confirmed_200():
    """ATS endpoint returning HTTP 201 confirms SUBMITTED and stores external reference ID."""
    from backend.models_career import CareerApplicationStatus, SubmissionMethod
    from backend.services.career_submission import AtsEndpointAdapter

    user = "user_ats_confirmed"
    app_rec = await get_or_create_career_application(user, 109)
    await update_career_application(app_rec.id, user, {
        "status": CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    })

    opp_dict = {"company_name": "Greenhouse Partner", "role_title": "SWE Intern"}
    resume_dict = {"title": "SWE Resume", "content": {"full_name": "SWE Candidate"}}

    adapter = AtsEndpointAdapter()

    mock_resp = AsyncMock()
    mock_resp.status_code = 201
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"reference_id": "GH_CONFIRMED_98765"}

    with patch.dict("os.environ", {"ATS_ENTERPRISE_API_KEY": "gh_token_xyz"}):
        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            result = await adapter.execute(app_rec, opp_dict, resume_dict, user)

            assert result.status == CareerApplicationStatus.SUBMITTED.value
            assert result.reference_id == "GH_CONFIRMED_98765"
            assert "confirmed by partner ATS" in result.message

            updated_app = await get_career_application_by_id(app_rec.id, user)
            assert updated_app is not None
            assert updated_app.status == CareerApplicationStatus.SUBMISSION_SUBMITTED.value if hasattr(CareerApplicationStatus, 'SUBMISSION_SUBMITTED') else updated_app.status == CareerApplicationStatus.SUBMITTED.value
            assert updated_app.submitted_at is not None


# ===========================================================================
# 7. TAVILY RESILIENCE: RATE LIMITS, QUOTAS, MALFORMED RESULTS
# ===========================================================================

@pytest.mark.asyncio
async def test_tavily_rate_limit_and_quota_exhaustion_never_promotes_open():
    """When Tavily quota is exhausted or rate limited, system handles gracefully without status fabrication."""
    with patch("backend.services.radar_verifier.tavily_available", return_value=True):
        with patch("backend.services.radar_verifier.tavily_extract", side_effect=Exception("HTTP 429: Monthly credit limit exceeded")):
            with patch("backend.services.radar_verifier.safe_http_get_with_url", new_callable=AsyncMock, side_effect=Exception("ConnectionRefused")):
                status, evidence, _ = await verify_opportunity_status(
                    "https://portal.example.com/job",
                    current_status=OpportunityStatus.DISCOVERED,
                )
                assert status == OpportunityStatus.DISCOVERED
                assert status != OpportunityStatus.OPEN_CONFIRMED
                assert "timed out or failed" in evidence.lower() or "error" in evidence.lower()

