"""Graduation year and year of study from "Expected (2028)" style resume text (BUG A).

Today is pinned to 2026-11-19, so a degree that finishes in 2028 is year 3.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.models_career import ResumeContent, ResumeEducationItem
from backend.models_radar import (
    EligibilityClassification,
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
    UserOpportunityProfileIn,
)
from backend.services import career_profile_derive
from backend.services.career_profile_derive import extract_education_years, resume_facts
from backend.services.career_resume import parse_uploaded_resume_text
from backend.services.radar_eligibility import evaluate_eligibility

TODAY = date(2026, 11, 19)

_RESUME = """Priya Sharma
Bhopal, India | priya@example.com | +91 98765 43210

Education
{edu_line}

Skills
Python, React, SQL
"""

_VARIANTS = [
    "B.Tech in Computer Science, VIT Bhopal University Expected (2028)",
    "B.Tech in Computer Science, VIT Bhopal University Expected 2028",
    "B.Tech in Computer Science, VIT Bhopal University, Class of 2028",
    "B.Tech in Computer Science, VIT Bhopal University 2024 - 2028",
    "B.Tech in Computer Science, VIT Bhopal University, May 2028",
]


# --- the text reader ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected_end",
    [
        ("VIT Bhopal University Expected (2028)", 2028),
        ("VIT Bhopal University Expected 2028", 2028),
        ("VIT Bhopal University, Class of 2028", 2028),
        ("VIT Bhopal University 2024 - 2028", 2028),
        ("VIT Bhopal University 2024-28", 2028),
        ("VIT Bhopal University, May 2028", 2028),
        ("Expected graduation: May 2028", 2028),
    ],
)
def test_extract_education_years_finds_2028(text, expected_end):
    assert extract_education_years(text)[1] == expected_end


def test_extract_education_years_range_gives_start_and_end():
    assert extract_education_years("B.Tech 2024 - 2028") == (2024, 2028)


def test_extract_education_years_cue_beats_other_years():
    assert extract_education_years("Class XII 2022, B.Tech Expected (2028)")[1] == 2028


def test_extract_education_years_no_year():
    assert extract_education_years("B.Tech in Computer Science", None, "") == (None, None)


# --- parsed resume -> facts -----------------------------------------------------------------------

@pytest.mark.parametrize("edu_line", _VARIANTS)
def test_uploaded_resume_yields_grad_year_2028_and_year_3(edu_line):
    content = parse_uploaded_resume_text(_RESUME.format(edu_line=edu_line))
    assert content.education, "education entry was not parsed"
    facts = resume_facts(content, TODAY)
    assert facts["grad_year"] == 2028
    assert facts["academic_year"] == 3
    assert facts["academic_year_source"] == "computed"


@pytest.mark.parametrize(
    "institution",
    [
        "VIT Bhopal University Expected (2028)",
        "VIT Bhopal University Expected 2028",
        "VIT Bhopal University, Class of 2028",
        "VIT Bhopal University 2024 - 2028",
        "VIT Bhopal University, May 2028",
    ],
)
def test_facts_read_year_from_text_when_end_year_was_not_parsed(institution):
    """The parser left end_year empty; the year in the education text must still be found."""
    content = ResumeContent(
        education=[ResumeEducationItem(institution=institution, degree="B.Tech in Computer Science")]
    )
    facts = resume_facts(content, TODAY)
    assert facts["grad_year"] == 2028
    assert facts["academic_year"] == 3


def test_facts_keep_parsed_end_year():
    content = ResumeContent(
        education=[ResumeEducationItem(institution="VIT Bhopal University", degree="B.Tech", end_year=2028)]
    )
    facts = resume_facts(content, TODAY)
    assert facts["grad_year"] == 2028
    assert facts["academic_year"] == 3


def test_facts_without_any_year_stay_empty():
    content = ResumeContent(
        education=[ResumeEducationItem(institution="VIT Bhopal University", degree="B.Tech")]
    )
    facts = resume_facts(content, TODAY)
    assert facts["grad_year"] is None
    assert facts["academic_year"] is None


def test_facts_ignore_grad_year_the_profile_would_reject():
    content = ResumeContent(
        education=[ResumeEducationItem(institution="Old College Class of 2012", degree="B.Sc")]
    )
    assert resume_facts(content, TODAY)["grad_year"] is None


# --- saved profile ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_fills_grad_year_and_year_of_study(monkeypatch):
    from backend.memory import radar as radar_memory

    saved = {}
    profile = UserOpportunityProfileIn(degree="B.Tech", university="VIT Bhopal University")

    async def fake_get(user_id):
        return profile

    async def fake_upsert(user_id, p):
        saved["profile"] = p

    monkeypatch.setattr(radar_memory, "get_user_opportunity_profile", fake_get)
    monkeypatch.setattr(radar_memory, "upsert_user_opportunity_profile", fake_upsert)
    content = ResumeContent(
        education=[
            ResumeEducationItem(institution="VIT Bhopal University Expected (2028)", degree="B.Tech in Computer Science")
        ]
    )
    changed = await career_profile_derive.enrich_radar_profile_from_resume("u1", content, TODAY)
    assert changed["grad_year"] == 2028
    assert changed["academic_year"] == 3
    assert saved["profile"].grad_year == 2028
    assert saved["profile"].academic_year == 3


# --- eligibility -----------------------------------------------------------------------------------

def test_eligibility_derives_year_of_study_from_grad_year(monkeypatch):
    class _FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 19)

    monkeypatch.setattr(career_profile_derive, "date", _FixedDate)
    opp = OpportunityOut(
        id=1,
        company_name="Acme",
        normalized_company="Acme",
        role_title="SWE Intern",
        opportunity_type="internship",
        category="swe",
        canonical_url="https://example.com/jobs/1",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="India",
        is_india_eligible=True,
        requirements=OpportunityRequirementsOut(eligible_academic_years=[3], eligible_countries=["India"]),
    )
    profile = UserOpportunityProfileIn(degree="B.Tech", grad_year=2028, country_of_study="India")
    assert profile.academic_year is None
    _classification, _explanation, reasons = evaluate_eligibility(opp, profile)
    year_reason = next(r for r in reasons if r["field"] == "academic_year")
    assert year_reason["status"] == "pass"
    assert _classification != EligibilityClassification.INELIGIBLE
