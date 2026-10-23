import pytest
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
from backend.memory.radar import derive_profile_from_master_resume


def test_malformed_metadata_sanitized_to_none():
    """Verify that 'nan', 'NaN', 'null', 'undefined', 'none' are cleansed to None."""
    opp = OpportunityOut(
        id=1,
        company_name="Acme Corp",
        normalized_company="acme_corp",
        role_title="Software Intern",
        canonical_url="https://example.com/job/1",
        current_status=OpportunityStatus.NEEDS_VERIFICATION,
        location="nan",
        work_arrangement="null",
        compensation="undefined",
        duration="none",
        category="NaN",
        employer_type="nan",
    )
    assert opp.location is None
    assert opp.work_arrangement is None
    assert opp.compensation is None
    assert opp.duration is None
    assert opp.category is None
    assert opp.employer_type is None


def test_salary_validation_and_formatting():
    """Valid salary intervals format cleanly; malformed or NaN values return None."""
    # Valid annual salary
    formatted = format_compensation(1200000, 1500000, "INR", "year")
    assert formatted == "INR 1,200,000 - 1,500,000 / year"

    # Valid monthly salary in INR
    formatted_monthly = format_compensation(40000, 60000, "INR", "month")
    assert formatted_monthly == "INR 40,000 - 60,000 / month"

    # Valid USD monthly
    formatted_usd = format_compensation(3000, 4000, "USD", "month")
    assert formatted_usd == "USD 3,000 - 4,000 / month"

    # Invalid / NaN / None values
    assert format_compensation(None, None, "INR", "year") is None
    assert format_compensation(float("nan"), float("nan"), "INR", "year") is None
    assert format_compensation(-1000, -500, "INR", "year") is None
    assert format_compensation(0, 0, "INR", "year") is None


def test_infer_employer_type_omits_unreliable_data():
    """infer_employer_type returns None when evidence is absent, never fabricating classifications."""
    assert infer_employer_type("Google LLC", "careers.google.com") == "enterprise"
    assert infer_employer_type("IIT Bombay", "iitb.ac.in") == "research"
    assert infer_employer_type("ISRO", "isro.gov.in") == "government"
    # Unverified company without clear signals should return None (omitted) rather than 'startup'
    assert infer_employer_type("RandomUnknownFirmXYZ", "randomunknownxyz.io") is None
    assert infer_employer_type("AlphaBetaGamma", "alphabetagamma.com") is None


def test_is_india_or_remote_rejects_unsupported_remote():
    """Remote work alone does not infer global or India eligibility without explicit scope."""
    # US-restricted remote must be rejected
    assert not is_india_or_remote("Remote - US Only")
    assert not is_india_or_remote("Remote, North America")
    assert not is_india_or_remote("Remote (United States)")
    assert not is_india_or_remote("California, United States")

    # Global or explicit India remote must be accepted
    assert is_india_or_remote("Remote - Anywhere in the World")
    assert is_india_or_remote("Remote, India")
    assert is_india_or_remote("Bengaluru, Karnataka, India")
    assert is_india_or_remote("Worldwide Remote")


def test_derive_profile_from_master_resume():
    """Candidate profile derivation extracts facts truthfully from master resume data."""
    master_resume_data = {
        "content": {
            "full_name": "Aditi Sharma",
            "education": [
                {
                    "institution": "IIT Madras",
                    "degree": "B.Tech",
                    "field_of_study": "Computer Science",
                    "end_year": 2026,
                    "cgpa_or_grade": "8.8/10",
                }
            ],
            "skills": ["Python", "FastAPI", "React", "Docker"],
            "location": "Bengaluru, India",
        }
    }

    profile = derive_profile_from_master_resume(master_resume_data)
    assert profile is not None
    assert profile.degree == "B.Tech"
    assert profile.degree_specialization == "Computer Science"
    assert profile.university == "IIT Madras"
    assert profile.grad_year == 2026
    assert profile.cgpa == 8.8
    assert "Python" in profile.skills
    assert "FastAPI" in profile.skills


def test_matching_evaluates_against_candidate_profile():
    """Evaluate matching against verified candidate profile distinguishing all 4 states."""
    reqs = OpportunityRequirementsOut(
        eligible_degree_types=["B.Tech"],
        eligible_graduation_years=[2026],
        eligible_countries=["India"],
        min_gpa=8.0,
        required_skills=["Python"],
    )
    opp = OpportunityOut(
        id=10,
        company_name="Tech Solutions",
        normalized_company="tech_solutions",
        role_title="Backend Intern",
        canonical_url="https://techsolutions.com/careers/10",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="India",
        is_india_eligible=True,
        requirements=reqs,
    )

    # 1. Confirmed match
    matching_profile = UserOpportunityProfileOut(
        user_id="u1",
        degree="B.Tech",
        grad_year=2026,
        cgpa=8.5,
        skills=["Python", "FastAPI"],
        country_of_study="India",
    )
    classification, explanation, reasons = evaluate_eligibility(opp, matching_profile)
    assert classification == EligibilityClassification.ELIGIBLE
    assert "Strong match" in explanation

    # 2. Mandatory mismatch (ineligible)
    ineligible_profile = UserOpportunityProfileOut(
        user_id="u2",
        degree="B.Tech",
        grad_year=2024,  # Mismatch
        cgpa=8.5,
        skills=["Python"],
        country_of_study="India",
    )
    classification, explanation, reasons = evaluate_eligibility(opp, ineligible_profile)
    assert classification == EligibilityClassification.INELIGIBLE
    assert any(r.get("field") == "grad_year" and r.get("status") == "fail" for r in reasons)

    # 3. Possible match (unknown/unconfirmed candidate fields)
    unconfirmed_profile = UserOpportunityProfileOut(
        user_id="u3",
        degree=None,  # Unknown
        grad_year=None,
        skills=["Python"],
    )
    classification, explanation, reasons = evaluate_eligibility(opp, unconfirmed_profile)
    assert classification == EligibilityClassification.POTENTIAL_MATCH
    assert "Possible match" in explanation

    # 4. Insufficient information when job requirements are unspecified
    unspecified_opp = OpportunityOut(
        id=11,
        company_name="Mystery Corp",
        normalized_company="mystery_corp",
        role_title="General Intern",
        canonical_url="https://mysterycorp.com/careers/11",
        current_status=OpportunityStatus.NEEDS_VERIFICATION,
        requirements=None,
    )
    classification, explanation, reasons = evaluate_eligibility(unspecified_opp, matching_profile)
    assert classification == EligibilityClassification.INSUFFICIENT_INFORMATION

    # 5. Missing profile entirely returns INSUFFICIENT_INFORMATION and prompts for Resume Studio
    classification, explanation, reasons = evaluate_eligibility(opp, None)
    assert classification == EligibilityClassification.INSUFFICIENT_INFORMATION
    assert "Resume Studio" in explanation
    assert "Resume Studio" in explanation
