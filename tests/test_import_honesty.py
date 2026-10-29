"""Regression tests for the resume/profile import path: no data loss, no fabricated content,
honest confidence, URL safety, hardened file parsing, rate limiting and draft status."""
import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from backend.dependencies import generate_guest_token
from backend.main import app
from backend.models_career import (
    ExternalProfileImportRequest,
    ExternalProfileSource,
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
    ResumeProjectItem,
)
from backend.services import career_file_parser
from backend.services.career_file_parser import extract_resume_from_file_bytes
from backend.services.career_profile_sources import ingest_external_profile, parse_pasted_linkedin_text
from backend.services.career_resume import (
    analyze_extraction_diagnostics,
    parse_uploaded_resume_text,
    validate_resume_against_master,
)
from backend.services.resume_merge import merge_resume_content


def _headers() -> dict:
    _gid, token = generate_guest_token()
    return {"x-guest-token": token}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _full_content() -> ResumeContent:
    return ResumeContent(
        full_name="Ada Lovelace",
        email="ada@example.com",
        skills=["Python", "SQL"],
        education=[ResumeEducationItem(institution="MIT", degree="BS Computer Science")],
        projects=[ResumeProjectItem(title="Engine", description="Analytical engine emulator")],
        experience=[ResumeExperienceItem(company="Babbage Ltd", role_title="Engineer")],
    )


# --- 1. merge ---------------------------------------------------------------

def test_merge_keeps_existing_lists_and_scalars_when_incoming_empty():
    existing = _full_content()
    incoming = ResumeContent(relevant_links=["https://example.com/me"], github_or_portfolio="https://example.com")
    merged = merge_resume_content(existing, incoming)
    assert merged.full_name == "Ada Lovelace"
    assert merged.email == "ada@example.com"
    assert merged.skills == ["Python", "SQL"]
    assert len(merged.experience) == 1 and len(merged.projects) == 1 and len(merged.education) == 1
    assert merged.relevant_links == ["https://example.com/me"]
    assert merged.github_or_portfolio == "https://example.com"


def test_merge_replaces_sections_present_in_incoming():
    existing = _full_content()
    incoming = ResumeContent(full_name="Ada L.", skills=["Rust"])
    merged = merge_resume_content(existing, incoming)
    assert merged.full_name == "Ada L."
    assert merged.skills == ["Rust"]
    assert merged.email == "ada@example.com"
    assert len(merged.experience) == 1


@pytest.mark.asyncio
async def test_links_only_commit_does_not_wipe_master():
    headers = _headers()
    async with _client() as ac:
        r1 = await ac.post(
            "/api/career/resumes/commit-extracted",
            json={"content": _full_content().model_dump(), "target": "master"},
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        r2 = await ac.post(
            "/api/career/resumes/commit-extracted",
            json={"content": {"relevant_links": ["https://example.com/p"]}, "target": "master"},
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
        content = r2.json()["content"]
    assert content["full_name"] == "Ada Lovelace"
    assert content["skills"] == ["Python", "SQL"]
    assert len(content["experience"]) == 1
    assert len(content["projects"]) == 1
    assert len(content["education"]) == 1
    assert content["relevant_links"] == ["https://example.com/p"]


# --- 2. no fabricated defaults ----------------------------------------------

@pytest.mark.parametrize("text", ["", "   \n  \n", "Some Person"])
def test_parse_uploaded_text_does_not_invent_content(text):
    content = parse_uploaded_resume_text(text)
    assert content.email == ""
    assert content.skills == []
    assert content.education == []
    assert content.full_name in ("", "Some Person")
    assert "Candidate" not in content.full_name


def test_empty_name_and_email_reported_missing_by_validation_and_diagnostics():
    content = parse_uploaded_resume_text("")
    report = validate_resume_against_master(content, content)
    assert report.is_valid is False
    assert any("Full Name" in m for m in report.missing_fields)
    assert any("email" in m.lower() for m in report.missing_fields)
    diag = analyze_extraction_diagnostics(content, "")
    assert "Candidate Full Name" in diag["missing_fields"]


def test_validation_rejects_legacy_placeholders():
    placeholder = ResumeContent(
        full_name="Candidate",
        email="candidate@compass.local",
        education=[ResumeEducationItem(institution="MIT", degree="BS")],
    )
    report = validate_resume_against_master(placeholder, placeholder)
    assert report.is_valid is False


def test_linkedin_about_only_input_has_no_fabricated_fields():
    content, _ = parse_pasted_linkedin_text("About\nI build backend systems for fun.")
    assert content.full_name == ""
    assert content.skills == []
    assert content.education == []
    assert content.experience == []


def test_linkedin_items_not_tagged_user_confirmed():
    raw = "Jane Doe\nExperience\nSoftware Engineer\nGoogle · Full-time\nEducation\nStanford University\n"
    content, _ = parse_pasted_linkedin_text(raw)
    assert content.experience and content.education
    assert all(e.evidence_classification is None for e in content.experience)
    assert all(e.evidence_classification is None for e in content.education)
    assert content.evidence_classifications.get("verification") != "USER_CONFIRMED"


def test_data_export_without_skills_yields_no_skills_and_skips_header():
    req = ExternalProfileImportRequest(source_type=ExternalProfileSource.LINKEDIN_DATA_EXPORT, raw_content="")
    content, _ = ingest_external_profile(req)
    assert content.skills == []
    req2 = ExternalProfileImportRequest(
        source_type=ExternalProfileSource.LINKEDIN_DATA_EXPORT, raw_content="Name\nPython\nGo\n"
    )
    content2, _ = ingest_external_profile(req2)
    assert content2.skills == ["Python", "Go"]


def test_default_role_and_company_not_invented():
    content, _ = parse_pasted_linkedin_text("Jane Doe\nExperience\nStaff Wizard\n")
    assert [e.company for e in content.experience] != ["Organization"]
    assert all(e.company != "Organization" and e.role_title != "Engineer" for e in content.experience)


# --- 3. confidence ----------------------------------------------------------

def test_parse_file_result_carries_overall_confidence():
    text = "Jane Doe\njane@example.com\n\nSkills\nPython, Go, SQL, Docker, Git\n"
    result = extract_resume_from_file_bytes(text.encode(), filename="r.txt")
    assert result.success
    assert "overall" in result.field_confidence
    assert 0.0 <= result.field_confidence["overall"] <= 1.0
    assert result.field_confidence["overall"] != 0.85
    assert "overall_confidence" in result.field_confidence


@pytest.mark.asyncio
async def test_parse_upload_response_includes_overall_confidence():
    async with _client() as ac:
        resp = await ac.post(
            "/api/career/resumes/parse-upload", json={"raw_text": "Jane Doe\njane@example.com"}, headers=_headers()
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["full_name"] == "Jane Doe"
    assert "overall" in body["field_confidence"]
    assert "overall_confidence" in body


# --- 4. URL safety ----------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,hi", "file:///etc/passwd", "ftp://x.example/a"])
async def test_external_profile_rejects_non_http_source_url(bad):
    async with _client() as ac:
        resp = await ac.post(
            "/api/career/intelligence/external-profile",
            json={"source_type": "PORTFOLIO_SITE", "raw_content": "see me", "source_url": bad},
            headers=_headers(),
        )
    assert resp.status_code == 422
    assert "http" in resp.text.lower()


@pytest.mark.asyncio
async def test_external_profile_accepts_https_and_caps_raw_content():
    async with _client() as ac:
        ok = await ac.post(
            "/api/career/intelligence/external-profile",
            json={"source_type": "PORTFOLIO_SITE", "raw_content": "x", "source_url": "https://me.example.com"},
            headers=_headers(),
        )
        big = await ac.post(
            "/api/career/intelligence/external-profile",
            json={"source_type": "PORTFOLIO_SITE", "raw_content": "a" * 200001},
            headers=_headers(),
        )
    assert ok.status_code == 200, ok.text
    assert ok.json()["github_or_portfolio"] == "https://me.example.com"
    assert big.status_code == 422


# --- 5. LinkedIn parser -----------------------------------------------------

def test_header_words_inside_sentences_do_not_switch_sections():
    raw = (
        "Jane Doe\nExperience\nSoftware Engineer\nAcme · Full-time\n"
        "Jan 2020 - Present\nLed work about data skills\n"
    )
    content, _ = parse_pasted_linkedin_text(raw)
    assert content.skills == []
    assert len(content.experience) == 1
    assert "Led work about data skills" in content.experience[0].highlights


def test_hyphenated_title_is_not_split_and_bs_is_not_substring():
    raw = "Jane Doe\nExperience\nFull-Stack Engineer at Acme\nEducation\nSomething about Jobs here\n"
    content, _ = parse_pasted_linkedin_text(raw)
    assert content.experience[0].role_title == "Full-Stack Engineer"
    assert content.experience[0].company == "Acme"
    assert content.education == []


def test_long_headline_is_not_taken_as_name():
    headline = "Senior Staff Distributed Systems Engineer building reliable platforms at scale"
    content, _ = parse_pasted_linkedin_text(headline + "\nAbout\nHello")
    assert content.full_name == ""


# --- 6. file parser hardening -----------------------------------------------

@pytest.mark.asyncio
async def test_oversize_upload_rejected_before_parsing(monkeypatch):
    from backend.routers import career

    def boom(*_a, **_k):
        raise AssertionError("parser must not run for oversize uploads")

    monkeypatch.setattr(career, "extract_resume_from_file_bytes", boom)
    big = b"a" * (career_file_parser.MAX_RESUME_FILE_SIZE + 1)
    async with _client() as ac:
        resp = await ac.post(
            "/api/career/resumes/parse-file", files={"file": ("r.txt", big, "text/plain")}, headers=_headers()
        )
    assert resp.status_code in (400, 413)
    assert "5 MB" in resp.text


def test_text_decoding_handles_bom_utf16_and_cp1252():
    body = "Jane Doe\njane@example.com\nSkills\nPython, Go\nCafé Rep\n"
    for raw in (
        b"\xef\xbb\xbf" + body.encode("utf-8"),
        body.encode("utf-16"),
        body.encode("utf-16-be").join([b"\xfe\xff", b""]),
        body.encode("cp1252"),
    ):
        result = extract_resume_from_file_bytes(raw, filename="r.txt")
        assert result.success, result.error_message
        assert result.extracted_content.full_name == "Jane Doe"
        assert "﻿" not in result.raw_text
        assert "�" not in result.raw_text
        assert "Café" in result.raw_text


_PDF_TEXT = "Jane Doe jane@example.com Skills Python Go SQL Docker"


def _tiny_pdf(extra_pages: int = 0, encrypt_owner: bool = False) -> bytes:
    import pypdf

    content = f"BT /F1 12 Tf 72 700 Td ({_PDF_TEXT}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(bytes(out))))
    for _ in range(extra_pages):
        writer.add_blank_page(612, 792)
    if encrypt_owner:
        writer.encrypt(user_password="", owner_password="owner-secret", algorithm="AES-128")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_owner_password_pdf_is_parsed():
    result = extract_resume_from_file_bytes(_tiny_pdf(encrypt_owner=True), filename="r.pdf")
    assert result.success, result.error_message
    assert "Jane Doe" in result.raw_text


def test_pdf_pages_capped_at_15_with_warning():
    result = extract_resume_from_file_bytes(_tiny_pdf(extra_pages=24), filename="r.pdf")
    assert result.success, result.error_message
    assert result.page_count == 25
    joined = " ".join(result.ambiguous_fields) + " " + (result.confidence_warning or "")
    assert "first 15" in joined


def _docx_like_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def test_docx_with_huge_uncompressed_size_rejected():
    data = _docx_like_zip([("word/document.xml", b"\0" * (51 * 1024 * 1024))])
    assert len(data) < career_file_parser.MAX_RESUME_FILE_SIZE
    result = extract_resume_from_file_bytes(data, filename="r.docx")
    assert result.success is False
    assert "uncompressed" in result.error_message.lower()


def test_docx_with_too_many_entries_rejected():
    data = _docx_like_zip([(f"f{i}.xml", b"x") for i in range(2001)])
    result = extract_resume_from_file_bytes(data, filename="r.docx")
    assert result.success is False
    assert "entries" in result.error_message.lower()


@pytest.mark.asyncio
async def test_original_document_stores_full_text_not_preview():
    from backend.memory.career import get_original_resume_document

    text = "Jane Doe\njane@example.com\n" + ("Built many things. " * 400)
    headers = _headers()
    async with _client() as ac:
        resp = await ac.post(
            "/api/career/resumes/parse-file", files={"file": ("r.txt", text.encode(), "text/plain")}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["raw_text"]) <= 3000
        assert "full_text" not in body
        doc_id = body["original_document_id"]
    from backend.dependencies import _get_current_identity  # noqa: F401
    docs = None
    from backend.memory import career as mem

    rec = mem._in_memory_original_resumes[doc_id]
    assert len(rec["raw_text"]) == len(text.strip())
    assert docs is None
    assert await get_original_resume_document(doc_id, rec["user_id"]) is not None


# --- 7. rate limiting -------------------------------------------------------

@pytest.mark.asyncio
async def test_import_endpoints_are_rate_limited():
    headers = _headers()
    statuses = []
    async with _client() as ac:
        for _ in range(35):
            r = await ac.post("/api/career/resumes/parse-upload", json={"raw_text": "Jane Doe"}, headers=headers)
            statuses.append(r.status_code)
    assert 429 in statuses


@pytest.mark.asyncio
async def test_other_import_routes_declare_rate_limit():
    from backend.dependencies import rate_limit

    wanted = {
        "/api/career/resumes/parse-file",
        "/api/career/resumes/parse-upload",
        "/api/career/resumes/commit-extracted",
        "/api/career/intelligence/external-profile",
    }
    found = set()
    from backend.routers.career import router as career_router

    for route in career_router.routes:
        if getattr(route, "path", None) in wanted:
            deps = [d.call for d in route.dependant.dependencies]
            assert rate_limit in deps, route.path
            found.add(route.path)
    assert found == wanted


# --- 8. draft status --------------------------------------------------------

@pytest.mark.asyncio
async def test_draft_status_derived_from_validation_and_named_with_timestamp():
    headers = _headers()
    good = _full_content().model_dump()
    bad = ResumeContent(full_name="No Email", skills=["Python"]).model_dump()
    async with _client() as ac:
        r_good = await ac.post(
            "/api/career/resumes/commit-extracted", json={"content": good, "target": "new_draft"}, headers=headers
        )
        r_bad = await ac.post(
            "/api/career/resumes/commit-extracted", json={"content": bad, "target": "new_draft"}, headers=headers
        )
    assert r_good.status_code == 200 and r_bad.status_code == 200
    assert r_good.json()["validation_status"] == "READY_FOR_REVIEW"
    assert r_bad.json()["validation_status"] != "READY_FOR_REVIEW"
    assert r_good.json()["title"].startswith("Imported Resume Draft (")
    assert r_good.json()["title"].endswith(" UTC)")
