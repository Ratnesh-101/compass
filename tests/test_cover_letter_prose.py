"""Default cover letter reads as prose built only from verified profile data."""

from backend.models_career import (
    ResumeContent,
    ResumeExperienceItem,
    ResumeProjectItem,
)
from backend.models_radar import (
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
)
from backend.services.career_resume import draft_truthful_cover_letter


def _opportunity(**overrides) -> OpportunityOut:
    fields = dict(
        id=4001,
        company_name="Acme",
        normalized_company="acme",
        role_title="Software Engineering Intern",
        opportunity_type="internship",
        canonical_url="https://acme.example/jobs/swe",
        official_application_url="https://acme.example/jobs/swe",
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


def _project() -> ResumeProjectItem:
    return ResumeProjectItem(
        title="Campus Event Tracker",
        description="Built a FastAPI and React app that lists campus events.",
        technologies=["FastAPI", "React", "Docker", "PostgreSQL"],
    )


def test_project_description_verb_is_not_glued_after_tech_list():
    letter, _, _ = draft_truthful_cover_letter(_master(projects=[_project()]), _opportunity())

    assert ", Built" not in letter
    assert "using FastAPI, React, Docker, PostgreSQL, Built" not in letter
    assert "built a FastAPI and React app that lists campus events." in letter
    assert "Campus Event Tracker" in letter
    assert "It used FastAPI, React, Docker and PostgreSQL." in letter


def test_project_without_technologies_has_no_tech_sentence():
    project = ResumeProjectItem(title="Notes App", description="A simple notes app")
    letter, _, _ = draft_truthful_cover_letter(_master(projects=[project]), _opportunity())

    assert "It used" not in letter
    assert "A simple notes app." in letter


def test_most_recent_experience_is_mentioned():
    exp = ResumeExperienceItem(
        company="Globex",
        role_title="Backend Intern",
        start_date="May 2025",
        end_date="Jul 2025",
        highlights=["Fixed flaky integration tests"],
    )
    letter, _, _ = draft_truthful_cover_letter(_master(experience=[exp]), _opportunity())

    assert "Backend Intern" in letter
    assert "Globex" in letter
    assert "May 2025" in letter and "Jul 2025" in letter
    assert "Fixed flaky integration tests" in letter


def test_non_engineering_role_has_no_technical_engineering_phrase():
    master = _master(skills=["Python"], projects=[_project()])

    pm_letter, _, _ = draft_truthful_cover_letter(master, _opportunity(role_title="Product Management Intern"))
    swe_letter, _, _ = draft_truthful_cover_letter(master, _opportunity())

    assert "technical engineering" not in pm_letter
    assert "contribute to Acme's goals" in pm_letter
    assert "technical engineering" in swe_letter


def test_only_profile_skills_appear_even_if_job_requires_more():
    master = _master(skills=["Python", "SQL"])
    opp = _opportunity(
        requirements=OpportunityRequirementsOut(required_skills=["Python", "Kubernetes", "Rust"]),
    )

    letter, _, skills = draft_truthful_cover_letter(master, opp)

    assert "Python" in skills
    assert "Kubernetes" not in letter
    assert "Rust" not in letter


def test_up_to_five_skills_listed():
    master = _master(skills=["A1", "B2", "C3", "D4", "E5", "F6"])

    _, _, skills = draft_truthful_cover_letter(master, _opportunity())

    assert skills == ["A1", "B2", "C3", "D4", "E5"]


def test_empty_profile_fallback_unchanged():
    letter, projects, skills = draft_truthful_cover_letter(_master(), _opportunity())

    assert skills == [] and projects == []
    assert "I am eager to contribute meaningfully to Acme's" in letter
    assert "bring my rigorous work ethic and eagerness to learn to the Software Engineering Intern position" in letter
    assert "For example" not in letter


def test_engineering_titles_containing_design_stay_technical():
    from backend.services.career_resume import _is_non_engineering_role

    assert _is_non_engineering_role("Software Design Engineer Intern") is False
    assert _is_non_engineering_role("Product Engineer") is False
    assert _is_non_engineering_role("Product Management Intern") is True
    assert _is_non_engineering_role("UX Design Intern") is True
