"""Regression tests for career resume/profile parsing, tailoring, validation, and export fixes."""
import io
import sys
import types

from backend.models_career import (
    OpportunityOut,
    ResumeContent,
    ResumeOut,
    ResumeProjectItem,
)
from backend.models_radar import OpportunityStatus
from backend.services import career_file_parser
from backend.services.career_profile_sources import parse_pasted_linkedin_text
from backend.services.career_resume import (
    generate_resume_docx,
    generate_resume_html,
    parse_uploaded_resume_text,
    tailor_resume_for_opportunity,
    validate_resume_against_master,
)


def _opp() -> OpportunityOut:
    return OpportunityOut(
        id=1,
        company_name="Acme",
        normalized_company="Acme",
        role_title="Backend Intern",
        opportunity_type="internship",
        category="software_engineering",
        canonical_url="https://acme.example/jobs/1",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="Remote",
        is_india_eligible=True,
    )


def _resume_out(content: ResumeContent) -> ResumeOut:
    return ResumeOut(id=1, user_id="u", title="R", content=content)


def test_linkedin_date_range_lines_do_not_become_experience_entries():
    raw = (
        "Jane Doe\n"
        "Experience\n"
        "Software Engineer\n"
        "Google · Full-time\n"
        "Jan 2020 - Present · 3 yrs 5 mos\n"
        "Education\n"
        "IIT Delhi - B.Tech\n"
    )
    content, _ = parse_pasted_linkedin_text(raw)
    titles = [e.role_title for e in content.experience]
    assert not any("2020" in t or "yrs" in t for t in titles)
    assert [e.company for e in content.experience] == ["Google"]


def test_resume_multi_job_header_not_merged_into_previous_bullet():
    text = "\n".join([
        "Jane Doe",
        "Experience",
        "Google | Software Engineer | Jan 2020 - Dec 2021",
        "\u2022 Built a search service",
        "Meta | Software Engineer",
        "Jan 2022 - Present",
        "\u2022 Scaled the feed ranking pipeline",
    ])
    content = parse_uploaded_resume_text(text)
    google = content.experience[0]
    assert google.company == "Google"
    assert google.highlights == ["Built a search service"]
    assert "Meta" in [e.company for e in content.experience]


def test_tailor_preserves_extended_sections():
    master = ResumeContent(
        full_name="Jane",
        skills=["Python"],
        internships=[{"company": "Acme", "role_title": "Intern"}],
        awards=["Dean's List"],
        hackathons=["HackMIT winner"],
        publications=["Paper on RAG"],
        leadership_and_volunteering=["Club president"],
    )
    tailored, _, _ = tailor_resume_for_opportunity(master, _opp())
    assert [i.company for i in tailored.internships] == ["Acme"]
    assert tailored.awards == ["Dean's List"]
    assert tailored.hackathons == ["HackMIT winner"]
    assert tailored.publications == ["Paper on RAG"]
    assert tailored.leadership_and_volunteering == ["Club president"]


def test_validation_flags_fabricated_project_when_master_has_none():
    master = ResumeContent(full_name="Jane", skills=["Python"])
    tailored = ResumeContent(
        full_name="Jane",
        skills=["Python"],
        projects=[ResumeProjectItem(title="Invented Startup", description="made up")],
    )
    report = validate_resume_against_master(tailored, master, _opp())
    assert not report.is_valid
    assert any("Invented Startup" in u for u in report.unsupported_claims)


def test_pdf_parse_falls_back_to_pdfplumber_when_pypdf_missing(monkeypatch):
    class _Page:
        def extract_text(self):
            return "Jane Doe\nSkills\nPython, FastAPI, PostgreSQL experience in backend work"

    class _Pdf:
        pages = [_Page()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake = types.SimpleNamespace(open=lambda _stream: _Pdf())
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import pypdf -> ImportError
    monkeypatch.setitem(sys.modules, "pdfplumber", fake)
    assert career_file_parser.is_pdf_parser_available()
    result = career_file_parser.extract_resume_from_file_bytes(b"%PDF-1.4 fake", "cv.pdf")
    assert result.success, result.error_message
    assert result.page_count == 1


def test_html_export_renders_escaped_certifications():
    resume = _resume_out(ResumeContent(full_name="Jane", certifications=["AWS <b>SAA</b>"]))
    html_out = generate_resume_html(resume)
    assert "Certifications" in html_out
    assert "AWS &lt;b&gt;SAA&lt;/b&gt;" in html_out
    assert "<b>SAA</b>" not in html_out


def test_docx_export_renders_certifications():
    from docx import Document

    resume = _resume_out(ResumeContent(full_name="Jane", certifications=["AWS Solutions Architect"]))
    doc = Document(io.BytesIO(generate_resume_docx(resume)))
    texts = [p.text for p in doc.paragraphs]
    assert "CERTIFICATIONS" in texts
    assert "AWS Solutions Architect" in texts
