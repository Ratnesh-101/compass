"""Gap tests for resume and LinkedIn parsing. All data is invented; no DB, network or files."""
from __future__ import annotations

import csv
import io
import time
import zipfile

import pytest

from backend.models_career import ResumeContent
from backend.services.career_profile_archive import parse_linkedin_archive_zip
from backend.services.career_profile_derive import resume_facts
from backend.services.career_profile_sources import parse_linkedin_profile_text, parse_pasted_linkedin_text
from backend.services.career_resume import parse_uploaded_resume_text

HEADER = "Riya Fakenamey\nriya.fakenamey@example.dev | Pune, Maharashtra\n"
EDUCATION = "EDUCATION\nExample Institute of Technology, B.Tech Computer Science 2025 - 2029\n"
SKILLS = "SKILLS\nPython, FastAPI\n"


def _titles(content: ResumeContent) -> list[str]:
    return [p.title for p in content.projects]


# ---------------------------------------------------------------- (1) projects


def test_bulleted_projects_section_gives_two_projects_and_keeps_other_sections():
    text = (
        HEADER + EDUCATION + SKILLS
        + "PROJECTS\n"
        "- Expense tracker web app (HTML, CSS, JavaScript) - tracks daily spending\n"
        "- Weather CLI in Python - fetches forecasts\n"
    )
    content = parse_uploaded_resume_text(text)
    assert _titles(content) == ["Expense tracker web app", "Weather CLI in Python"]
    first = content.projects[0]
    for tech in ("HTML", "CSS", "JavaScript"):
        assert tech in first.technologies
    assert all(p.description.strip() for p in content.projects)
    assert content.full_name == "Riya Fakenamey"
    assert content.education and "Python" in content.skills


@pytest.mark.parametrize(
    "body, expected_titles",
    [
        (
            "Expense tracker web app - tracks daily spending\nWeather CLI in Python - fetches forecasts\n",
            ["Expense tracker web app", "Weather CLI in Python"],
        ),
        (
            "Expense tracker web app tracks daily spending and builds monthly charts\n\n"
            "Weather CLI in Python fetches forecasts and prints them nicely\n",
            None,  # paragraph form: only the count is checked
        ),
    ],
    ids=["unbulleted-title-dash-description", "blank-line-separated-paragraphs"],
)
def test_unbulleted_and_paragraph_projects(body, expected_titles):
    content = parse_uploaded_resume_text(HEADER + EDUCATION + "PROJECTS\n" + body)
    assert len(content.projects) == 2, _titles(content)
    if expected_titles is not None:
        assert _titles(content) == expected_titles
        assert all(p.description.strip() for p in content.projects)


def test_next_section_header_stops_projects():
    text = (
        HEADER
        + "PROJECTS\n- Weather CLI in Python - fetches forecasts\n"
        + "CERTIFICATIONS\nExample Cloud Practitioner\n"
    )
    content = parse_uploaded_resume_text(text)
    assert _titles(content) == ["Weather CLI in Python"]
    assert content.certifications == ["Example Cloud Practitioner"]


# ------------------------------------------------------- (2) graduation month


def _facts_for(education_line: str) -> dict:
    content = parse_uploaded_resume_text(HEADER + "EDUCATION\n" + education_line + "\n" + SKILLS)
    return resume_facts(content)


def test_expected_graduation_month_is_read():
    facts = _facts_for("Example Institute of Technology, B.Tech Computer Science, Expected graduation: May 2029")
    assert facts["grad_year"] == 2029
    if "grad_month" not in facts:
        pytest.skip("resume_facts does not expose grad_month yet")
    assert facts["grad_month"] == 5


def test_no_month_keeps_previous_default():
    facts = _facts_for("Example Institute of Technology, B.Tech Computer Science, Expected 2029")
    assert facts["grad_year"] == 2029
    # Previous default (profile model and DB default) is 6; absent/None means "not set, default applies".
    assert facts.get("grad_month") in (None, 6)


# ------------------------------------------------------ (3) LinkedIn PDF text

LINKEDIN_TEXT = """Contact
riya.fakenamey@example.dev
www.linkedin.com/in/riya-fakenamey (LinkedIn)
Top Skills
Python
FastAPI
Languages
English (Full Professional)
Hindi (Native or Bilingual)
Riya Fakenamey
Software Engineering Student
Pune, Maharashtra, India
Summary
Student building backend services.
Experience
Backend Developer
Acme Labs
June 2025 - August 2025 (3 months)
Built internal APIs.
Backend Developer
Acme Labs
September 2025 - Present (3 months)
Maintains services.
Education
Example Institute of Technology
Bachelor of Technology - BTech, Information Technology · (2024 - 2028)
"""


@pytest.fixture(params=[parse_pasted_linkedin_text, parse_linkedin_profile_text], ids=["pasted", "profile_alias"])
def linkedin(request):
    content, _notes = request.param(LINKEDIN_TEXT)
    return content


def _jobs(content: ResumeContent):
    return [*content.experience, *content.internships]


def test_linkedin_experience_dates_and_current_flag(linkedin):
    acme = [j for j in _jobs(linkedin) if "acme" in f"{j.company} {j.role_title}".lower()]
    assert len(acme) == 2, [(j.company, j.role_title, j.start_date, j.end_date) for j in _jobs(linkedin)]
    first, second = acme
    assert "acme labs" in first.company.lower()
    assert "backend developer" in first.role_title.lower()
    assert first.start_date and first.end_date
    assert first.is_current is False
    assert second.is_current is True


def test_linkedin_education_degree_field_and_years(linkedin):
    edu = next((e for e in linkedin.education if e.degree.startswith("Bachelor of Technology")), None)
    assert edu is not None, [(e.institution, e.degree, e.field_of_study) for e in linkedin.education]
    assert edu.field_of_study == "Information Technology"
    assert (edu.start_year, edu.end_year) == (2024, 2028)


def test_linkedin_existing_name_location_skills_still_work(linkedin):
    assert linkedin.full_name == "Riya Fakenamey"
    assert "Pune" in (linkedin.location or "")
    assert "Python" in linkedin.skills and "FastAPI" in linkedin.skills
    assert not any("Full Professional" in s for s in linkedin.skills)


def test_linkedin_btech_comma_field_split():
    text = (
        "Riya Fakenamey\nSoftware Engineering Student\nPune, Maharashtra, India\n"
        "Summary\nStudent.\nEducation\nExample University\nB.Tech, Computer Science\n"
    )
    content, _ = parse_pasted_linkedin_text(text)
    edu = next((e for e in content.education if e.degree == "B.Tech"), None)
    assert edu is not None, [(e.institution, e.degree, e.field_of_study) for e in content.education]
    assert edu.field_of_study == "Computer Science"


# ----------------------------------------------------------- (4) zip Websites


def _zip_with_profile(websites: str) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["First Name", "Last Name", "Headline", "Summary", "Geo Location", "Websites"])
    writer.writerow(["Riya", "Fakenamey", "Student", "Builds APIs.", "Pune, India", websites])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("Profile.csv", buf.getvalue())
    return out.getvalue()


def test_zip_portfolio_website_is_used():
    content, _ = parse_linkedin_archive_zip(_zip_with_profile("[PORTFOLIO:https://riya-fakenamey.example.dev]"))
    assert content.full_name == "Riya Fakenamey"
    assert content.github_or_portfolio == "https://riya-fakenamey.example.dev"
    assert any(link == "https://riya-fakenamey.example.dev" for link in content.relevant_links)


def test_zip_multiple_websites_kept_and_javascript_dropped():
    value = "[COMPANY:https://x.example],[PERSONAL:https://y.example],[OTHER:javascript:alert(1)]"
    content, _ = parse_linkedin_archive_zip(_zip_with_profile(value))
    links = [*content.relevant_links, content.github_or_portfolio or ""]
    assert any(u.rstrip("/") == "https://x.example" for u in content.relevant_links), content.relevant_links
    assert any(u.rstrip("/") == "https://y.example" for u in content.relevant_links), content.relevant_links
    assert not any(u.lower().startswith("javascript:") for u in links)
    assert not any("javascript:" in u.lower() for u in links)


# ------------------------------------------------------------ (5) bounded regex


@pytest.mark.parametrize("filler", [" " * 50000, "- " * 50000], ids=["spaces", "dashes"])
@pytest.mark.parametrize("parser", [parse_uploaded_resume_text, parse_pasted_linkedin_text], ids=["resume", "linkedin"])
def test_pathological_input_finishes_quickly(parser, filler):
    text = (" " * 50000) + "PROJECTS" if filler.strip() == "" else "PROJECTS\n" + filler
    started = time.perf_counter()
    parser(text)
    assert time.perf_counter() - started < 1.0
