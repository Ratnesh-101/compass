"""
Skill matching in the application workspace ('Verified Matching Skills' vs 'Unverified or Missing').
Combined entries ('Languages: Python, C/C++'), aliases and case must match; absent skills stay unverified.
"""

from backend.models_career import ResumeContent
from backend.models_radar import OpportunityOut
from backend.services.career_job_match import (
    analyze_job_and_match,
    build_skill_index,
    skill_in_index,
    split_skill_entry,
)


def _opp(description):
    return OpportunityOut(
        id=601, company_name="Acme", normalized_company="acme", role_title="Systems Intern",
        category="software_engineering", location="Remote", canonical_url="https://acme.test/c/1",
        current_status="open_confirmed", source="devpost", description=description,
    )


def _master(skills):
    return ResumeContent(full_name="Dev", email="d@test.com", skills=list(skills))


JOB = "Skills required: Git, Open Source, C++, Python, Rust, Java"


def test_flat_skills_list_with_c_slash_cpp_matches_python_and_cpp():
    report = analyze_job_and_match(_opp(JOB), _master(["Python", "JavaScript", "C/C++", "SQL", "Java", "Rust"]))
    assert sorted(report.matched_skills) == ["C++", "Java", "Python", "Rust"]
    assert sorted(report.missing_skills) == ["Git", "Open Source"]


def test_single_languages_prefixed_entry_is_split():
    report = analyze_job_and_match(_opp(JOB), _master(["Languages: Python, JavaScript, C/C++, SQL, Java, Rust"]))
    assert sorted(report.matched_skills) == ["C++", "Java", "Python", "Rust"]
    assert sorted(report.missing_skills) == ["Git", "Open Source"]


def test_matching_is_case_insensitive_and_alias_aware():
    report = analyze_job_and_match(
        _opp("Skills required: JavaScript, Node.js, PostgreSQL, C++"),
        _master(["python", "JS", "nodejs", "Postgres", "cpp"]),
    )
    assert sorted(report.matched_skills) == ["C++", "JavaScript", "Node.js", "PostgreSQL"]
    assert report.missing_skills == []


def test_unverified_stays_honest_no_substring_leaks():
    report = analyze_job_and_match(
        _opp("Skills required: Java, Go, SQL"),
        _master(["Languages: JavaScript, PostgreSQL, C++"]),
    )
    # Java is not JavaScript, SQL is not PostgreSQL, Go is absent.
    assert report.matched_skills == []
    assert sorted(report.missing_skills) == ["Go", "Java", "SQL"]


def test_required_c_slash_cpp_needs_either_language_in_profile():
    has = analyze_job_and_match(_opp("Skills required: C/C++"), _master(["C++"]))
    lacks = analyze_job_and_match(_opp("Skills required: C/C++"), _master(["Python"]))
    assert has.matched_skills == ["C/C++"]
    assert lacks.missing_skills == ["C/C++"]


def test_split_skill_entry_and_index_helpers():
    parts = split_skill_entry("Languages: Python, JavaScript, C/C++")
    assert parts == ["Python", "JavaScript", "C/C++", "C", "C++"]
    assert split_skill_entry("CI/CD, Docker") == ["CI/CD", "Docker"]
    index = build_skill_index(["Languages: Python, C/C++"])
    assert skill_in_index("c++", index) == "Languages: Python, C/C++"
    assert skill_in_index("Rust", index) is None
