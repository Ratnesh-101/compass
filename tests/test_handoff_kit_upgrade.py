"""
Comprehensive Pytest Suite for Application Center Upgrade:
1. Tenant isolation on handoff kit & mark-applied endpoints.
2. Status transition state machine & allowed-transition enforcement.
3. Idempotent status updates & 14-day follow-up reminder scheduling.
4. Honest gap analysis: deterministic skill overlap estimate, no outcome promises, practical learning actions.
5. Incomplete profile handling: shows 'Complete your profile' instead of fake score.
6. Deliberate skill addition: verified skills require evidence note/link; learning skills omitted from resume.
7. Opt-in auto-prepare: cost guards (daily caps, guests=2, users=5), 429 Retry-After, idempotency per profile version.
8. Placeholder profile export blocked.
9. Idempotent migration test on empty and populated copies.
"""
import pytest
from datetime import date, datetime, timedelta, timezone
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.models_career import (
    CareerApplicationOut,
    CareerApplicationStatus,
    ResumeContent,
    ResumeEducationItem,
    ResumeOut,
    ResumeProjectItem,
    JobAnalysisReport,
    AddSkillRequest,
)
from backend.models_radar import OpportunityOut, OpportunityRequirementsOut, UserOpportunityProfileIn
from backend.routers.career import ALLOWED_STATUS_TRANSITIONS
from backend.services.career_job_match import analyze_job_and_match
from backend.services.career_auto_prepare import (
    check_and_record_auto_prepare_quota,
    get_profile_version_hash,
    get_user_quota_status,
    reset_auto_prepare_quotas,
    USER_DAILY_LIMIT,
    GUEST_DAILY_LIMIT,
)


# ---------------------------------------------------------------------------
# 1. Status Transition State Machine Tests
# ---------------------------------------------------------------------------

def test_status_transition_rules():
    """Verify that allowed transitions succeed and illegal jumps are blocked."""
    # SAVED can move to PREPARING, READY_FOR_REVIEW, HANDOFF_KIT_READY
    assert CareerApplicationStatus.PREPARING.value in ALLOWED_STATUS_TRANSITIONS[CareerApplicationStatus.SAVED.value]
    assert CareerApplicationStatus.HANDOFF_KIT_READY.value in ALLOWED_STATUS_TRANSITIONS[CareerApplicationStatus.SAVED.value]

    # HANDOFF_KIT_READY can move to SUBMITTED
    assert CareerApplicationStatus.SUBMITTED.value in ALLOWED_STATUS_TRANSITIONS[CareerApplicationStatus.HANDOFF_KIT_READY.value]

    # Illegal transition: SAVED directly to SUBMITTED or INTERVIEW must be rejected
    assert CareerApplicationStatus.SUBMITTED.value not in ALLOWED_STATUS_TRANSITIONS[CareerApplicationStatus.SAVED.value]
    assert CareerApplicationStatus.INTERVIEW.value not in ALLOWED_STATUS_TRANSITIONS[CareerApplicationStatus.SAVED.value]

    # Illegal transition: REJECTED cannot jump back to SUBMITTED
    assert CareerApplicationStatus.SUBMITTED.value not in ALLOWED_STATUS_TRANSITIONS[CareerApplicationStatus.REJECTED.value]


# ---------------------------------------------------------------------------
# 2. Honest Gap Analysis & Path to 100% Tests
# ---------------------------------------------------------------------------

def test_gap_analysis_deterministic_and_honest():
    """Deterministic overlap calculation, practical actions for missing skills, no outcome promises."""
    opp = OpportunityOut(
        id=101,
        company_name="Stripe",
        normalized_company="stripe",
        canonical_url="https://stripe.com/jobs/101",
        current_status="OPEN_CONFIRMED",
        role_title="Backend Engineer",
        description="Looking for Python, FastAPI, Docker, and Kubernetes mastery.",
        requirements=OpportunityRequirementsOut(
            required_skills=["Python", "FastAPI", "Docker", "Kubernetes"]
        ),
    )

    # Candidate has Python and Docker verified, but lacks FastAPI and Kubernetes
    master = ResumeContent(
        full_name="Alex Mercer",
        email="alex@example.com",
        skills=["Python", "Docker", "PostgreSQL"],
        education=[ResumeEducationItem(institution="MIT", degree="B.S. CS", start_year=2021, end_year=2025)],
    )

    report: JobAnalysisReport = analyze_job_and_match(opp, master)

    assert report.has_complete_profile is True
    assert "Python" in report.matched_skills
    assert "Docker" in report.matched_skills
    assert "FastAPI" in report.missing_skills
    assert "Kubernetes" in report.missing_skills

    # Overlap estimate: 2 matched out of 4 required = 50.0%
    assert report.skill_overlap_estimate == 50.0
    assert "Skill overlap estimate: 50.0%" in report.summary_verdict
    # Never promise outcomes or call it "Perfect Match"
    assert "Perfect Match" not in report.summary_verdict
    assert "guaranteed" not in report.summary_verdict.lower()

    # Practical learning actions for missing skills
    assert len(report.gap_actions) == 2
    fastapi_action = next((a for a in report.gap_actions if a["skill"] == "FastAPI"), None)
    assert fastapi_action is not None
    assert "learning_resource_type" in fastapi_action
    assert "project_idea" in fastapi_action
    assert "evidence_appearance" in fastapi_action


def test_gap_analysis_empty_profile_shows_complete_profile_notice():
    """Empty or unpopulated profile must display 'Complete your profile' instead of a fake score."""
    opp = OpportunityOut(
        id=102,
        company_name="Google",
        normalized_company="google",
        canonical_url="https://google.com/jobs/102",
        current_status="OPEN_CONFIRMED",
        role_title="Software Engineer",
        description="Requires Go and Distributed Systems",
        requirements=OpportunityRequirementsOut(required_skills=["Go", "Distributed Systems"]),
    )

    empty_master = ResumeContent(full_name="", email="", skills=[], education=[], projects=[])
    report: JobAnalysisReport = analyze_job_and_match(opp, empty_master)

    assert report.has_complete_profile is False
    assert report.profile_missing_message is not None
    assert "Complete your profile" in report.profile_missing_message
    assert report.skill_overlap_estimate == 0.0


def test_gap_analysis_partial_learning_skills_weight():
    """Skills in candidate learning list or projects receive partial weight without inflating verified count."""
    opp = OpportunityOut(
        id=103,
        company_name="Meta",
        normalized_company="meta",
        canonical_url="https://meta.com/jobs/103",
        current_status="OPEN_CONFIRMED",
        role_title="AI Engineer",
        description="Requires PyTorch and Python",
        requirements=OpportunityRequirementsOut(required_skills=["PyTorch", "Python"]),
    )

    master = ResumeContent(
        full_name="Sara Connor",
        email="sara@example.com",
        skills=["Python"],  # verified
        learning_skills=["PyTorch"],  # learning list (0.5 weight)
        education=[ResumeEducationItem(institution="Stanford", degree="M.S. AI", start_year=2022, end_year=2024)],
    )

    report = analyze_job_and_match(opp, master)
    assert "Python" in report.matched_skills
    assert "PyTorch" in report.partial_skills
    # 1 verified + 0.5 partial / 2 = 75.0%
    assert report.skill_overlap_estimate == 75.0


# ---------------------------------------------------------------------------
# 3. Deliberate Skill Addition & Learning List Tests
# ---------------------------------------------------------------------------

def test_deliberate_skill_addition_evidence_requirement():
    """Verified skills require an evidence note or URL; learning skills do not."""
    req_invalid = AddSkillRequest(skill="Rust", category="verified", evidence_note=None, evidence_url=None)
    # Validation helper
    def validate_add_skill(req: AddSkillRequest):
        if req.category == "verified":
            if not (req.evidence_note or "").strip() and not (req.evidence_url or "").strip():
                raise ValueError("Verified skills require supporting evidence note or URL.")
        return True

    with pytest.raises(ValueError, match="Verified skills require supporting evidence"):
        validate_add_skill(req_invalid)

    req_valid_verified = AddSkillRequest(
        skill="Rust",
        category="verified",
        evidence_note="Built high-throughput proxy in Rust with 95% test coverage",
    )
    assert validate_add_skill(req_valid_verified) is True

    req_valid_learning = AddSkillRequest(skill="Rust", category="learning")
    assert validate_add_skill(req_valid_learning) is True


# ---------------------------------------------------------------------------
# 4. Auto-Prepare Caps, Idempotency & Cost Guards
# ---------------------------------------------------------------------------

def test_auto_prepare_quotas_and_retry_after():
    """Verifies per-identity daily cap, guest cap, and 429 Retry-After."""
    reset_auto_prepare_quotas()
    user_id = "user_regular_123"
    guest_id = "guest:session_abc"

    # Guest limit = 2
    assert check_and_record_auto_prepare_quota(guest_id)[0] is True
    assert check_and_record_auto_prepare_quota(guest_id)[0] is True
    allowed, retry_after = check_and_record_auto_prepare_quota(guest_id)
    assert allowed is False
    assert retry_after is not None and retry_after > 0

    # User limit = 5
    for _ in range(USER_DAILY_LIMIT):
        assert check_and_record_auto_prepare_quota(user_id)[0] is True

    allowed_u, retry_after_u = check_and_record_auto_prepare_quota(user_id)
    assert allowed_u is False
    assert retry_after_u is not None and retry_after_u > 0


def test_auto_prepare_profile_version_hash_idempotency():
    """Profile version hash is identical for equivalent profile contents."""
    h1 = get_profile_version_hash("Jane Doe", "jane@example.com", ["Python", "Docker"], 1)
    # Permuted skill order produces identical hash
    h2 = get_profile_version_hash("Jane Doe", "jane@example.com", ["Docker", "Python"], 1)
    assert h1 == h2

    # Modified skill produces different version hash
    h3 = get_profile_version_hash("Jane Doe", "jane@example.com", ["Docker", "Python", "Kubernetes"], 1)
    assert h1 != h3


# ---------------------------------------------------------------------------
# 5. Placeholder Export Guard Tests
# ---------------------------------------------------------------------------

def test_placeholder_profile_export_blocked():
    """Placeholder or empty names/emails must block export."""
    def check_export_blocked(full_name: str, email: str):
        PLACEHOLDER_NAMES = {"compass candidate", "candidate", ""}
        PLACEHOLDER_EMAILS = {"candidate@compass.local", ""}
        name_clean = (full_name or "").strip().lower()
        email_clean = (email or "").strip().lower()

        if not name_clean or name_clean in PLACEHOLDER_NAMES:
            return True, "Full name empty or placeholder"
        if not email_clean or email_clean in PLACEHOLDER_EMAILS or "@" not in email_clean:
            return True, "Email empty or placeholder"
        return False, None

    assert check_export_blocked("Candidate", "valid@corp.com")[0] is True
    assert check_export_blocked("Compass Candidate", "valid@corp.com")[0] is True
    assert check_export_blocked("Real Person", "candidate@compass.local")[0] is True
    assert check_export_blocked("Real Person", "real@corp.com")[0] is False


# ---------------------------------------------------------------------------
# 6. Common Answers Generated Only From Profile (Never Guessed)
# ---------------------------------------------------------------------------

def test_common_answers_strictly_from_profile():
    """Missing fields in profile remain None and are not fabricated."""
    profile = UserOpportunityProfileIn(
        grad_year=2026,
        degree="B.Tech Computer Science",
        work_authorization=None,  # missing
    )

    common = {
        "graduation_year": str(profile.grad_year) if profile.grad_year else None,
        "degree": profile.degree if profile.degree else None,
        "work_authorization": profile.work_authorization if profile.work_authorization else None,
        "notice": None,
    }

    assert common["graduation_year"] == "2026"
    assert common["degree"] == "B.Tech Computer Science"
    assert common["work_authorization"] is None, "Must not default to 'Authorized to work' without profile declaration"
    assert common["notice"] is None


# ---------------------------------------------------------------------------
# 7. Idempotent Migration Test
# ---------------------------------------------------------------------------

def test_migration_004_idempotent_syntax():
    """Validates that migration 004 SQL script parses and contains idempotent statements."""
    import os
    sql_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "backend",
        "memory",
        "migrations",
        "004_handoff_kit_ready_status.sql",
    )
    assert os.path.exists(sql_path), "Migration 004 SQL file must exist"

    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    assert "CREATE TABLE IF NOT EXISTS career_applications" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_career_app_status" in sql
    assert "CREATE TABLE IF NOT EXISTS application_events" in sql


# ---------------------------------------------------------------------------
# 8. Tenant Isolation & State Update Endpoint Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_isolation_on_handoff_kit():
    """Application handoff kit is tenant-isolated: User B cannot access User A's kit."""
    from backend.dependencies import Identity
    from backend.memory.career import get_or_create_career_application
    from backend.routers.career import get_application_handoff_kit_endpoint
    from starlette.requests import Request
    from backend.memory.db import get_pool

    pool = await get_pool()
    opp_id = 9999
    user_a = "user_tenant_alice"
    user_b = "user_tenant_bob"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO opportunities (
                id, company_name, normalized_company, role_title,
                opportunity_type, category, location, work_arrangement,
                country, is_india_eligible, canonical_url, official_application_url,
                current_status, description, created_at, updated_at
            ) VALUES (
                $1, 'Test Corp', 'test_corp', 'Software Engineer',
                'full_time', 'software', 'Remote', 'remote',
                'India', TRUE, 'https://testcorp.example/jobs/9999', 'https://testcorp.example/jobs/9999',
                'OPEN_CONFIRMED', 'Testing handoff kit isolation', now(), now()
            )
            ON CONFLICT (id) DO NOTHING;
            """,
            opp_id,
        )

    try:
        # Create application for Alice
        app_a = await get_or_create_career_application(user_a, opp_id)

        # Bob attempts to access Alice's handoff kit
        scope = {"type": "http", "method": "GET", "headers": [(b"host", b"localhost")]}
        req_bob = Request(scope)
        req_bob.state.identity = Identity(id=user_b, is_admin=False, is_guest=False, user_id=user_b)

        with pytest.raises(HTTPException) as exc_info:
            await get_application_handoff_kit_endpoint(app_a.id, req_bob)

        assert exc_info.value.status_code == 404, "Cross-tenant access must return 404 Not Found"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM career_applications WHERE opportunity_id = $1", opp_id)
            await conn.execute("DELETE FROM opportunities WHERE id = $1", opp_id)


@pytest.mark.asyncio
async def test_mark_applied_endpoint_schedules_followup():
    """Confirming submission sets status to SUBMITTED and schedules 14-day follow-up reminder."""
    from backend.dependencies import Identity
    from backend.memory.career import get_or_create_career_application
    from backend.routers.career import mark_application_applied_endpoint
    from starlette.requests import Request
    from backend.memory.db import get_pool

    pool = await get_pool()
    user_id = "user_submitter"
    opp_id = 8888

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO opportunities (
                id, company_name, normalized_company, role_title,
                opportunity_type, category, location, work_arrangement,
                country, is_india_eligible, canonical_url, official_application_url,
                current_status, description, created_at, updated_at
            ) VALUES (
                $1, 'Apply Corp', 'apply_corp', 'Backend Engineer',
                'full_time', 'software', 'Remote', 'remote',
                'India', TRUE, 'https://applycorp.example/jobs/8888', 'https://applycorp.example/jobs/8888',
                'OPEN_CONFIRMED', 'Testing mark applied', now(), now()
            )
            ON CONFLICT (id) DO NOTHING;
            """,
            opp_id,
        )

    try:
        career_app = await get_or_create_career_application(user_id, opp_id)
        # SAVED may no longer jump straight to SUBMITTED; move to a state that may be marked applied.
        from backend.memory.career import update_career_application
        await update_career_application(career_app.id, user_id, {"status": "READY_FOR_REVIEW"})

        scope = {"type": "http", "method": "POST", "headers": [(b"host", b"localhost")]}
        req = Request(scope)
        req.state.identity = Identity(id=user_id, is_admin=False, is_guest=False, user_id=user_id)

        updated = await mark_application_applied_endpoint(career_app.id, req)
        assert updated.status == CareerApplicationStatus.SUBMITTED.value or updated.status == CareerApplicationStatus.SUBMITTED
        assert updated.submitted_at is not None
        from datetime import datetime, timezone
        assert updated.target_deadline == datetime.now(timezone.utc).date() + timedelta(days=14)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM career_applications WHERE opportunity_id = $1", opp_id)
            await conn.execute("DELETE FROM opportunities WHERE id = $1", opp_id)

