"""Cover letters must only claim what the master profile supports (zero hallucination)."""

from backend.models_career import ResumeContent, ResumeEducationItem
from backend.models_radar import (
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
)
from backend.services.career_resume import draft_truthful_cover_letter


def _opportunity(**overrides) -> OpportunityOut:
    fields = dict(
        id=3001,
        company_name="Acme",
        normalized_company="acme",
        role_title="Python Engineering Intern",
        opportunity_type="internship",
        canonical_url="https://acme.example/jobs/intern",
        official_application_url="https://acme.example/jobs/intern",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        category="swe",
        country="India",
        is_india_eligible=True,
    )
    fields.update(overrides)
    return OpportunityOut(**fields)


def _master(**overrides) -> ResumeContent:
    fields = dict(full_name="Test Person", email="test@example.com")
    fields.update(overrides)
    return ResumeContent(**fields)


def test_empty_profile_makes_no_skill_claims():
    letter, projects, skills = draft_truthful_cover_letter(_master(), _opportunity())

    assert skills == []
    assert projects == []
    assert "solid foundation" not in letter
    assert "verified skills in" not in letter
    assert "  to the " not in letter
    assert "I am eager to contribute meaningfully to Acme's" in letter
    assert "bring my rigorous work ethic and eagerness to learn to the Python Engineering Intern position" in letter


def test_profile_with_matching_skills_keeps_skill_claims():
    master = _master(skills=["Python", "SQL"])
    opp = _opportunity(
        requirements=OpportunityRequirementsOut(required_skills=["Python", "SQL"]),
    )

    letter, _, skills = draft_truthful_cover_letter(master, opp)

    assert skills == ["Python", "SQL"]
    assert "solid foundation in Python, SQL" in letter
    assert "verified skills in Python, SQL to the" in letter


def test_education_without_skills_reads_grammatically_and_claims_no_foundation():
    master = _master(
        education=[
            ResumeEducationItem(
                institution="IIT Delhi",
                degree="B.Tech Computer Science",
                field_of_study="Computer Science",
                end_year=2027,
            )
        ]
    )

    letter, _, skills = draft_truthful_cover_letter(master, _opportunity())

    assert skills == []
    assert "As a student at IIT Delhi pursuing B.Tech Computer Science, I am eager to contribute" in letter
    assert "solid foundation" not in letter
    assert "verified skills in" not in letter
