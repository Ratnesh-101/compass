"""Graduation year when a resume lists several degrees (TASK D). Today is pinned to 2026-11-19."""
from __future__ import annotations

from datetime import date

from backend.models_career import ResumeContent, ResumeEducationItem
from backend.services.career_profile_derive import pick_education, resume_facts

TODAY = date(2026, 11, 19)


def _edu(institution, degree, start=None, end=None):
    return ResumeEducationItem(institution=institution, degree=degree, start_year=start, end_year=end)


def _facts(*items):
    return resume_facts(ResumeContent(education=list(items)), TODAY)


def test_two_degrees_newest_first_picks_the_first_in_progress():
    facts = _facts(
        _edu("VIT Bhopal University Expected (2028)", "B.Tech Computer Science"),
        _edu("IIT Madras", "BS (Data Science)", 2025, 2029),
    )
    assert facts["grad_year"] == 2028
    assert facts["academic_year"] == 3


def test_two_degrees_with_parsed_end_years_pick_the_first_listed():
    facts = _facts(
        _edu("VIT Bhopal University", "B.Tech", 2024, 2028),
        _edu("IIT Madras", "BS (Data Science)", 2025, 2029),
    )
    assert facts["grad_year"] == 2028
    assert facts["academic_year"] == 3


def test_text_only_years_in_both_entries():
    facts = _facts(
        _edu("VIT Bhopal University Expected (2028)", "B.Tech Computer Science"),
        _edu("Online programme 2025 - 2029", "BS (Data Science)"),
    )
    assert facts["grad_year"] == 2028


def test_in_progress_entry_beats_a_finished_one_listed_first():
    facts = _facts(
        _edu("Old College", "Diploma", 2020, 2023),
        _edu("VIT Bhopal University", "B.Tech", 2024, 2028),
    )
    assert facts["grad_year"] == 2028


def test_none_in_progress_uses_most_recent_past_end_year():
    content = ResumeContent(
        education=[_edu("College A", "B.Sc", 2018, 2021), _edu("College B", "M.Sc", 2021, 2024)]
    )
    assert pick_education(content.education, TODAY).institution == "College B"
    assert resume_facts(content, TODAY)["grad_year"] == 2024


def test_end_year_of_this_year_counts_as_in_progress():
    facts = _facts(_edu("College A", "B.Tech", 2022, 2026), _edu("College B", "MBA", 2020, 2024))
    assert facts["grad_year"] == 2026


def test_high_school_entries_are_skipped():
    facts = _facts(
        _edu("Delhi Public School (DPS) Class XII", "CBSE", 2022, 2024),
        _edu("VIT Bhopal University", "B.Tech", 2024, 2028),
    )
    assert facts["grad_year"] == 2028


def test_high_school_listed_first_and_in_progress_is_still_skipped():
    items = [
        _edu("Sunrise Public School", "Class XII", 2025, 2027),
        _edu("VIT Bhopal University", "B.Tech", 2024, 2028),
    ]
    assert pick_education(items, TODAY).institution == "VIT Bhopal University"


def test_class_of_phrase_is_not_mistaken_for_school():
    facts = _facts(_edu("VIT Bhopal University, Class of 2028", "B.Tech"))
    assert facts["grad_year"] == 2028


def test_only_school_entries_fall_back_to_them():
    items = [_edu("Sunrise Public School", "Class XII", 2022, 2024)]
    assert pick_education(items, TODAY) is items[0]


def test_single_entry_and_empty_list_still_work():
    assert _facts(_edu("VIT Bhopal University", "B.Tech", 2024, 2028))["grad_year"] == 2028
    assert pick_education([], TODAY) is None
    assert resume_facts(ResumeContent(), TODAY)["grad_year"] is None


def test_saved_profile_graduation_year_uses_the_main_degree_not_the_latest_year():
    """The profile row built from the master resume must agree with resume_facts (2028, not 2029)."""
    from backend.memory.radar import derive_profile_from_master_resume

    content = {
        "education": [
            {"institution": "VIT Bhopal University", "degree": "B.Tech", "field_of_study": "Computer Science", "end_year": 2028},
            {"institution": "IIT Madras", "degree": "BS", "field_of_study": "Data Science", "end_year": 2029},
            {"institution": "Delhi Public School (DPS)", "degree": "Class XII: 80.1%", "end_year": None},
        ],
        "skills": ["Python"],
    }
    profile = derive_profile_from_master_resume(content)
    assert profile is not None
    assert profile.grad_year == 2028
