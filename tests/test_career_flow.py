"""Automatic application flow helpers (WS-D): apply-by date, pasted links, tailoring changes, ATS estimate,
company intel summary. Pure functions plus the in-memory listing store; no network, no database."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.models_career import (
    CareerApplicationStatus,
    ResumeContent,
    ResumeEducationItem,
    ResumeProjectItem,
    ResumeValidationStatus,
)
from backend.models_radar import OpportunityOut, OpportunityRequirementsOut
from backend.services import career_flow as flow
from backend.services.ats_check import extract_keywords, simulate_ats_check
from backend.services.career_resume import tailor_resume_for_opportunity
from backend.services.career_tailor_changes import attach_changes, compute_tailor_changes
from backend.services.company_intel_jobs import build_sources_only_fallback
from backend.services.company_intel_summary import UNAVAILABLE_MESSAGE, extractive_summary, is_scrape_dump
from backend.services.winning_features import simulate_ats_parsing


def _opp(skills=None, description="General internship working with the team.", **over):
    base = dict(
        id=11,
        company_name="Acme",
        normalized_company="acme",
        role_title="Software Intern",
        category="swe",
        location="Remote",
        description=description,
        canonical_url="https://example.com/acme/11",
        current_status="open_confirmed",
        source="devpost",
        requirements=OpportunityRequirementsOut(required_skills=skills or []),
    )
    base.update(over)
    return OpportunityOut(**base)


def _master(skills):
    return ResumeContent(
        full_name="Priya Sharma",
        email="priya@example.com",
        skills=skills,
        education=[ResumeEducationItem(institution="Pune Institute of Technology", degree="B.Tech", start_year=2024, end_year=2028)],
        projects=[
            ResumeProjectItem(title="Notes App", description="A notes app.", technologies=["Go"]),
            ResumeProjectItem(title="Web Shop", description="A shop.", technologies=["React"]),
        ],
    )


# --- apply-by date and Timeline task -------------------------------------------------------------

def test_apply_by_uses_the_listing_close_date_when_it_is_ahead():
    today = date(2026, 11, 17)
    assert flow.apply_by_date(date(2026, 12, 1), today) == (date(2026, 12, 1), "listing")
    assert flow.apply_by_date(today, today) == (today, "listing")


def test_apply_by_defaults_to_seven_days():
    today = date(2026, 11, 17)
    assert flow.apply_by_date(None, today) == (today + timedelta(days=7), "default")
    assert flow.apply_by_date(date(2026, 11, 1), today) == (today + timedelta(days=7), "default")


# --- pasted job links ----------------------------------------------------------------------------

def test_job_link_is_cleaned_and_validated():
    assert flow.normalize_job_url("https://Boards.Greenhouse.io/acme/jobs/123/?utm_source=x&gh_jid=123#apply") == (
        "https://boards.greenhouse.io/acme/jobs/123?gh_jid=123"
    )
    assert flow.normalize_job_url("careers.example.com/intern").startswith("https://careers.example.com/")
    for bad in ("", "   ", "ftp://example.com/x", "javascript:alert(1)", "https://" + "a" * 2100):
        with pytest.raises(ValueError):
            flow.normalize_job_url(bad)


def test_company_name_comes_from_the_link():
    assert flow.company_from_url("https://boards.greenhouse.io/acmecorp/jobs/123") == "Acmecorp"
    assert flow.company_from_url("https://jobs.lever.co/my-co/abc") == "My Co"
    assert flow.company_from_url("https://acme.wd1.myworkdayjobs.com/en-US/careers") == "Acme"
    assert flow.company_from_url("https://careers.stripe.com/jobs/1") == "Stripe"


def test_listing_identity_from_page_text():
    assert flow.infer_listing_identity("Job Application for Software Engineer Intern at Acme Robotics\nApply", "https://x.io/1") == (
        "Acme Robotics",
        "Software Engineer Intern",
    )
    assert flow.infer_listing_identity("# Data Science Intern\nAbout the role", "https://careers.stripe.com/j/1") == ("Stripe", "Data Science Intern")
    assert flow.infer_listing_identity("Backend Intern - Zeta Labs\nWhat you will do", "https://x.io/1") == ("Zeta Labs", "Backend Intern")
    company, role = flow.infer_listing_identity("", "https://careers.stripe.com/j/1")
    assert company == "Stripe" and role == "Role from a pasted link"


@pytest.mark.asyncio
async def test_pasted_link_creates_a_listing_hidden_from_other_users_and_prepares_it(monkeypatch):
    from backend.memory import radar as radar_memory
    from backend.services import radar_jd, security

    monkeypatch.setattr(radar_memory, "get_pool", AsyncMock(return_value=None))  # in-memory store
    monkeypatch.setattr(radar_memory, "_in_memory_opportunities", {})
    monkeypatch.setattr(radar_memory, "get_user_opportunity_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(radar_memory, "upsert_user_saved_opportunity", AsyncMock())
    monkeypatch.setattr(security, "is_safe_url", lambda url: (True, ""))
    page_text = "Software Engineer Intern at Acme Robotics\n" + "You will build tools for our robots. " * 20 + "\nApplications close on 30 November 2026."
    monkeypatch.setattr(radar_jd, "_fetch_page_text", AsyncMock(return_value={"text": page_text, "raw": page_text, "method": "http_direct"}))
    prepared = AsyncMock(return_value="prepared-app")
    monkeypatch.setattr(flow, "prepare_application_for_user", prepared)
    monkeypatch.setattr(flow, "log_application_event", AsyncMock())

    class _App:
        id = 1

    prepared.return_value = _App()
    result = await flow.prepare_from_link("user-1", "https://careers.acme.example/jobs/42?utm_source=x", lambda profile: ResumeContent())
    assert isinstance(result, _App)

    rows = list(radar_memory._in_memory_opportunities.values())
    assert len(rows) == 1
    row = rows[0]
    assert row["role_title"] == "Software Engineer Intern" and row["company_name"] == "Acme Robotics"
    assert row["canonical_url"] == "https://careers.acme.example/jobs/42"
    assert row["is_india_eligible"] is False  # not shown in anyone else's India-filtered lists
    assert len(row["description"]) > 200
    prepared.assert_awaited_once()


@pytest.mark.asyncio
async def test_pasted_link_that_cannot_be_read_gives_a_plain_message(monkeypatch):
    from backend.services import radar_jd, security

    monkeypatch.setattr(security, "is_safe_url", lambda url: (True, ""))
    monkeypatch.setattr(radar_jd, "_fetch_page_text", AsyncMock(return_value={}))
    monkeypatch.setattr(flow, "find_opportunity_id_by_url", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as err:
        await flow.prepare_from_link("user-1", "https://careers.acme.example/jobs/42", lambda profile: ResumeContent())
    assert err.value.status_code == 422
    assert "couldn't read that page" in err.value.detail


@pytest.mark.asyncio
async def test_pasted_link_to_an_internal_address_is_refused():
    with pytest.raises(HTTPException) as err:
        await flow.prepare_from_link("user-1", "http://169.254.169.254/latest/meta-data", lambda profile: ResumeContent())
    assert err.value.status_code == 422


def test_resume_status_after_attaching_a_tailored_copy():
    ready, failed = ResumeValidationStatus.READY_FOR_REVIEW, ResumeValidationStatus.VALIDATION_FAILED
    assert flow.resume_status_for(CareerApplicationStatus.PREPARING, ready) == "READY_FOR_REVIEW"
    assert flow.resume_status_for(CareerApplicationStatus.SAVED, failed) == "RESUME_VALIDATION_FAILED"
    assert flow.resume_status_for(CareerApplicationStatus.SUBMITTED, ready) is None


def test_missing_profile_fields_are_named():
    assert flow.missing_profile_fields(ResumeContent()) == ["Full name", "Email address", "Phone number", "Education history"]
    assert flow.missing_profile_fields(_master(["Python"])) == ["Phone number"]


# --- "What changed" after tailoring ---------------------------------------------------------------

def test_what_changed_lists_moved_skills_and_projects():
    master = _master(["SQL", "Python", "React"])
    opp = _opp(skills=["Python", "React"], description="Build web tools with React.")
    tailored, report, _status = tailor_resume_for_opportunity(master, opp)
    changes = compute_tailor_changes(master, tailored, opp)
    assert changes["changed"] is True
    assert changes["skills_moved_up"] == ["Python", "React"]
    assert changes["projects_reordered"] == ["Web Shop", "Notes App"]
    assert changes["skills_added"] == [] and changes["bullets_rephrased"] == 0
    assert any(line.startswith("Skills moved to the front") for line in changes["lines"])
    assert changes["preview"]["skills"][:2] == ["Python", "React"]
    assert "never adds" in changes["note"]
    attach_changes(report, master, tailored, opp)
    assert report.diff_summary["what_changed"]["changed"] is True


def test_what_changed_explains_when_the_posting_lists_no_skills():
    master = _master(["Cooking"])
    opp = _opp(skills=[], description="Join our friendly team.")
    tailored, _report, _status = tailor_resume_for_opportunity(master, opp)
    changes = compute_tailor_changes(master, tailored, opp)
    assert changes["changed"] is False
    assert changes["reason_if_unchanged"] == "This posting lists no skills we could match."


def test_what_changed_explains_when_the_order_was_already_right():
    master = ResumeContent(skills=["Python", "SQL"], projects=[])
    opp = _opp(skills=["Python"])
    tailored, _report, _status = tailor_resume_for_opportunity(master, opp)
    changes = compute_tailor_changes(master, tailored, opp)
    assert changes["changed"] is False
    assert "already puts the skills" in changes["reason_if_unchanged"]


def test_what_changed_for_an_empty_resume():
    master = ResumeContent()
    changes = compute_tailor_changes(master, master, _opp(skills=["Python"]))
    assert changes["changed"] is False and "nothing to reorder" in changes["reason_if_unchanged"]


# --- ATS check ------------------------------------------------------------------------------------

def test_ats_estimate_is_labelled_and_lists_gaps():
    resume = _master(["Python", "SQL"])
    report = simulate_ats_check(resume, ["Python", "Kubernetes"], "Role: Backend Intern. We use Kubernetes and Terraform.")
    assert report["is_estimate"] is True and report["label"] == "estimate"
    assert "Contact details" in report["detected_sections"] and "Education" in report["detected_sections"]
    assert "Kubernetes" in report["missing_critical_keywords"] and "Python" not in report["missing_critical_keywords"]
    assert 0 <= report["score"] <= 100
    assert any("phone" in w.lower() for w in report["formatting_warnings"])
    assert "Priya Sharma" in report["parsed_text_preview"]


def test_ats_entry_point_used_by_the_route_accepts_the_job_inputs():
    report = simulate_ats_parsing(_master(["Python"]), ["Python"], "Python role")
    assert report["missing_critical_keywords"] == []
    assert simulate_ats_parsing("Experience: Software Developer")["label"] == "estimate"


def test_job_keywords_prefer_listed_skills_and_skip_filler_words():
    kw = extract_keywords(["Python"], "We want Python, TypeScript and C++ people. Strong team work. Experience with FastAPI.")
    assert kw[0] == "Python"
    assert "TypeScript" in kw and "C++" in kw and "FastAPI" in kw
    assert "Strong" not in kw and "Experience" not in kw


# --- company intel summary --------------------------------------------------------------------------

def test_scraped_field_dumps_are_not_sentences():
    assert is_scrape_dump("1Password ID: Jwu4pnzXlRGp Website: www.1password.com Headquarters: Toronto")
    assert is_scrape_dump("See https://example.com for details about the company and more")
    assert not is_scrape_dump("1Password builds password management software for families and businesses.")


def test_extractive_summary_quotes_whole_sentences_up_to_three():
    sources = [
        {"id": 1, "snippet": "1Password ID: Jwu4pnzXlRGp Website: www.1password.com Headquarters: Toronto."},
        {"id": 2, "snippet": "1Password builds password management software for families and businesses. It was founded in 2005."},
        {"id": 3, "snippet": "The company employs engineers across many countries and time zones today."},
        {"id": 4, "snippet": "Its products are used by millions of people around the world every day."},
        {"id": 5, "snippet": "Another readable sentence that should not make it into the short summary."},
    ]
    summary = extractive_summary(sources)
    assert summary.count(".") == 3
    assert "Jwu4" not in summary and "It was founded" not in summary
    assert summary.startswith("1Password builds password management software")


def test_fallback_brief_has_a_summary_and_never_says_summary_unavailable():
    sources = [{"id": 1, "title": "About", "domain": "x.com", "url": "https://x.com", "snippet": "Stripe processes billions of dollars in payments for online businesses each year."}]
    brief = build_sources_only_fallback(sources, "Stripe", "Intern", reason="model_timeout")
    assert brief["status"] == "ready" and brief["is_sources_only"] is True
    assert brief["summary"].startswith("Stripe processes billions")
    assert "unavailable" not in brief["summary"].lower() and "unavailable" not in brief["fallback_label"].lower()
    assert brief["reason"] == "model_timeout"


def test_fallback_brief_with_only_scraped_text_is_one_plain_message():
    sources = [{"id": 1, "title": "Profile", "domain": "x.com", "url": "https://x.com", "snippet": "1Password ID: Jwu4pnzXlRGp Website: www.1password.com Headquarters: Toronto."}]
    brief = build_sources_only_fallback(sources, "1Password", "Intern", reason="model_failed")
    assert brief["status"] == "error"
    assert brief["error"] == UNAVAILABLE_MESSAGE == "Couldn't summarise this company right now."
    assert brief["priorities"] == [] and brief["role_context"] == [] and brief["challenges"] == []
