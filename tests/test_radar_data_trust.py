"""Internship Radar data trust (WS-C): eligibility honesty, India fit, dedupe, verifier failures, deadlines.

Pure-function tests: no database and no network. NOT RUN by the author (no shell access).
"""
from __future__ import annotations

import urllib.parse
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.models_radar import (
    EligibilityClassification as EC,
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunitySourceOut,
    OpportunityStatus as OS,
    UserOpportunityProfileIn,
)
from backend.services import radar_verifier, security
from backend.services.radar_ats_adapters import (
    is_india_location,
    is_india_or_remote,
    states_india_applicants_accepted,
)
from backend.services.radar_deadline import parse_application_deadline
from backend.services.radar_eligibility import countries_named_in_location, evaluate_eligibility
from backend.services.radar_jd import extract_apply_url, html_to_text
from backend.services.radar_quality import (
    country_rank,
    dedupe_opportunities,
    is_entry_level_listing,
    normalize_company,
    normalize_title,
    recommendation_rank_key,
    refine_listings,
    requires_clearance_or_citizenship,
    yearly_salary_exceeds_internship_range,
)
from backend.skills.handlers.radar import normalize_category


def _opp(oid=1, company="Acme", title="Software Intern", status=OS.OPEN_CONFIRMED, location=None, country="India",
         india=True, compensation=None, description=None, sources=None, verified=None, **reqs) -> OpportunityOut:
    return OpportunityOut(
        id=oid, company_name=company, normalized_company=company.lower(), role_title=title,
        canonical_url=f"https://example.com/{oid}", current_status=status, location=location, country=country,
        is_india_eligible=india, compensation=compensation, description=description,
        sources=sources or [], last_verified_at=verified,
        requirements=OpportunityRequirementsOut(**reqs) if reqs is not None else None,
    )


def _profile(**kw) -> UserOpportunityProfileIn:
    base = dict(degree="B.Tech Computer Science", academic_year=3, grad_year=2027, cgpa=8.0, cgpa_scale=10.0,
                active_backlogs=0, country_of_study="India", country_of_residence="India", skills=["python"])
    base.update(kw)
    return UserOpportunityProfileIn(**base)


# ---- T-015: SNI hostname is a str, failed fetches verify nothing -------------------------------------------
@pytest.mark.asyncio
async def test_pinned_https_fetch_passes_sni_hostname_as_str(monkeypatch):
    seen = {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def build_request(self, method, url, headers=None, extensions=None):
            seen["extensions"] = extensions
            return httpx.Request(method, url, headers=headers)

        async def send(self, req):
            return httpx.Response(200, text="ok", request=req)

    monkeypatch.setattr(security.httpx, "AsyncClient", _Client)
    parsed = urllib.parse.urlsplit("https://example.com/jobs/1")
    resp = await security._send_pinned(["93.184.216.34"], parsed, "example.com", 443, {}, 5.0)
    assert resp.status_code == 200
    assert seen["extensions"]["sni_hostname"] == "example.com"
    assert isinstance(seen["extensions"]["sni_hostname"], str)


@pytest.mark.asyncio
async def test_failed_fetch_is_reported_as_failure_and_keeps_status(monkeypatch):
    monkeypatch.setattr(radar_verifier, "tavily_available", lambda: False)
    monkeypatch.setattr(radar_verifier, "is_safe_url", lambda url: (True, ""))
    monkeypatch.setattr(radar_verifier, "safe_http_get_with_url", AsyncMock(side_effect=RuntimeError("boom")))
    status, evidence, _when = await radar_verifier.verify_opportunity_status(
        "https://boards.greenhouse.io/acme/jobs/1", OS.OPEN_CONFIRMED
    )
    assert status == OS.OPEN_CONFIRMED
    assert radar_verifier.is_fetch_failure(evidence)


def test_is_fetch_failure_classification():
    f = radar_verifier.is_fetch_failure
    assert f("Verification connection timed out or failed: x. Retaining current status.")
    assert f("Verification stopped: DNS rebinding blocked. Retaining current status.")
    assert f("Verification failed with error: application URL was not fetched (x). Retaining current status.")
    assert f("Official page returned HTTP 503. Status retained pending recheck.")
    assert not f("Official page returned HTTP 404 (Requisition Removed).")
    assert not f("Verified open via http_direct: Found active submission trigger 'apply now'.")
    assert not f("")


def test_failed_fetch_never_sets_application_url_checked():
    meta = radar_verifier.verify_opportunity_evidence_metadata(
        "https://example.com/j", OS.OPEN_CONFIRMED, "Verification connection timed out or failed: x. Retaining current status.")
    assert meta["application_url_checked"] is False
    ok = radar_verifier.verify_opportunity_evidence_metadata(
        "https://example.com/j", OS.OPEN_CONFIRMED, "Verified open via http_direct: Found active submission trigger 'apply now'.")
    assert ok["application_url_checked"] is True


def test_should_demote_after_failure_only_when_check_is_old():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    assert not radar_verifier.should_demote_after_failure(OS.OPEN_CONFIRMED, now - timedelta(days=3), now)
    assert radar_verifier.should_demote_after_failure(OS.OPEN_CONFIRMED, now - timedelta(days=30), now)
    assert radar_verifier.should_demote_after_failure(OS.OPEN_CONFIRMED, None, now)
    assert not radar_verifier.should_demote_after_failure(OS.UPCOMING_CONFIRMED, now - timedelta(days=90), now)


# ---- T-016 / N-003: country alone is not an employer requirement -------------------------------------------
def test_country_only_match_is_not_eligible():
    cls, explanation, _ = evaluate_eligibility(_opp(eligible_countries=["India"]), _profile())
    assert cls == EC.POTENTIAL_MATCH
    assert "Requirements not published by the employer" in explanation
    assert "Confirmed eligible" not in explanation


def test_real_check_still_makes_eligible_and_explanation_lists_only_checks_made():
    cls, explanation, _ = evaluate_eligibility(
        _opp(eligible_countries=["India"], eligible_graduation_years=[2027]), _profile())
    assert cls == EC.ELIGIBLE
    assert "graduation year" in explanation and "country" in explanation
    assert "CGPA" not in explanation and "degree" not in explanation


def test_us_canada_listing_does_not_satisfy_india():
    opp = _opp(location="Remote (United States | Canada)", eligible_countries=["India"], eligible_graduation_years=[2027])
    cls, _, reasons = evaluate_eligibility(opp, _profile())
    country = [r for r in reasons if r["field"] == "country"][0]
    assert country["status"] == "fail"
    assert cls == EC.INELIGIBLE


def test_countries_named_in_location_is_whole_word():
    assert countries_named_in_location("Indianapolis, Indiana") == set()
    assert countries_named_in_location("Remote (United States | Canada)") == {"united states", "canada"}
    assert countries_named_in_location("Bengaluru, Karnataka") == {"india"}


# ---- N-014: plain sentences with a next step ---------------------------------------------------------------
def test_ineligible_explanation_is_plain_with_next_step():
    opp = _opp(eligible_degree_types=["Masters", "MS", "M.Tech"])
    cls, explanation, reasons = evaluate_eligibility(opp, _profile())
    assert cls == EC.INELIGIBLE
    assert "Master's degree" in explanation
    assert "B.Tech" in explanation and "Skip it" in explanation
    for ch in "[]{}":
        assert ch not in explanation
    degree = [r for r in reasons if r["field"] == "degree"][0]["detail"]
    assert "[" not in degree and "]" not in degree


# ---- T-017 / N-001: India fit -------------------------------------------------------------------------------
def test_india_fit_requires_india_location_or_explicit_statement():
    assert is_india_or_remote("Bengaluru, India")
    assert not is_india_or_remote("Indianapolis, Indiana")
    assert not is_india_or_remote("APAC")
    assert not is_india_or_remote("Remote (United States | Canada)")
    assert not is_india_or_remote("Remote (Global) United States")
    assert states_india_applicants_accepted("We are open to applicants in India.")
    assert not states_india_applicants_accepted("We are a global company.")
    assert is_india_location("Pune") and not is_india_location("Indiana")


def test_country_rank_puts_own_country_first():
    pc = "india"
    assert country_rank(_opp(country="India"), pc) == 0
    assert country_rank(_opp(country="Global", india=True), pc) == 1
    assert country_rank(_opp(country="Global", india=False), pc) == 2
    assert country_rank(_opp(country="USA", india=True), pc) == 2
    assert country_rank(_opp(country="Global", india=True, location="Remote (United States | Canada)"), pc) == 2


def test_ranking_puts_country_ahead_of_status():
    india_upcoming = _opp(1, "A", country="India", status=OS.UPCOMING_CONFIRMED)
    global_open = _opp(2, "B", country="Global", india=True, status=OS.OPEN_CONFIRMED)
    ranked = sorted([global_open, india_upcoming], key=lambda o: recommendation_rank_key(o, None, "india"))
    assert [o.id for o in ranked] == [1, 2]


def test_senior_clearance_and_salary_listings_are_excluded():
    assert not is_entry_level_listing(_opp(title="Senior Software Engineer Intern"))
    assert not is_entry_level_listing(_opp(title="Staff Engineer"))
    assert not is_entry_level_listing(_opp(title="Engineering Manager"))
    assert is_entry_level_listing(_opp(title="Intern, Product Manager"))
    assert is_entry_level_listing(_opp(title="Software Engineering Intern"))
    assert not is_entry_level_listing(_opp(title="Data Intern", compensation="USD 90,000 - 120,000 / year"))
    assert is_entry_level_listing(_opp(title="Data Intern", compensation="INR 25,000 / month"))
    assert yearly_salary_exceeds_internship_range("INR 2,500,000 / year")
    assert not yearly_salary_exceeds_internship_range("INR 300,000 / year")
    assert requires_clearance_or_citizenship(_opp(description="Active TS/SCI security clearance required"))
    assert requires_clearance_or_citizenship(_opp(description="Must be a U.S. citizen."))
    assert not requires_clearance_or_citizenship(_opp(description="Work with our ML team."))


def test_refine_listings_returns_nothing_when_no_listing_fits():
    items = [
        _opp(1, "UsCo", country="USA", india=False, location="New York, United States"),
        _opp(2, "SrCo", title="Senior Engineer", country="India"),
    ]
    assert refine_listings(items, "india") == []


# ---- T-019 / N-002: dedupe ----------------------------------------------------------------------------------
def test_company_and_title_normalization():
    assert normalize_company("DirecTV, Inc.") == normalize_company("DIRECTV") == "directv"
    assert normalize_company("Acme Technologies Ltd") == "acme"
    assert normalize_title("Software Engineering Internship (Summer 2026)") == normalize_title("software engineering intern summer")


def test_duplicates_merge_into_one_row_with_stricter_requirements():
    glass = _opp(1, "DIRECTV", "Data Intern", status=OS.NEEDS_VERIFICATION,
                 sources=[OpportunitySourceOut(source_name="Glassdoor", source_type="jobspy_glassdoor",
                                               source_url="https://glassdoor.com/1", source_authority="tier_2")])
    official = _opp(2, "DirecTV", "Data Intern", status=OS.OPEN_CONFIRMED, eligible_degree_types=["Masters"],
                    sources=[OpportunitySourceOut(source_name="DirecTV careers", source_type="ats_greenhouse_api",
                                                  source_url="https://boards.greenhouse.io/x", source_authority="tier_1")])
    merged = dedupe_opportunities([glass, official])
    assert len(merged) == 1
    row = merged[0]
    assert row.id == 2 and row.current_status == OS.OPEN_CONFIRMED
    assert len(row.sources) == 2
    assert row.requirements.eligible_degree_types == ["Masters"]
    cls, _, _ = evaluate_eligibility(row, _profile())
    assert cls == EC.INELIGIBLE  # the stricter copy decides: no more opposite verdicts


def test_same_title_in_different_countries_stays_two_listings():
    a = _opp(1, "Acme", "Data Intern", country="India")
    b = _opp(2, "Acme", "Data Intern", country="USA")
    assert len(dedupe_opportunities([a, b])) == 2


# ---- T-018: deadline parser ---------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Apply by March 31, 2027 to be considered.", date(2027, 3, 31)),
    ("Applications close on 15th January 2027.", date(2027, 1, 15)),
    ("Closing date: 2027-02-28", date(2027, 2, 28)),
    ("Last date to apply: 05/04/2027", date(2027, 4, 5)),
    ("Application deadline - Dec 1 2026", date(2026, 12, 1)),
])
def test_parse_application_deadline(text, expected):
    assert parse_application_deadline(text, today=date(2026, 11, 17)) == expected


@pytest.mark.parametrize("text", [
    "", "We love interns.", "Apply by March 31.", "Posted on March 31, 2027.", "Deadline: 31 Feb 2027",
    "Apply by January 1, 2040.",
])
def test_parse_application_deadline_ignores_unstated_or_implausible(text):
    assert parse_application_deadline(text, today=date(2026, 11, 17)) is None


# ---- T-020: description text and apply link -----------------------------------------------------------------
def test_html_to_text_drops_markup():
    out = html_to_text("<html><script>x()</script><h1>Intern</h1><p>Build <b>things</b>.</p><ul><li>Python</li></ul></html>")
    assert "x()" not in out and "<" not in out
    assert "Intern" in out and "Build things" in out and "- Python" in out


def test_extract_apply_url_prefers_employer_link_over_job_boards():
    md = "[Share](https://linkedin.com/share) [Apply now](https://jobs.lever.co/acme/12345678) [Apply on Indeed](https://indeed.com/x)"
    assert extract_apply_url(md, "https://glassdoor.com/job/1") == "https://jobs.lever.co/acme/12345678"
    assert extract_apply_url("no links here", None) is None
    html_page = '<a class="btn" href="https://acme.com/careers/apply/9">Apply for this role</a>'
    assert extract_apply_url(html_page, None) == "https://acme.com/careers/apply/9"


# ---- T-024: category validation -----------------------------------------------------------------------------
def test_category_is_validated_against_enum():
    assert normalize_category("ai_ml") == "ai_ml"
    assert normalize_category("AI_ML") == "ai_ml"
    assert normalize_category("general") is None
    assert normalize_category("made_up") is None
    assert normalize_category(None) is None
    assert normalize_category(5) is None
