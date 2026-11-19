"""Labelled skill lists ('Frameworks: React, FastAPI') must support each skill they name, in the resume check and in ranking."""
from types import SimpleNamespace

from backend.models_career import ResumeContent, ResumeProjectItem
from backend.models_radar import EligibilityClassification, OpportunityStatus
from backend.services.career_resume import validate_resume_against_master
from backend.services.radar_quality import recommendation_rank_key

LABELLED = [
    "Languages: Python, JavaScript, C/C++, SQL, Java, Rust",
    "Frameworks & Databases: React, FastAPI, Flask, PostgreSQL (Neon), MySQL",
]


def _resume(skills):
    return ResumeContent(
        full_name="Test Candidate",
        email="test@example.com",
        skills=skills,
        projects=[ResumeProjectItem(title="Compass", description="App", technologies=["React", "PostgreSQL", "C++", "Kafka"])],
    )


def _warnings(report):
    return " ".join(getattr(report, "warnings", []) or [])


def test_resume_check_accepts_project_tech_named_in_a_labelled_skills_entry():
    master = _resume(LABELLED)
    report = validate_resume_against_master(_resume(LABELLED), master)
    text = _warnings(report)
    assert "'React'" not in text
    assert "'PostgreSQL'" not in text
    assert "'C++'" not in text  # supported through 'C/C++'


def test_resume_check_still_flags_tech_that_is_really_missing():
    master = _resume(LABELLED)
    report = validate_resume_against_master(_resume(LABELLED), master)
    assert "'Kafka'" in _warnings(report)


def _opp(required):
    return SimpleNamespace(
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        needs_recheck=False,
        eligibility_classification=EligibilityClassification.INSUFFICIENT_INFORMATION,
        role_title="Intern",
        category="",
        requirements=SimpleNamespace(required_skills=required),
        confirmed_close_date=None,
        country="India",
        location="India",
        is_india_eligible=True,
        work_arrangement=None,
    )


def test_ranking_counts_skills_from_labelled_entries():
    profile = SimpleNamespace(skills=LABELLED, preferred_roles=[], country="India")
    match = recommendation_rank_key(_opp(["Python", "React", "Rust"]), profile, "India")
    other = recommendation_rank_key(_opp(["Photoshop", "Premiere Pro"]), profile, "India")
    assert match < other  # three real overlaps sort ahead of none
