"""Tests for the factual-claim verifier service and its router.

All search and fetch calls are injected fakes. No network, no database.
Sample data is invented.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.models_career import (
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
)
from backend.services import claim_verifier as cv


# ---------------------------------------------------------------- helpers

def _plain(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


def _get(obj, *names, default=None):
    obj = _plain(obj)
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return default


def _entity(claim) -> str:
    return str(_get(claim, "entity", "name", "claim", "text", default=""))


def _kind(claim) -> str:
    return str(_get(claim, "kind", "type", "category", default=""))


def _status(check) -> str:
    if isinstance(check, tuple):
        return str(check[0])
    return str(_get(check, "status", default=""))


def _evidence(check) -> list:
    if isinstance(check, tuple):
        return list(check[1])
    return list(_get(check, "evidence", default=[]))


def _note(check) -> str:
    if isinstance(check, tuple):
        return str(check[2])
    return str(_get(check, "note", default=""))


def _checks(report):
    return list(_get(report, "checks", "claims", default=[]))


def _counts(report):
    return {
        "found": report.found,
        "not_found": report.not_found,
        "cannot_check": report.cannot_check,
        "error": report.errors,
    }


def _run(coro):
    return asyncio.run(coro)


def _content(**kw) -> ResumeContent:
    base = dict(full_name="Asha Verma", email="asha@example.com")
    base.update(kw)
    return ResumeContent(**base)


def _full_content() -> ResumeContent:
    return _content(
        education=[
            ResumeEducationItem(
                institution="Riverbend Institute of Technology",
                degree="B.Tech",
            )
        ],
        experience=[
            ResumeExperienceItem(company="Northwind Labs Pvt Ltd", role_title="Developer")
        ],
        internships=[
            ResumeExperienceItem(company="Bluefin Systems Inc", role_title="Intern")
        ],
        certifications=["Cloud Practitioner Certificate from Harbor Academy"],
        hackathons=["Smart City Hackathon 2024"],
        publications=["Graph methods for campus routing"],
        relevant_links=["https://example.org/asha"],
    )


def _result(title, url="https://example.org/x", snippet="", score=0.9):
    return {"title": title, "url": url, "content": snippet, "snippet": snippet, "score": score}


# ---------------------------------------------------------------- extract_claims

def test_extract_claims_limits_to_twelve():
    content = _content(
        experience=[
            ResumeExperienceItem(company=f"Zephyr Works {chr(65 + i)}{chr(75 + i)}", role_title="Dev")
            for i in range(10)
        ],
        certifications=[f"Certificate Number {chr(97 + i)}{chr(110 + i)} Board" for i in range(10)],
    )
    assert len(cv.extract_claims(content)) <= 12


def test_extract_claims_priority_education_first():
    claims = cv.extract_claims(_full_content())
    assert claims
    assert "riverbend" in _entity(claims[0]).lower()


def test_extract_claims_dedupes_case_insensitively():
    content = _content(
        experience=[ResumeExperienceItem(company="Northwind Labs Pvt Ltd", role_title="Dev")],
        internships=[ResumeExperienceItem(company="NORTHWIND LABS PVT LTD", role_title="Intern")],
    )
    names = [_entity(c).lower() for c in cv.extract_claims(content)]
    assert sum("northwind" in n for n in names) == 1


@pytest.mark.parametrize("placeholder", ["Compass Candidate", "N/A", "TBD"])
def test_extract_claims_skips_placeholders(placeholder):
    content = _content(
        experience=[ResumeExperienceItem(company=placeholder, role_title="Dev")],
    )
    names = [_entity(c).lower() for c in cv.extract_claims(content)]
    assert not any(placeholder.lower() == n for n in names)


def test_extract_claims_empty_resume_gives_no_claims():
    assert list(cv.extract_claims(_content())) == []


# ---------------------------------------------------------------- evaluate_search_result

def test_evaluate_found_on_title_match():
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [_result("Northwind Labs - Company profile", score=0.8)],
    )
    assert _status(out) == "found"


def test_evaluate_found_on_url_host():
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [_result("Home", url="https://www.northwindlabs.example/about", score=0.8)],
    )
    assert _status(out) == "found"


def test_evaluate_found_on_concatenated_domain_host():
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [_result("Home", url="https://northwindlabs.example/", score=0.8)],
    )
    assert _status(out) == "found"


def test_evaluate_found_on_snippet():
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [_result("Directory", snippet="Northwind Labs builds tools for logistics.", score=0.7)],
    )
    assert _status(out) == "found"


def test_evaluate_low_score_snippet_is_ignored():
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [_result("Directory", snippet="Northwind Labs", score=0.2)],
    )
    assert _status(out) == "not_found"


def test_evaluate_legal_suffix_alone_does_not_match():
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [_result("Other Company Pvt Ltd", snippet="A Pvt Ltd company", score=0.9)],
    )
    assert _status(out) == "not_found"


def test_evaluate_university_of_prefix_ignored():
    out = cv.evaluate_search_result(
        "University of Riverbend",
        [_result("Admissions at University of Lakeshore", score=0.9)],
    )
    assert _status(out) == "not_found"


def test_evaluate_not_found_note_and_wording():
    out = cv.evaluate_search_result("Northwind Labs Pvt Ltd", [])
    assert _status(out) == "not_found"
    text = (_note(out) + " " + _status(out)).lower()
    assert "does not mean" in text
    assert "fake" not in text


def test_evaluate_sanitises_titles_and_urls():
    long_title = "Northwind Labs " + "<b>x</b>" * 100
    out = cv.evaluate_search_result(
        "Northwind Labs Pvt Ltd",
        [
            _result(long_title, url="https://example.org/ok", score=0.9),
            _result("Northwind Labs", url="javascript:alert(1)", score=0.9),
            _result("Northwind Labs", url="ftp://example.org/file", score=0.9),
        ],
    )
    evidence = _evidence(out)
    assert evidence
    for item in evidence:
        url = str(_get(item, "url", default=""))
        title = str(_get(item, "title", default=""))
        assert url.startswith(("http://", "https://"))
        assert len(title) <= 200


# ---------------------------------------------------------------- verify_claims

def test_verify_found_with_up_to_three_evidence():
    async def search(query, **kw):
        return {"results": [
            _result(f"Northwind Labs page {i}", url=f"https://example.org/p{i}")
            for i in range(6)
        ]}

    async def fetch(url, **kw):
        return 200

    content = _content(
        experience=[ResumeExperienceItem(company="Northwind Labs Pvt Ltd", role_title="Dev")]
    )
    report = _run(cv.verify_claims(content, search=search, fetch=fetch))
    checks = _checks(report)
    assert len(checks) == 1
    assert _status(checks[0]) == "found"
    assert 1 <= len(_get(checks[0], "evidence", default=[])) <= 3
    assert _get(report, "tavily_used") is True


def test_verify_results_for_other_company_not_found():
    async def search(query, **kw):
        return {"results": [_result("Contoso Holdings overview", snippet="Contoso Holdings")]}

    content = _content(
        experience=[ResumeExperienceItem(company="Northwind Labs Pvt Ltd", role_title="Dev")]
    )
    report = _run(cv.verify_claims(content, search=search, fetch=None))
    assert _status(_checks(report)[0]) == "not_found"


def test_verify_search_unavailable_marks_web_claims_cannot_check():
    async def search(query, **kw):
        raise RuntimeError("no key")

    async def fetch(url, **kw):
        return 200

    report = _run(cv.verify_claims(_full_content(), search=search, fetch=fetch))
    assert _get(report, "tavily_used") is False
    web = [c for c in _checks(report) if _kind(c) not in ("link", "self_reported")]
    assert web
    assert all(_status(c) == "cannot_check" for c in web)
    notice = str(_get(report, "notice", default=""))
    assert "Online checking" in notice
    assert "not available" in notice


def test_verify_single_search_error_isolated():
    async def search(query, **kw):
        if "Bluefin" in query:
            raise ValueError("boom")
        return {"results": [_result("Northwind Labs", snippet="Northwind Labs Riverbend")]}

    content = _content(
        experience=[ResumeExperienceItem(company="Northwind Labs Pvt Ltd", role_title="Dev")],
        internships=[ResumeExperienceItem(company="Bluefin Systems Inc", role_title="Intern")],
    )
    report = _run(cv.verify_claims(content, search=search, fetch=None))
    by_entity = {_entity(c): _status(c) for c in _checks(report)}
    assert len(by_entity) == 2
    statuses = {k: v for k, v in by_entity.items()}
    assert [v for k, v in statuses.items() if "Bluefin" in k] == ["error"]
    assert [v for k, v in statuses.items() if "Northwind" in k] == ["found"]


@pytest.mark.parametrize(
    "outcome,expected",
    [(200, "found"), (404, "not_found"), (403, "cannot_check")],
)
def test_verify_link_status_codes(outcome, expected):
    async def search(query, **kw):
        return []

    async def fetch(url, **kw):
        return outcome

    content = _content(relevant_links=["https://example.org/asha"])
    report = _run(cv.verify_claims(content, search=search, fetch=fetch))
    checks = [c for c in _checks(report) if _kind(c) == "link"]
    assert len(checks) == 1
    assert _status(checks[0]) == expected


@pytest.mark.parametrize("exc", [asyncio.TimeoutError(), RuntimeError("down")])
def test_verify_link_exception_is_error(exc):
    async def search(query, **kw):
        return []

    async def fetch(url, **kw):
        raise exc

    content = _content(relevant_links=["https://example.org/asha"])
    report = _run(cv.verify_claims(content, search=search, fetch=fetch))
    checks = [c for c in _checks(report) if _kind(c) == "link"]
    assert [_status(c) for c in checks] == ["error"]


def test_verify_counts_and_summary_match_checks():
    async def search(query, **kw):
        if "Northwind" in query:
            return {"results": [_result("Northwind Labs", snippet="Northwind Labs")]}
        return {"results": []}

    async def fetch(url, **kw):
        return 404

    report = _run(cv.verify_claims(_full_content(), search=search, fetch=fetch))
    checks = _checks(report)
    counts = _counts(report)
    for status in ("found", "not_found", "cannot_check", "error"):
        expected = sum(1 for c in checks if _status(c) == status)
        assert counts.get(status, 0) == expected, status
    summary = str(_get(report, "summary", default=""))
    assert summary
    assert str(counts.get("found", 0)) in summary
    assert str(len(checks)) in summary
    assert "fake" not in summary.lower()


def test_verify_never_raises_on_bad_inputs():
    async def search(query, **kw):
        raise Exception("anything")

    async def fetch(url, **kw):
        raise Exception("anything")

    report = _run(cv.verify_claims(_full_content(), search=search, fetch=fetch))
    assert report is not None
    report = _run(cv.verify_claims(_content(), search=search, fetch=fetch))
    assert report is not None


def test_verify_preserves_claim_order_under_concurrency():
    async def search(query, **kw):
        # Earlier claims answer later, so completion order is reversed.
        delay = 0.05 if "Riverbend" in query else 0.0
        await asyncio.sleep(delay)
        return []

    async def fetch(url, **kw):
        return 200

    content = _full_content()
    expected = [_entity(c) for c in cv.extract_claims(content)]
    report = _run(cv.verify_claims(content, search=search, fetch=fetch))
    assert [_entity(c) for c in _checks(report)] == expected


def test_own_work_statement_is_self_reported_cannot_check():
    content = _content(
        achievements=["Built a personal budgeting app on my own"],
        hackathons=[],
    )
    claims = list(cv.extract_claims(content))
    own = [c for c in claims if _kind(c) == "self_reported"]
    web = [c for c in claims if _kind(c) != "self_reported"]
    assert len(own) <= 1
    assert not any("budgeting" in _entity(c).lower() for c in web)

    async def search(query, **kw):
        raise AssertionError("own-work must not be searched")

    report = _run(cv.verify_claims(content, search=search, fetch=None))
    own_checks = [c for c in _checks(report) if _kind(c) == "self_reported"]
    assert own_checks
    assert all(_status(c) == "cannot_check" for c in own_checks)


# ---------------------------------------------------------------- router

class _FakeResume:
    def __init__(self):
        self.content = _content()
        self.is_master = True
        self.opportunity_id = None


@pytest.fixture
def router_mod(monkeypatch):
    from backend.routers import career_claims as mod

    monkeypatch.setattr(mod, "_user_cooldowns", {})
    monkeypatch.setattr(mod, "_get_or_create_user_id", lambda request: "u-asha")

    async def noop(*a, **kw):
        return None

    async def fake_verify(*a, **kw):
        return cv.ClaimVerificationReport(summary="ok")

    monkeypatch.setattr(mod, "get_master_resume", noop)
    monkeypatch.setattr(mod, "get_opportunity_by_id", noop)
    monkeypatch.setattr(mod, "update_resume", noop)
    monkeypatch.setattr(mod, "verify_claims", fake_verify)
    monkeypatch.setattr(
        mod,
        "validate_resume_against_master",
        lambda *a, **kw: type("R", (), {"is_valid": True})(),
    )
    return mod


def _call(mod, resume_id=1):
    return _run(mod.verify_resume_claims_endpoint(resume_id, object()))


def test_router_registers_verify_claims_path():
    from backend.routers import career_claims as mod

    paths = [getattr(r, "path", "") for r in mod.router.routes]
    assert any(p.endswith("/resumes/{resume_id}/verify-claims") for p in paths)


def test_router_unknown_resume_is_404(monkeypatch, router_mod):
    async def missing(*a, **kw):
        return None

    monkeypatch.setattr(router_mod, "get_resume_by_id", missing)
    with pytest.raises(HTTPException) as exc:
        _call(router_mod, resume_id=999)
    assert exc.value.status_code == 404


def test_router_second_call_within_20s_is_429_and_success_returns_report(
    monkeypatch, router_mod
):
    async def found(*a, **kw):
        return _FakeResume()

    monkeypatch.setattr(router_mod, "get_resume_by_id", found)
    first = _call(router_mod)
    assert isinstance(first, cv.ClaimVerificationReport)
    assert first.summary == "ok"
    with pytest.raises(HTTPException) as exc:
        _call(router_mod)
    assert exc.value.status_code == 429
    detail = str(exc.value.detail)
    assert detail and "Traceback" not in detail
