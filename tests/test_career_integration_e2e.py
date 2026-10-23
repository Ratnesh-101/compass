import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.models_career import ResumeContent, ResumeEducationItem
from backend.models_radar import (
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
    EligibilityClassification,
    UserOpportunityProfileOut,
)
from backend.services.radar_eligibility import evaluate_eligibility
from backend.services.radar_jobspy import format_compensation
from backend.services.radar_sources import infer_employer_type
from backend.services.radar_ats_adapters import is_india_or_remote
from backend.memory.career import upsert_master_resume, get_master_resume
from backend.memory.radar import get_user_opportunity_profile, _in_memory_opportunities


@pytest.fixture(autouse=True)
async def setup_e2e_environment(monkeypatch):
    import backend.memory.db as db_mod
    async def mock_get_pool():
        return None
    monkeypatch.setattr(db_mod, "get_pool", mock_get_pool)


@pytest.mark.asyncio
async def test_resume_studio_to_career_copilot_sync():
    """Verify that updating a master resume in Resume Studio updates Career Copilot matching."""
    transport = ASGITransport(app=app)
    user_id = "test_candidate_sync@example.com"
    headers = {"x-user-id": user_id}

    # 1. Update test candidate profile in Resume Studio workflow
    resume_payload = {
        "full_name": "Rohan Verma",
        "email": user_id,
        "phone": "+91 9123456789",
        "location": "Bengaluru, India",
        "education": [
            {
                "institution": "IIT Roorkee",
                "degree": "B.Tech",
                "field_of_study": "Computer Science",
                "end_year": 2026,
                "cgpa_or_grade": "9.1/10",
            }
        ],
        "skills": ["Python", "FastAPI", "React", "PostgreSQL", "Docker"],
        "projects": [
            {
                "title": "Autonomous Drone Navigation",
                "technologies": ["Python", "PyTorch"],
                "description": "Implemented optical flow obstacle avoidance.",
            }
        ],
        "experience": [],
    }

    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        # Save master resume via Resume Studio API
        save_resp = await client.put("/api/career/resumes/master", json=resume_payload)
        assert save_resp.status_code == 200

        # Confirm Resume Studio retrieved the master resume
        get_resume_resp = await client.get("/api/career/resumes/master")
        assert get_resume_resp.status_code == 200
        saved_data = get_resume_resp.json()
        assert saved_data["content"]["full_name"] == "Rohan Verma"

        # 2. Navigate to Career Copilot: Check Radar Candidate Profile endpoint
        profile_resp = await client.get("/api/opportunities/profile")
        assert profile_resp.status_code == 200
        radar_profile = profile_resp.json()
        assert radar_profile["degree"] == "B.Tech"
        assert radar_profile["grad_year"] == 2026
        assert radar_profile["cgpa"] == 9.1
        assert "FastAPI" in radar_profile["skills"]

        # 3. Update candidate skills in Resume Studio (adding 'Kubernetes')
        resume_payload["skills"].append("Kubernetes")
        update_resp = await client.put("/api/career/resumes/master", json=resume_payload)
        assert update_resp.status_code == 200

        # Confirm Career Copilot consumes the updated profile immediately
        refreshed_profile_resp = await client.get("/api/opportunities/profile")
        assert refreshed_profile_resp.status_code == 200
        refreshed_profile = refreshed_profile_resp.json()
        assert "Kubernetes" in refreshed_profile["skills"]


@pytest.mark.asyncio
async def test_controlled_eligibility_scenarios():
    """Verify all 5 required eligibility scenarios:
    - Satisfies all mandatory requirements
    - Fails a mandatory requirement
    - Insufficient evidence
    - Missing candidate profile
    - Remote role restricted to specific geography
    """
    reqs = OpportunityRequirementsOut(
        eligible_degree_types=["B.Tech"],
        eligible_academic_years=[3],
        eligible_graduation_years=[2026],
        eligible_countries=["India"],
        min_gpa=8.0,
        required_skills=["Python", "SQL"],
    )
    opp = OpportunityOut(
        id=501,
        company_name="Stripe India",
        normalized_company="stripe_india",
        role_title="Software Engineering Intern",
        canonical_url="https://stripe.com/jobs/501",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="India",
        is_india_eligible=True,
        requirements=reqs,
    )

    # Scenario 1: Candidate satisfying all mandatory requirements
    candidate_pass = UserOpportunityProfileOut(
        user_id="user_pass",
        degree="B.Tech",
        academic_year=3,
        grad_year=2026,
        cgpa=8.8,
        country_of_study="India",
        skills=["Python", "SQL", "Git"],
    )
    status1, exp1, reasons1 = evaluate_eligibility(opp, candidate_pass)
    assert status1 == EligibilityClassification.ELIGIBLE
    assert "Confirmed eligible" in exp1
    assert "Strong match" in exp1

    # Scenario 2: Candidate failing a mandatory requirement (e.g. CGPA < 8.0)
    candidate_fail_gpa = UserOpportunityProfileOut(
        user_id="user_fail_gpa",
        degree="B.Tech",
        academic_year=3,
        grad_year=2026,
        cgpa=7.2,  # Below 8.0
        country_of_study="India",
        skills=["Python", "SQL"],
    )
    status2, exp2, reasons2 = evaluate_eligibility(opp, candidate_fail_gpa)
    assert status2 == EligibilityClassification.INELIGIBLE
    assert "Ineligible" in exp2
    assert any(r.get("field") == "cgpa" and r.get("status") == "fail" for r in reasons2)

    # Scenario 3: Candidate with insufficient evidence (missing academic year and degree)
    candidate_incomplete = UserOpportunityProfileOut(
        user_id="user_incomplete",
        degree=None,
        academic_year=None,
        grad_year=None,
        skills=["Python"],
    )
    status3, exp3, reasons3 = evaluate_eligibility(opp, candidate_incomplete)
    assert status3 == EligibilityClassification.POTENTIAL_MATCH
    assert "Possible match" in exp3
    assert any(r.get("status") == "unknown" for r in reasons3)

    # Scenario 4: Missing candidate profile
    status4, exp4, reasons4 = evaluate_eligibility(opp, None)
    assert status4 == EligibilityClassification.INSUFFICIENT_INFORMATION
    assert "Resume Studio" in exp4

    # Scenario 5: Remote role restricted to specific geography (US-only remote)
    us_remote_location = "Remote - US Only"
    assert is_india_or_remote(us_remote_location) is False

    global_remote_location = "Remote - Worldwide"
    assert is_india_or_remote(global_remote_location) is True


@pytest.mark.asyncio
async def test_job_data_handling_boundaries():
    """Verify job data handling for malformed metadata, salary ranges, and external links."""
    # 1. Cleanse 'nan', 'null', 'undefined', 'none'
    opp = OpportunityOut(
        id=701,
        company_name="DeepTech AI",
        normalized_company="deeptech_ai",
        role_title="AI Research Intern",
        canonical_url="https://deeptech.example.com/jobs/701",
        current_status=OpportunityStatus.NEEDS_VERIFICATION,
        location="nan",
        work_arrangement="null",
        compensation="undefined",
        duration="none",
        employer_type="nan",
    )
    assert opp.location is None
    assert opp.work_arrangement is None
    assert opp.compensation is None
    assert opp.duration is None
    assert opp.employer_type is None

    # 2. Salary formatting guards
    assert format_compensation(0, 0, "INR", "month") is None
    assert format_compensation(float("nan"), float("nan"), "INR", "month") is None
    assert format_compensation(-5000, 0, "INR", "month") is None
    assert format_compensation(60000, 80000, "INR", "month") == "INR 60,000 - 80,000 / month"

    # 3. Unknown employer classification omitted
    assert infer_employer_type("CompletelyUnverifiedFirm", "randomhost123.com") is None

    # 4. Status distinction: Scraped listing is NEEDS_VERIFICATION
    assert opp.current_status == OpportunityStatus.NEEDS_VERIFICATION
    assert opp.is_verified_within_24h is False
