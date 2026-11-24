"""
DB-free tests for LinkedIn profile import: pasted text, Save-to-PDF text, data archive ZIP,
file dispatch and the upload endpoint. All sample data is invented ("Asha Verma").
"""
from __future__ import annotations

import io
import zipfile

import pytest

from backend.services import career_profile_sources as cps

MARKER = "SECRET-MARKER"

PASTED_WEB = """Asha Verma
Computer Science student | Backend and data
Pune, Maharashtra, India
About
Final-year student who builds small web services and data pipelines.
Experience
Backend Developer - Acme Labs
Jan 2023 - Present · 1 yr 8 mos
- Built REST endpoints for an internal tool
Education
Example Institute of Technology
Bachelor of Technology - BTech, Computer Science
Skills
Python, SQL, FastAPI
"""

PDF_EXPORT = """Contact
asha.verma@example.com
www.linkedin.com/in/asha-verma-123 (LinkedIn)
github.com/ashav (Portfolio)
Top Skills
Python
SQL
Data Analysis
Languages
English (Full Professional)
Hindi (Native)
Certifications
Example Cloud Practitioner
Asha Verma
Computer Science student
Pune, Maharashtra, India
Summary
I build small web services and data pipelines.
Experience
Acme Labs
Backend Developer
January 2023 - Present (1 year 8 months)
Pune, India
- Built REST endpoints for an internal tool
Sample Corp
Software Engineering Intern
June 2022 - August 2022 (3 months)
- Wrote unit tests for a billing module
Education
Example Institute of Technology
Bachelor of Technology - BTech, Computer Science
2020 - 2024
Page 1 of 2
"""


def _content(result):
    """Return the ResumeContent from a (content, notes) tuple or a bare content object."""
    return result[0] if isinstance(result, tuple) else result


def _notes(result):
    return list(result[1]) if isinstance(result, tuple) and len(result) > 1 else []


def _all_text(content) -> str:
    return content.model_dump_json()


def _zip_bytes(files: dict[str, str | bytes], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------- pasted web text


def test_pasted_web_profile_extracts_fields():
    result = cps.parse_pasted_linkedin_text(PASTED_WEB)
    content = _content(result)
    assert content.full_name == "Asha Verma"
    assert "Python" in content.skills and "SQL" in content.skills
    assert any("Acme" in e.company or "Acme" in e.role_title for e in content.experience)
    assert any("Example Institute" in e.institution for e in content.education)
    assert any("BTech" in e.degree or "Bachelor" in e.degree for e in content.education)
    assert content.location is None or "Pune" in content.location


def test_pasted_text_with_missing_sections_invents_nothing():
    result = cps.parse_pasted_linkedin_text("Asha Verma\nSkills\nPython, SQL\n")
    content = _content(result)
    assert content.skills == ["Python", "SQL"]
    assert content.experience == []
    assert content.education == []
    assert content.internships == []
    assert content.certifications == []
    assert content.phone is None
    assert content.email in ("", None)


# ---------------------------------------------------------------- Save-to-PDF text


@pytest.fixture(scope="module")
def pdf_result():
    return cps.parse_linkedin_profile_text(PDF_EXPORT)


def test_pdf_export_contact_fields(pdf_result):
    c = _content(pdf_result)
    assert c.full_name == "Asha Verma"
    assert c.email == "asha.verma@example.com"
    assert c.location and "Pune" in c.location
    assert c.linkedin_url == "https://www.linkedin.com/in/asha-verma-123"
    assert c.github_or_portfolio and "github.com/ashav" in c.github_or_portfolio
    assert c.phone is None  # no phone in the sample; nothing invented


def test_pdf_export_skills_and_certifications(pdf_result):
    c = _content(pdf_result)
    for skill in ("Python", "SQL", "Data Analysis"):
        assert skill in c.skills
    assert any("Cloud Practitioner" in cert for cert in c.certifications)


def test_pdf_export_education(pdf_result):
    c = _content(pdf_result)
    assert any("Example Institute of Technology" in e.institution for e in c.education)
    assert any("Bachelor of Technology" in e.degree or "BTech" in e.degree for e in c.education)


def test_pdf_export_experience_and_internship(pdf_result):
    c = _content(pdf_result)
    assert any(e.company == "Acme Labs" and "Backend" in e.role_title for e in c.experience)
    assert any("Intern" in e.role_title for e in c.internships)
    assert not any("Intern" in e.role_title for e in c.experience)


def test_pdf_export_page_footer_not_in_any_field(pdf_result):
    assert "Page 1 of 2" not in _all_text(_content(pdf_result))


def test_pdf_export_notes_and_import_summary(pdf_result):
    c = _content(pdf_result)
    summary = c.evidence_notes.get("import_summary")
    assert summary and summary.strip()
    notes = _notes(pdf_result)
    assert notes and any(n.strip() for n in notes)


# ---------------------------------------------------------------- archive ZIP

PROFILE_CSV = (
    "Notes: exported sample\n"
    "Generated for testing\n"
    "First Name,Last Name,Headline,Summary,Geo Location,Websites\n"
    'Asha,Verma,CS student,"Builds small web services.","Pune, Maharashtra, India",[PORTFOLIO:https://github.com/ashav]\n'
)
POSITIONS_CSV = (
    "Company Name,Title,Description,Location,Started On,Finished On\n"
    "Acme Labs,Backend Developer,Built REST endpoints,Pune,Jan 2023,\n"
    "Sample Corp,Software Engineering Intern,Wrote unit tests,Remote,Jun 2022,Aug 2022\n"
)
EDUCATION_CSV = (
    "School Name,Start Date,End Date,Notes,Degree Name,Activities\n"
    "Example Institute of Technology,2020,2024,,Bachelor of Technology - BTech,\n"
)
SKILLS_CSV = "Name\nPython\nSQL\n"
CERTS_CSV = "Name,Url,Authority,Started On,Finished On,License Number\nExample Cloud Practitioner,,Example Cloud,Jan 2023,,\n"
EMAILS_CSV = "Email Address,Confirmed,Primary,Updated On\nasha.verma@example.com,Yes,Yes,2023\n"


def _archive(extra: dict | None = None) -> bytes:
    files = {
        "Profile.csv": PROFILE_CSV,
        "Positions.csv": POSITIONS_CSV,
        "Education.csv": EDUCATION_CSV,
        "Skills.csv": SKILLS_CSV,
        "Certifications.csv": CERTS_CSV,
        "Email Addresses.csv": EMAILS_CSV,
        "messages.csv": f"FROM,CONTENT\nSomeone,hello {MARKER}\n",
        "Connections.csv": f"First Name,Last Name,Company\nBob,Roe,{MARKER}\n",
    }
    files.update(extra or {})
    return _zip_bytes(files)


def test_archive_fills_profile_and_skips_private_files():
    content = _content(cps.parse_linkedin_archive_zip(_archive()))
    assert MARKER not in _all_text(content)
    assert content.full_name == "Asha Verma"
    assert content.email == "asha.verma@example.com"
    assert "Python" in content.skills and "SQL" in content.skills
    assert any(e.company == "Acme Labs" for e in content.experience)
    assert any("Intern" in e.role_title for e in content.internships + content.experience)
    assert any("Example Institute" in e.institution for e in content.education)
    assert any("Cloud Practitioner" in c for c in content.certifications)


def test_archive_ignores_path_traversal_member():
    data = _archive({"../evil.csv": f"Name\n{MARKER}-EVIL\n"})
    content = _content(cps.parse_linkedin_archive_zip(data))
    assert "EVIL" not in _all_text(content)
    assert "Python" in content.skills


def test_archive_with_too_many_entries_raises():
    data = _zip_bytes({f"f{i}.txt": "x" for i in range(501)})
    with pytest.raises(ValueError):
        cps.parse_linkedin_archive_zip(data)


def test_archive_with_oversize_member_raises():
    big = "A" * (5 * 1024 * 1024 + 1)
    data = _zip_bytes({"Skills.csv": big})
    assert len(data) < 1024 * 1024  # compresses well, so the check is on uncompressed size
    with pytest.raises(ValueError):
        cps.parse_linkedin_archive_zip(data)


# ---------------------------------------------------------------- file dispatch


def test_ingest_zip_bytes_use_archive_parser():
    content = _content(cps.ingest_external_profile_file(_archive(), "export.zip"))
    assert content.full_name == "Asha Verma"
    assert MARKER not in _all_text(content)


def test_ingest_csv_with_skills_header():
    content = _content(cps.ingest_external_profile_file(SKILLS_CSV.encode(), "Skills.csv"))
    assert content.skills == ["Python", "SQL"]


def test_ingest_txt_uses_text_parser():
    content = _content(cps.ingest_external_profile_file(PDF_EXPORT.encode(), "profile.txt"))
    assert content.email == "asha.verma@example.com"


def test_ingest_empty_bytes_raises():
    with pytest.raises(ValueError):
        cps.ingest_external_profile_file(b"", "empty.txt")


def test_ingest_over_25mb_raises():
    with pytest.raises(ValueError):
        cps.ingest_external_profile_file(b"a" * (25 * 1024 * 1024 + 1), "big.txt")


def test_ingest_bad_zip_raises_value_error():
    # Documented behaviour is confirmed against the final service code when it lands.
    with pytest.raises(ValueError):
        cps.ingest_external_profile_file(b"this is not a zip file", "x.zip")


# ---------------------------------------------------------------- router

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def _client(monkeypatch):
    from fastapi import FastAPI

    from backend.routers import career_profile_import as mod

    app = FastAPI()
    app.include_router(mod.router)
    # rate_limit is a route dependency; _get_or_create_user_id is called directly in the handler body.
    app.dependency_overrides[mod.rate_limit] = lambda: None
    monkeypatch.setattr(mod, "_get_or_create_user_id", lambda request: "user-test")
    path = next(r.path for r in mod.router.routes if "external-profile-file" in getattr(r, "path", ""))
    return fastapi_testclient.TestClient(app), path


def test_router_accepts_small_csv(monkeypatch):
    client, path = _client(monkeypatch)
    resp = client.post(path, files={"file": ("Skills.csv", SKILLS_CSV.encode(), "text/csv")})
    assert resp.status_code == 200, resp.text
    assert "Python" in resp.text


def test_router_rejects_oversize_with_413(monkeypatch):
    client, path = _client(monkeypatch)
    resp = client.post(path, files={"file": ("big.txt", b"a" * (25 * 1024 * 1024 + 1), "text/plain")})
    assert resp.status_code == 413


def test_router_rejects_bad_file_with_400(monkeypatch):
    client, path = _client(monkeypatch)
    resp = client.post(path, files={"file": ("x.zip", b"not a zip", "application/zip")})
    assert resp.status_code == 400
