"""Resume parse slips and profile derivation (N-013 / T-021). Pure functions, no database."""
from __future__ import annotations

from datetime import date

from backend.models_career import ResumeContent, ResumeEducationItem, ResumeProjectItem
from backend.services.career_profile_derive import (
    academic_year_from_dates,
    derive_tracks,
    infer_country,
    resume_facts,
    split_education_note,
    stated_year_of_study,
)
from backend.services.career_resume import parse_uploaded_resume_text
from backend.services.career_resume_parse_fixes import extract_grade, merge_split_education_items

RESUME_TEXT = """Priya Sharma
Pune, India | priya@example.com | +91 98765 43210

Education
Pune Institute of Technology, (currently in 3rd year)
B.Tech in Computer Science | 2024-2028 | CGPA 8.4/10

Skills
Python, React, SQL, PyTorch

Projects
Library Management System - React, Flask
Built a web app for the college library;
used by 200 students.
"""


def test_college_name_and_status_note_are_split():
    content = parse_uploaded_resume_text(RESUME_TEXT)
    assert len(content.education) == 1
    edu = content.education[0]
    assert edu.institution == "Pune Institute of Technology"
    assert "currently" not in edu.institution and "(" not in edu.institution
    assert "3rd year" in content.evidence_notes["education_note_1"]


def test_degree_dates_and_grade_are_kept_on_the_same_entry():
    edu = parse_uploaded_resume_text(RESUME_TEXT).education[0]
    assert edu.degree == "B.Tech in Computer Science"
    assert (edu.start_year, edu.end_year) == (2024, 2028)
    assert edu.cgpa_or_grade == "8.4/10"


def test_a_sentence_under_a_project_stays_with_the_project():
    content = parse_uploaded_resume_text(RESUME_TEXT)
    assert [p.title for p in content.projects] == ["Library Management System"]
    project = content.projects[0]
    assert "used by 200 students" in project.description
    assert any("used by 200 students" in h for h in project.highlights)


def test_a_real_second_project_header_is_still_a_new_project():
    text = RESUME_TEXT + "Chat App - Node.js, Express\nBuilt a realtime chat with rooms.\n"
    titles = [p.title for p in parse_uploaded_resume_text(text).projects]
    assert titles == ["Library Management System", "Chat App"]


def test_grade_is_read_before_or_after_its_label():
    assert extract_grade("B.Tech 2024-2028 CGPA 8.4/10") == "8.4/10"
    assert extract_grade("B.Tech 2024-2028 8.4/10 CGPA") == "8.4/10"
    assert extract_grade("GPA: 3.7 / 4.0") == "3.7/4.0"
    assert extract_grade("B.Tech Computer Science") is None


def test_split_education_note_variants():
    assert split_education_note("Pune Institute of Technology, (currently in 3rd year)") == (
        "Pune Institute of Technology",
        "currently in 3rd year",
    )
    assert split_education_note("IIT Delhi (Autonomous)") == ("IIT Delhi (Autonomous)", None)
    assert split_education_note("NIT Trichy, currently in second year") == ("NIT Trichy", "currently in second year")
    assert split_education_note("") == ("", None)


def test_merge_only_joins_a_college_line_with_its_degree_line():
    items = [
        ResumeEducationItem(institution="Pune Institute of Technology", degree=""),
        ResumeEducationItem(institution="B.Tech in CS", degree="B.Tech in CS", start_year=2024, end_year=2028, cgpa_or_grade="8.4/10"),
    ]
    merged = merge_split_education_items(items)
    assert len(merged) == 1 and merged[0].degree == "B.Tech in CS" and merged[0].end_year == 2028

    separate = [
        ResumeEducationItem(institution="Pune Institute of Technology", degree="B.Tech"),
        ResumeEducationItem(institution="City Junior College", degree="HSC"),
    ]
    assert len(merge_split_education_items(separate)) == 2


# --- year of study -------------------------------------------------------------------------------

def test_stated_year_of_study_phrases():
    assert stated_year_of_study("currently in 3rd year") == 3
    assert stated_year_of_study("(Third Year)") == 3
    assert stated_year_of_study("pursuing B.Tech, 2nd year") == 2
    assert stated_year_of_study("Year 4") == 4
    assert stated_year_of_study("final year student") == 4
    assert stated_year_of_study("Year 2024-2028") is None
    assert stated_year_of_study("", None) is None


def test_year_of_study_from_dates_and_today():
    assert academic_year_from_dates(2024, 2028, date(2026, 11, 17)) == 3
    assert academic_year_from_dates(2024, 2028, date(2026, 3, 1)) == 2
    assert academic_year_from_dates(2024, 2028, date(2027, 8, 1)) == 4
    assert academic_year_from_dates(None, 2027, date(2026, 11, 17)) == 4  # four-year degree assumed
    assert academic_year_from_dates(2023, 2026, date(2026, 11, 17)) is None  # already finished
    assert academic_year_from_dates(2030, 2034, date(2026, 11, 17)) is None  # not started
    assert academic_year_from_dates(None, None, date(2026, 11, 17)) is None


def test_facts_prefer_the_stated_year_and_fall_back_to_dates():
    content = parse_uploaded_resume_text(RESUME_TEXT)
    facts = resume_facts(content, today=date(2026, 11, 17))
    assert facts["academic_year"] == 3 and facts["academic_year_source"] == "stated"

    no_note = ResumeContent(education=[ResumeEducationItem(institution="X University", degree="B.Tech", start_year=2024, end_year=2028)])
    facts = resume_facts(no_note, today=date(2026, 11, 17))
    assert facts["academic_year"] == 3 and facts["academic_year_source"] == "computed"

    nothing = resume_facts(ResumeContent(), today=date(2026, 11, 17))
    assert nothing["academic_year"] is None and nothing["academic_year_source"] is None


def test_country_from_location_phone_or_city():
    assert infer_country("Pune, India", None) == "India"
    assert infer_country("Pune", None) == "India"
    assert infer_country("", "+91 98765 43210") == "India"
    assert infer_country("Austin, TX", None) == "USA"
    assert infer_country("Springfield", "+1 555 0100") is None


def test_tracks_come_only_from_listed_skills():
    tracks = derive_tracks(["Python", "PyTorch", "FastAPI", "Docker"])
    assert "Artificial Intelligence and Machine Learning" in tracks
    assert "Backend Engineering" in tracks
    assert len(tracks) <= 4
    assert derive_tracks([]) == []
    assert derive_tracks(["Cooking"]) == []


def test_resume_facts_for_the_audit_persona():
    facts = resume_facts(parse_uploaded_resume_text(RESUME_TEXT), today=date(2026, 11, 17))
    assert facts["country"] == "India"
    assert facts["academic_year"] == 3
    assert "Artificial Intelligence and Machine Learning" in facts["tracks"]


def test_projects_with_no_description_do_not_break_the_facts():
    content = ResumeContent(skills=["Rust"], projects=[ResumeProjectItem(title="Tool", description="")])
    assert resume_facts(content, today=date(2026, 11, 17))["tracks"] == ["Software Engineering"]
