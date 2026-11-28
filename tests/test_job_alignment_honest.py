"""Job alignment must be honest: missing required skills lower coverage and are named."""
from __future__ import annotations

from backend.models_career import ResumeContent, ResumeProjectItem
from backend.models_radar import OpportunityOut
from backend.services.career_job_match import analyze_job_and_match, parse_job_skill_lists

SAMPLE_JD = "Requirements: Python, React, SQL, Kubernetes, Go. Nice to have: Docker"


def _opp(description=None) -> OpportunityOut:
    return OpportunityOut(
        id=7,
        company_name="Acme",
        normalized_company="acme",
        role_title="Backend Intern",
        category="internship",
        canonical_url="https://example.com/job",
        current_status="open",
        description=description,
    )


def _master(skills=None, projects=None) -> ResumeContent:
    return ResumeContent(full_name="Asha", skills=skills or [], projects=projects or [])


def test_parse_sample_splits_required_and_nice():
    required, nice = parse_job_skill_lists(SAMPLE_JD)
    assert required == ["Python", "React", "SQL", "Kubernetes", "Go"]
    assert nice == ["Docker"]


def test_parse_multiline_bullets_and_sections():
    text = "Must have:\n- Python\n- Node\nGood to have\n* Terraform\n"
    required, nice = parse_job_skill_lists(text)
    assert required == ["Python", "Node"]
    assert nice == ["Terraform"]


def test_sample_jd_is_sixty_percent_not_hundred():
    report = analyze_job_and_match(_opp(), _master(skills=["Python", "React", "SQL"]), custom_description=SAMPLE_JD)
    assert report.skill_overlap_estimate == 60.0
    assert report.match_score == 60.0
    assert report.matched_skills == ["Python", "React", "SQL"]
    assert report.missing_skills == ["Kubernetes", "Go"]
    verdict = report.summary_verdict
    assert "You list Python, React, SQL (from your profile)." in verdict
    assert "Missing required: Kubernetes, Go." in verdict
    assert "Missing nice-to-have: Docker." in verdict
    assert "100" not in verdict
    nice = [m for m in report.matches if not m.is_mandatory]
    assert [(m.requirement, m.match_status) for m in nice] == [("Docker", "missing_evidence")]


def test_listed_skill_is_not_called_verified_mastery():
    report = analyze_job_and_match(_opp(), _master(skills=["Python"]), custom_description="Requirements: Python")
    text = " ".join(m.reasoning for m in report.matches) + report.summary_verdict
    assert "verified mastery" not in text.lower()
    assert "list" in text.lower()


def test_aliases_match_k8s_golang_postgres():
    report = analyze_job_and_match(
        _opp(),
        _master(skills=["Kubernetes", "Go", "PostgreSQL"]),
        custom_description="Requirements: k8s, golang, postgres",
    )
    assert report.matched_skills == ["k8s", "golang", "postgres"]
    assert report.missing_skills == []


def test_project_mention_is_shown_in_your_project():
    project = ResumeProjectItem(
        title="Deploy Bot", description="Deployed services on Kubernetes", technologies=["Kubernetes"]
    )
    report = analyze_job_and_match(
        _opp(), _master(skills=["Python"], projects=[project]), custom_description="Requirements: Python, Kubernetes"
    )
    assert "Kubernetes" in report.matched_skills
    assert "shown in your project Deploy Bot" in report.summary_verdict
    kube = next(m for m in report.matches if m.requirement == "Kubernetes")
    assert "shown in your project Deploy Bot" in kube.reasoning


def test_no_requirements_list_is_not_a_hundred_percent():
    report = analyze_job_and_match(
        _opp(), _master(skills=["Python"]), custom_description="We are a friendly team building things together."
    )
    assert report.score_available is False
    assert report.skill_overlap_estimate == 0.0
    assert "could not find a requirements list" in report.summary_verdict


def test_empty_description_falls_back_to_stored_posting_text():
    opp = _opp(description=SAMPLE_JD)
    for blank in (None, "", "   \n"):
        report = analyze_job_and_match(opp, _master(skills=["Python", "React", "SQL"]), custom_description=blank)
        assert report.required_skills == ["Python", "React", "SQL", "Kubernetes", "Go"]
        assert report.skill_overlap_estimate == 60.0


def test_no_text_anywhere_asks_for_paste():
    report = analyze_job_and_match(_opp(), _master(skills=["Python"]), custom_description=None)
    assert report.score_available is False
    assert report.summary_verdict == "Paste the job description to analyse it."


def test_matched_nice_to_have_never_reaches_hundred_with_missing_required():
    report = analyze_job_and_match(
        _opp(),
        _master(skills=["Python", "Docker", "Git", "Linux"]),
        custom_description="Required: Python, Kubernetes\nBonus: Docker, Git, Linux",
    )
    assert report.skill_overlap_estimate < 100.0
    assert report.missing_skills == ["Kubernetes"]
