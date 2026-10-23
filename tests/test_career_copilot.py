"""
Compass — Career Copilot Test Suite.

Comprehensive unit and integration tests for:
1. Master Resume Management and Factual Integrity Engine.
2. Truthful Role Tailoring and Unsupported Claim Detection.
3. Strict Resume Validation Checklist & Status Transitions.
4. Application Lifecycle State Machine and Structured Answer Prefill.
5. Batch Preparation, Approval Gate, and Safe Submission Execution.
6. Manual Application Handoff Package Generation.
7. FastAPI Career Endpoints (/api/career/*).
8. AI Conversational Agent Grounded Skill Handlers.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.models_career import (
    BatchApproveRequest,
    BatchPrepareRequest,
    CareerApplicationOut,
    CareerApplicationStatus,
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
    ResumeOut,
    ResumeProjectItem,
    ResumeValidationReport,
    ResumeValidationStatus,
    SubmissionMethod,
)
from backend.models_radar import (
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
)
from backend.memory.radar import upsert_opportunity
from backend.services.career_resume import (
    draft_truthful_cover_letter,
    generate_resume_html,
    parse_uploaded_resume_text,
    tailor_resume_for_opportunity,
    validate_resume_against_master,
)
from backend.services.career_submission import (
    SUPPORTED_ADAPTERS,
    execute_batch_submission,
    generate_manual_application_package,
    submit_single_application,
)
from backend.memory.career import (
    approve_application_batch,
    create_application_batch,
    get_or_create_career_application,
    create_tailored_resume,
    get_application_batch,
    get_career_application_by_id,
    get_master_resume,
    get_resume_by_id,
    list_career_applications,
    list_resumes,
    update_career_application,
    upsert_master_resume,
)
from backend.skills.handlers.career import (
    handle_check_application_deadlines,
    handle_draft_cover_letter,
    handle_prepare_application,
    handle_submit_approved_application_batch,
    handle_tailor_resume,
    handle_track_career_applications,
)


# ===========================================================================
# FIXTURES: RADAR ISOLATION & TEST OPPORTUNITY SEEDING
# ===========================================================================

@pytest.fixture(autouse=True)
async def setup_career_copilot_environment():
    """Ensure radar pool state is reset and opportunities 1000-1005 exist for copilot lifecycle tests."""
    import backend.memory.radar as radar_mem
    from backend.memory.db import get_pool
    radar_mem._db_pool_available = True
    try:
        pool = await get_pool()
    except Exception:
        pool = None
    if pool:
        try:
            async with pool.acquire() as conn:
                for oid in range(1000, 1006):
                    await conn.execute(
                        """
                        INSERT INTO opportunities (
                            id, company_name, normalized_company, role_title,
                            opportunity_type, category, location, work_arrangement,
                            country, is_india_eligible, canonical_url, official_application_url,
                            current_status, description, created_at, updated_at
                        ) VALUES (
                            $1, 'Google India', 'google_india', 'Software Engineering Intern',
                            'internship', 'general', 'Bengaluru, India', 'hybrid', 'India', TRUE,
                            $2, $2, 'DISCOVERED', 'Test opportunity description', now(), now()
                        )
                        ON CONFLICT (id) DO NOTHING;
                        """,
                        oid,
                        f"https://careers.google.com/jobs/results/swe-intern-test-app-{oid}",
                    )
        except Exception:
            pass
    for oid in range(1000, 1006):
        radar_mem._in_memory_opportunities[oid] = {
            "id": oid,
            "company_name": "Google India",
            "normalized_company": "google_india",
            "role_title": "Software Engineering Intern",
            "opportunity_type": "internship",
            "category": "general",
            "location": "Bengaluru, India",
            "work_arrangement": "hybrid",
            "country": "India",
            "is_india_eligible": True,
            "canonical_url": f"https://careers.google.com/jobs/results/swe-intern-test-app-{oid}",
            "official_application_url": f"https://careers.google.com/jobs/results/swe-intern-test-app-{oid}",
            "current_status": "DISCOVERED",
        }


# ===========================================================================
# 1. Truthful Resume & Factual Validation Tests
# ===========================================================================

def test_resume_factual_validation_passes_for_supported_claims():
    """Resume with only truthful, verified profile content passes validation."""
    master = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        phone="+91 9876543210",
        location="India",
        education=[
            ResumeEducationItem(
                institution="IIT Delhi",
                degree="B.Tech",
                field_of_study="Computer Science",
                end_year=2027,
                cgpa_or_grade="8.9/10",
            )
        ],
        skills=["Python", "PyTorch", "FastAPI", "React", "PostgreSQL"],
        projects=[
            ResumeProjectItem(
                title="Distributed Search Engine",
                technologies=["Python", "PostgreSQL"],
                description="Built a distributed search engine supporting vector indexing.",
            )
        ],
        experience=[
            ResumeExperienceItem(
                company="OpenSource Org",
                role_title="Student Contributor",
                start_date="2025-05",
                end_date="2025-08",
                highlights=["Contributed core performance optimizations to streaming parser."],
            )
        ],
    )

    tailored = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        phone="+91 9876543210",
        location="India",
        education=master.education,
        skills=["Python", "PyTorch", "FastAPI"],
        projects=master.projects,
        experience=master.experience,
    )

    report = validate_resume_against_master(tailored, master)
    assert report.is_valid is True
    assert len(report.unsupported_claims) == 0
    assert len(report.missing_fields) == 0


def test_resume_factual_validation_blocks_unsupported_skills():
    """Detects when tailored resume injects skills not present in master resume."""
    master = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        skills=["Python", "PyTorch"],
        education=[ResumeEducationItem(institution="IIT", degree="B.Tech")],
        projects=[ResumeProjectItem(title="Search Engine", description="Indexed web pages.")],
    )

    tailored = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        education=master.education,
        projects=master.projects,
        # Fabricated Rust and Kubernetes not present in master
        skills=["Python", "Rust", "Kubernetes"],
    )

    report = validate_resume_against_master(tailored, master)
    assert report.is_valid is False
    assert any("Rust" in c for c in report.unsupported_claims)
    assert any("Kubernetes" in c for c in report.unsupported_claims)


def test_resume_factual_validation_blocks_fabricated_projects():
    """Detects when tailored resume adds unverified projects."""
    master = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        education=[ResumeEducationItem(institution="IIT", degree="B.Tech")],
        skills=["Python"],
        projects=[
            ResumeProjectItem(title="Search Engine", description="Indexed web pages.")
        ],
    )

    tailored = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        education=master.education,
        skills=["Python"],
        projects=[
            ResumeProjectItem(title="Search Engine", description="Indexed web pages."),
            # Fabricated project
            ResumeProjectItem(title="Self-Driving Car Vision", description="Autonomous vehicle pipeline."),
        ],
    )

    report = validate_resume_against_master(tailored, master)
    assert report.is_valid is False
    assert any("Self-Driving Car Vision" in c for c in report.unsupported_claims)


def test_truthful_tailoring_aligns_without_fabrication():
    """Tailoring re-ranks verified skills and matches projects without manufacturing claims."""
    master = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        skills=["React", "Python", "PyTorch", "Node.js", "Docker"],
        education=[ResumeEducationItem(institution="IIT", degree="B.Tech")],
        projects=[
            ResumeProjectItem(
                title="ML Benchmark Suite",
                technologies=["PyTorch", "Python"],
                description="Evaluated transformer inference latency.",
            ),
            ResumeProjectItem(
                title="React Portfolio",
                technologies=["React", "CSS"],
                description="Responsive personal site.",
            ),
        ],
    )

    opp = OpportunityOut(
        id=101,
        company_name="Anthropic",
        normalized_company="Anthropic",
        role_title="Machine Learning Research Intern",
        opportunity_type="internship",
        category="ai_ml",
        canonical_url="https://anthropic.com/careers/intern",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="Remote",
        is_india_eligible=True,
        requirements=OpportunityRequirementsOut(
            required_skills=["Python", "PyTorch", "Transformer"],
            preferred_skills=["CUDA", "Distributed Systems"],
        ),
    )

    tailored_content, report, status = tailor_resume_for_opportunity(master, opp)
    # Primary skills should feature Python and PyTorch first
    assert tailored_content.skills[0] in ["Python", "PyTorch"]
    # Transformer was required by JD but not in master: must NOT be fabricated into skills
    assert "Transformer" not in tailored_content.skills
    assert report.is_valid is True
    assert status == ResumeValidationStatus.READY_FOR_REVIEW


def test_printable_resume_html_generation():
    """Generates clean ATS-friendly HTML document."""
    resume_out = ResumeOut(
        id=99,
        user_id="test_user",
        title="SWE Intern Resume",
        content=ResumeContent(
            full_name="Jane Doe",
            email="jane@example.com",
            skills=["Python", "FastAPI"],
        ),
    )
    html = generate_resume_html(resume_out)
    assert "<!DOCTYPE html>" in html
    assert "Jane Doe" in html
    assert "SWE Intern Resume" in html
    assert "Python" in html


# ===========================================================================
# 2. Application Pipeline & State Machine Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_application_lifecycle_and_handoff_package():
    """Validates application creation, status updates, and manual handoff package generation."""
    import uuid
    user_id = f"user_test_app_{uuid.uuid4().hex[:8]}"
    opp_id = await upsert_opportunity(
        "Google India",
        "Software Engineering Intern",
        f"https://careers.google.com/jobs/results/swe-intern-test-app-{uuid.uuid4().hex[:6]}",
    )
    app_record = await get_or_create_career_application(user_id, opp_id)
    assert app_record.id is not None
    assert app_record.status == CareerApplicationStatus.SAVED

    updated = await update_career_application(
        app_record.id,
        user_id,
        {
            "status": CareerApplicationStatus.READY_FOR_REVIEW.value,
            "form_answers": {
                "university": "IIT",
                "degree": "B.Tech Computer Science",
                "graduation_year": "2027",
                "work_authorization": "Eligible to work in India without sponsorship",
            },
        },
    )
    assert updated is not None
    assert updated.status == CareerApplicationStatus.READY_FOR_REVIEW

    # Generate manual handoff package
    opp_dict = {
        "company_name": "Google India",
        "role_title": "Software Engineering Intern",
        "canonical_url": "https://careers.google.com/jobs/results/swe-intern-test-app",
    }
    resume_dict = {
        "title": "Tailored SWE Resume",
        "content": {"full_name": "Ratnesh Singh", "email": "ratnesh@example.com", "skills": ["Python", "FastAPI"]},
    }
    pkg = generate_manual_application_package(updated, opp_dict, resume_dict)
    assert pkg["company_name"] == "Google India"
    assert pkg["portal_url"] == "https://careers.google.com/jobs/results/swe-intern-test-app"
    assert pkg["prefilled_answers"]["current_degree"] == "B.Tech Computer Science"
    assert len(pkg["submission_instructions"]) >= 4


# ===========================================================================
# 3. Batch Preparation & Explicit Approval Gate Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_batch_approval_security_gate():
    """Batch submission requires valid approval token and blocks unapproved attempts."""
    # 1. Create two applications
    opp1_id = await upsert_opportunity("Batch Corp 1", "Intern 1", "https://batch.corp/test-batch-1")
    opp2_id = await upsert_opportunity("Batch Corp 2", "Intern 2", "https://batch.corp/test-batch-2")
    app1 = await get_or_create_career_application("user_batch_test", opp1_id)
    app2 = await get_or_create_career_application("user_batch_test", opp2_id)

    # 2. Prepare batch
    batch_id = await create_application_batch("user_batch_test", [app1.id, app2.id])
    batch_data = await get_application_batch(batch_id, "user_batch_test")
    assert batch_data is not None
    assert batch_data["status"] == "DRAFT"

    # 3. Attempt execution without approval -> Must be blocked by submit_single_application
    blocked_item = await submit_single_application(app1.id, "user_batch_test", SubmissionMethod.MANUAL_HANDOFF)
    assert blocked_item.status == "BLOCKED"
    assert "not been explicitly reviewed and approved" in blocked_item.message

    # 4. Proper explicit approval
    approval_success = await approve_application_batch(batch_id, "user_batch_test", "token_test_123")
    assert approval_success is True

    # Verify application status transitioned
    app1_approved = await get_career_application_by_id(app1.id, "user_batch_test")
    assert app1_approved is not None
    assert app1_approved.status == CareerApplicationStatus.APPROVED_FOR_SUBMISSION

    # 5. Execute approved batch -> Succeeds safely with adapter execution
    batch_data_approved = await get_application_batch(batch_id, "user_batch_test")
    assert batch_data_approved is not None
    results = await execute_batch_submission("user_batch_test", batch_data_approved, SubmissionMethod.MANUAL_HANDOFF)
    assert len(results) == 2
    assert results[0].status == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value
    assert results[0].manual_package is not None


# ===========================================================================
# 4. FastAPI Career Endpoints Integration Tests
# ===========================================================================

@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_career_api_endpoints():
    """Validates FastAPI routes across master resume, tailoring, applications, and batching."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "candidate@example.com"}) as client:
        # 1. Update Master Resume
        master_payload = {
            "full_name": "Test Candidate",
            "email": "candidate@example.com",
            "phone": "+91 9999988888",
            "location": "Bengaluru, India",
            "skills": ["Python", "FastAPI", "React", "PostgreSQL"],
            "education": [
                {
                    "institution": "BITS Pilani",
                    "degree": "B.E.",
                    "field_of_study": "Computer Science",
                    "end_year": 2027,
                    "cgpa_or_grade": "9.1/10",
                }
            ],
            "projects": [
                {
                    "title": "Compass Platform",
                    "technologies": ["FastAPI", "React"],
                    "description": "Autonomous career copilot with truthful resume studio.",
                }
            ],
            "experience": [],
            "achievements": [],
            "certifications": [],
        }
        res_master = await client.put("/api/career/resumes/master", json=master_payload)
        assert res_master.status_code == 200
        assert res_master.json()["title"] == "Master Resume"
        assert res_master.json()["content"]["full_name"] == "Test Candidate"

        # 2. Get Master Resume
        get_master = await client.get("/api/career/resumes/master")
        assert get_master.status_code == 200
        assert get_master.json()["content"]["skills"] == ["Python", "FastAPI", "React", "PostgreSQL"]

        # 3. Create or Seed an opportunity first to tailor against
        # Use existing radar sync to ensure an opportunity exists
        await client.post("/api/opportunities/sync?source=curated")
        opps_res = await client.get("/api/opportunities")
        assert opps_res.status_code == 200
        opp_list = opps_res.json()["opportunities"]
        opp_id = opp_list[0]["id"] if opp_list else 1

        # Request Tailoring for an Opportunity
        tailor_res = await client.post(
            "/api/career/resumes/tailor",
            json={
                "opportunity_id": opp_id,
                "custom_title": "Tailored Engineering Resume",
                "target_skills_emphasis": ["Python", "PostgreSQL"],
            },
        )
        assert tailor_res.status_code == 200
        tailored_data = tailor_res.json()
        assert tailored_data["opportunity_id"] == opp_id
        resume_id = tailored_data["id"]

        # 4. Export Printable HTML
        export_res = await client.get(f"/api/career/resumes/{resume_id}/export/html")
        assert export_res.status_code == 200
        assert "<!DOCTYPE html>" in export_res.text
        assert "Test Candidate" in export_res.text

        # 5. List Resumes
        resumes_list_res = await client.get("/api/career/resumes")
        assert resumes_list_res.status_code == 200
        assert len(resumes_list_res.json()) >= 1

        # 6. Check Registered Submission Adapters
        adapters_res = await client.get("/api/career/adapters")
        assert adapters_res.status_code == 200
        adapters = adapters_res.json()
        assert any(a["adapter_id"] == "manual_handoff" for a in adapters)
        assert any(a["adapter_id"] == "ats_endpoint" for a in adapters)

        # 7. Create Application Record
        app_res = await client.post(
            f"/api/career/applications/{opp_id}",
            params={"resume_id": resume_id},
        )
        assert app_res.status_code == 200
        app_data = app_res.json()
        app_id = app_data["id"]

        # 8. Update Application Status to Ready for Review
        patch_res = await client.patch(
            f"/api/career/applications/{app_id}",
            json={
                "status": "READY_FOR_APPROVAL",
                "form_answers": {"university": "BITS Pilani", "degree": "B.E."},
            },
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "READY_FOR_APPROVAL"

        # 9. Prepare Batch Review
        batch_prep = await client.post("/api/career/batches/prepare", json={"opportunity_ids": [opp_id]})
        assert batch_prep.status_code == 200
        batch_info = batch_prep.json()
        batch_id = batch_info["batch_id"]

        # 10. Approve Batch
        approve_res = await client.post(
            f"/api/career/batches/{batch_id}/approve",
            json={
                "batch_id": batch_id,
                "attestation_confirmed": True,
                "work_auth_confirmed": True,
                "legal_statements_accepted": True,
            },
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["status"] == "APPROVED"

        # 11. Submit Approved Batch
        submit_res = await client.post(
            f"/api/career/batches/{batch_id}/submit",
            json={"batch_id": batch_id},
        )
        assert submit_res.status_code == 200
        submit_data = submit_res.json()
        assert submit_data["total_processed"] >= 1


# ===========================================================================
# 5. AI Conversational Agent Grounded Skill Execution Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_ai_career_skill_handlers():
    """Tests the specialized career tools invoked by Compass ReAct agent."""
    # Seed an opportunity first
    opp_id = await upsert_opportunity(
        company_name="Uber",
        role_title="Software Engineering Intern",
        canonical_url="https://uber.com/jobs/swe-intern-2026-test",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        category="swe",
        country="India",
        is_india_eligible=True,
    )

    # 1. handle_tailor_resume
    tailor_out = await handle_tailor_resume(
        {
            "opportunity_id": opp_id,
            "custom_title": "Tailored Skill Test",
            "skills_emphasis": ["Python"],
            "user_id": "user_skill_test",
        }
    )
    assert tailor_out["success"] is True
    assert "resume_id" in tailor_out
    assert "summary" in tailor_out

    # 2. handle_prepare_application
    prep_out = await handle_prepare_application(
        {
            "opportunity_id": opp_id,
            "user_id": "user_skill_test",
        }
    )
    assert prep_out["success"] is True
    assert "application_id" in prep_out

    # 3. handle_track_career_applications
    track_out = await handle_track_career_applications({"user_id": "user_skill_test"})
    assert track_out["success"] is True
    assert track_out["count"] >= 1

    # 4. handle_submit_approved_application_batch without approval -> returns error
    submit_fail = await handle_submit_approved_application_batch(
        {"batch_id": "non_existent_batch", "user_id": "user_skill_test"}
    )
    assert submit_fail["success"] is False


def test_resume_raw_text_parsing_extracts_truthfully():
    """Resume text parser extracts name, contact info, skills, and projects without inventing unverified facts."""
    sample_text = """
    Aakash Verma
    aakash.v@example.com | +91 91234 56789 | Bengaluru, India
    github.com/aakash-v | linkedin.com/in/aakash-v

    Professional Summary
    Undergraduate CS student passionate about distributed systems and machine learning pipelines.

    Education
    B.Tech in Computer Science and Engineering, 2026

    Technical Skills
    Python, C++, PyTorch, Docker, PostgreSQL, Redis, Git

    Projects
    High-Throughput Vector DB: Built an in-memory vector similarity index using HNSW and Python.
    Autonomous Rover Controller: Implemented trajectory planning and ROS2 communication.
    """

    parsed = parse_uploaded_resume_text(sample_text)
    assert parsed.full_name == "Aakash Verma"
    assert parsed.email == "aakash.v@example.com"
    assert parsed.phone == "+91 91234 56789"
    assert parsed.location == "Bengaluru, India"
    assert "Python" in parsed.skills
    assert "PyTorch" in parsed.skills
    assert len(parsed.education) >= 1
    assert (
        (parsed.education[0].field_of_study and "Computer Science" in parsed.education[0].field_of_study)
        or (parsed.education[0].degree and "Computer Science" in parsed.education[0].degree)
        or "Computer Science" in parsed.education[0].institution
    )
    assert len(parsed.projects) >= 1


def test_truthful_cover_letter_grounding():
    """Cover letter drafting strictly references real projects and skills without inventing accomplishments."""
    master = ResumeContent(
        full_name="Ratnesh Singh",
        email="ratnesh@example.com",
        phone="+91 9876543210",
        location="India",
        education=[
            ResumeEducationItem(
                institution="IIT Delhi",
                degree="B.Tech Computer Science",
                field_of_study="Computer Science",
                end_year=2027,
            )
        ],
        skills=["Python", "FastAPI", "PostgreSQL", "PyTorch"],
        projects=[
            ResumeProjectItem(
                title="Compass AI Operating System",
                technologies=["FastAPI", "Python", "SQLite"],
                description="Built a full-stack context copilot with long-term memory.",
            )
        ],
    )

    opp = OpportunityOut(
        id=2001,
        company_name="Google",
        normalized_company="google",
        role_title="Software Engineering Intern",
        opportunity_type="internship",
        canonical_url="https://google.com/jobs/intern-swe",
        official_application_url="https://google.com/jobs/intern-swe",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        category="swe",
        country="India",
        is_india_eligible=True,
    )

    letter_text, verified_projs, verified_skls = draft_truthful_cover_letter(master, opp)

    assert "Google" in letter_text
    assert "Software Engineering Intern" in letter_text
    assert "Compass AI Operating System" in letter_text
    assert "Compass AI Operating System" in verified_projs
    assert "Python" in verified_skls or "FastAPI" in verified_skls
    # Invariant: No fabricated awards or unverified claims
    assert "Gold Medal" not in letter_text
    assert "PhD" not in letter_text


@pytest.mark.asyncio
async def test_ai_career_skills_cover_letter_and_deadlines():
    """Verify handle_draft_cover_letter and handle_check_application_deadlines handlers."""
    opp_id = await upsert_opportunity(
        company_name="Microsoft",
        role_title="Research Intern",
        canonical_url="https://microsoft.com/jobs/research-intern-2026",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        category="research",
        country="India",
        is_india_eligible=True,
    )

    # 1. Draft Cover Letter Skill
    letter_res = await handle_draft_cover_letter({
        "opportunity_id": opp_id,
        "user_id": "test_agent_user",
    })
    assert letter_res["success"] is True
    assert "Microsoft" in letter_res["cover_letter"]
    assert "summary" in letter_res

    # 2. Check Deadlines Skill
    deadlines_res = await handle_check_application_deadlines({
        "days_ahead": 60,
        "user_id": "test_agent_user",
    })
    assert deadlines_res["success"] is True
    assert "upcoming_deadlines" in deadlines_res
    assert "summary" in deadlines_res


@pytest.mark.asyncio
async def test_career_api_cover_letter_and_upload_endpoints():
    """FastAPI integration tests for resume upload parsing and cover letter drafting."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "priya@example.com"}) as client:
        # 1. Parse upload endpoint
        parse_res = await client.post(
            "/api/career/resumes/parse-upload",
            json={
                "raw_text": "Priya Sharma\npriya@example.com | +91 98765 00000\nSkills: Python, React, Docker"
            },
        )
        assert parse_res.status_code == 200
        parsed_data = parse_res.json()
        assert parsed_data["full_name"] == "Priya Sharma"
        assert parsed_data["email"] == "priya@example.com"
        assert "Python" in parsed_data["skills"]

        # 2. Seed opportunity
        opp_id = await upsert_opportunity(
            company_name="Adobe",
            role_title="Product Intern",
            canonical_url="https://adobe.com/jobs/product-intern-2026",
            current_status=OpportunityStatus.OPEN_CONFIRMED,
            category="swe",
            country="India",
            is_india_eligible=True,
        )

        # 3. Draft cover letter endpoint
        draft_res = await client.post(
            "/api/career/cover-letters/draft",
            json={"opportunity_id": opp_id},
        )
        assert draft_res.status_code == 200
        draft_data = draft_res.json()
        assert "Adobe" in draft_data["company_name"]
        assert len(draft_data["content"]) > 50

        # 4. Attach cover letter to application
        prep_res = await client.post(f"/api/career/applications/{opp_id}")
        assert prep_res.status_code == 200
        app_id = prep_res.json()["id"]

        attach_res = await client.post(
            f"/api/career/applications/{app_id}/cover-letter",
            json={"cover_letter": "Custom tailored truthful cover letter content."},
        )
        assert attach_res.status_code == 200
        attached_data = attach_res.json()
        assert attached_data["cover_letter"] == "Custom tailored truthful cover letter content."

