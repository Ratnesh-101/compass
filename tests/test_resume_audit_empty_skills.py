"""
Regression tests: the resume audit must not report a passed "skills verified"
check when there are no listed skills (nothing was verified).
"""
from backend.models_career import ResumeContent
from backend.services.career_resume import validate_resume_against_master

VERIFIED_MARKER = "listed skills verified"


def _content(skills):
    return ResumeContent(
        full_name="Verified Master Candidate",
        email="verified@example.com",
        skills=skills,
        education=[],
        projects=[],
    )


def test_empty_skills_does_not_report_skills_verified():
    content = _content([])
    report = validate_resume_against_master(content, content)
    assert not any(VERIFIED_MARKER in p for p in report.passed_checks)
    assert len(report.unsupported_claims) == 0


def test_verified_skills_still_report_pass_message():
    content = _content(["Python", "PostgreSQL", "Docker"])
    report = validate_resume_against_master(content, content)
    assert any("All 3 listed skills verified" in p for p in report.passed_checks)
    assert len(report.unsupported_claims) == 0


def test_unsupported_skill_suppresses_pass_message_and_is_reported():
    master = _content(["Python", "PostgreSQL"])
    tailored = _content(["Python", "Kubernetes"])
    report = validate_resume_against_master(tailored, master)
    assert not any(VERIFIED_MARKER in p for p in report.passed_checks)
    assert any("Kubernetes" in c for c in report.unsupported_claims)
