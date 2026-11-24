"""DB-free tests: year of study, graduation year, CGPA, degree text and clean skills from resume text.

All resume data is invented. Assertions match what the real functions return. Tests whose names
start with ``test_qa_`` cover reported QA failures and are kept strict on purpose.
"""
import time
from datetime import date

import pytest

from backend.services.career_profile_derive import resume_facts
from backend.services.career_resume import parse_uploaded_resume_text
from backend.services.radar_profile_parse import (
    format_degree,
    parse_academic_year,
    parse_grade,
    parse_graduation_year,
)

TODAY = date(2026, 11, 25)

RESUME_TEXT = (
    "Aarav Testwala\n"
    "aarav@example.com | +91 98765 43210 | Pune, India\n"
    "\n"
    "Education\n"
    "Example Institute of Technology, Pune\n"
    "B.Tech in Computer Science and Engineering, 2nd year (2025 - 2029)\n"
    "Expected graduation: May 2029\n"
    "CGPA: 7.4 / 10\n"
    "\n"
    "Skills\n"
    "Languages: Python, Java, C++\n"
    "Web: HTML, CSS, Flask\n"
    "ML/Data: NumPy, Pandas\n"
    "Tools & Platforms: Git, Docker\n"
    "\n"
    "Projects\n"
    "Expense tracker - a small Flask app\n"
)

CLEAN_SKILLS = ["Python", "Java", "C++", "HTML", "CSS", "Flask", "NumPy", "Pandas", "Git", "Docker"]


# (1) parse_academic_year


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1st year", 1),
        ("2nd year", 2),
        ("3rd year", 3),
        ("first year", 1),
        ("second year", 2),
        ("third year", 3),
        ("fourth year", 4),
        ("final year", 4),  # real mapping: "final" -> 4
        ("Year 2", 2),
        ("Sem 5", 3),
        ("Semester 8", 4),
    ],
)
def test_parse_academic_year_stated(text, expected):
    assert parse_academic_year(text) == expected


def test_parse_academic_year_from_dates():
    assert parse_academic_year("B.Tech", start_year=2025, end_year=2029, today=TODAY) == 2


@pytest.mark.parametrize("text", [None, ""])
def test_parse_academic_year_empty_is_none(text):
    assert parse_academic_year(text) is None


def test_parse_academic_year_invents_nothing():
    assert parse_academic_year("Studied at Example Institute") is None


# (2) parse_graduation_year


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Expected graduation: May 2029", 2029),
        ("Class of 2026", 2026),
        ("Graduating 2027", 2027),
        ("(2025 - 2029)", 2029),
        ("No dates here", None),
    ],
)
def test_parse_graduation_year(text, expected):
    assert parse_graduation_year(text) == expected


# (3) parse_grade


@pytest.mark.parametrize(
    "text, expected",
    [
        ("CGPA: 7.4 / 10", (7.4, 10.0)),
        ("8.2", (None, None)),  # no label and no scale: the function refuses to guess
        ("8.1/10", (8.1, 10.0)),
        ("GPA 3.6/4.0", (3.6, 4.0)),
        ("not a grade", (None, None)),
        ("", (None, None)),
    ],
)
def test_parse_grade(text, expected):
    assert parse_grade(text) == expected


def test_parse_grade_bare_number_with_label():
    assert parse_grade("CGPA 8.2") == (8.2, 10.0)


# (4) format_degree


def test_format_degree_keeps_degree_that_has_specialisation():
    degree = "B.Tech in Computer Science and Engineering"
    assert format_degree(degree, "Computer Science") == degree


def test_format_degree_appends_missing_specialisation():
    assert format_degree("B.Tech", "Computer Science") == "B.Tech in Computer Science"


# (5) parse_uploaded_resume_text


def test_resume_skills_are_clean_names():
    skills = parse_uploaded_resume_text(RESUME_TEXT).skills
    assert sorted(skills) == sorted(CLEAN_SKILLS)
    assert all(":" not in s for s in skills)
    labels = ("languages", "web", "ml/data", "tools & platforms", "tools", "platforms")
    assert not any(s.lower() in labels or s.lower().startswith(labels) for s in skills)


def test_resume_has_one_education_item_with_institution():
    edu = parse_uploaded_resume_text(RESUME_TEXT).education
    assert len(edu) == 1
    assert "Example Institute" in edu[0].institution


def test_qa_education_start_year_is_2025():
    edu = parse_uploaded_resume_text(RESUME_TEXT).education
    assert edu, "no education item parsed"
    assert edu[0].start_year == 2025


def test_qa_education_end_year_is_2029():
    edu = parse_uploaded_resume_text(RESUME_TEXT).education
    assert edu, "no education item parsed"
    assert edu[0].end_year == 2029


def test_education_degree_does_not_repeat_specialisation():
    edu = parse_uploaded_resume_text(RESUME_TEXT).education
    assert edu, "no education item parsed"
    shown = format_degree(edu[0].degree, edu[0].field_of_study)
    assert shown.count("Computer Science") == 1, shown


# (6) end to end


def test_qa_radar_facts_grad_year_is_2029():
    facts = resume_facts(parse_uploaded_resume_text(RESUME_TEXT), today=TODAY)
    assert facts["grad_year"] == 2029


def test_qa_radar_facts_academic_year_is_2():
    facts = resume_facts(parse_uploaded_resume_text(RESUME_TEXT), today=TODAY)
    assert facts["academic_year"] == 2


# (7) bounded regex work


def _seconds(fn, arg):
    start = time.perf_counter()
    fn(arg)
    return time.perf_counter() - start


def test_parse_academic_year_is_bounded():
    assert _seconds(parse_academic_year, (" " * 50000) + "year") < 1.0


def test_parse_graduation_year_is_bounded():
    assert _seconds(parse_graduation_year, "1" * 50000) < 1.0


def test_parse_grade_is_bounded():
    assert _seconds(parse_grade, " " * 50000 + "CGPA") < 1.0
