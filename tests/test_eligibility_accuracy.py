"""Eligibility accuracy: engine verdict honesty, profile derivation, list/stat consistency, input validation."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.memory.radar import derive_profile_from_master_resume
from backend.models_radar import (
    EligibilityClassification as EC,
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
    UserOpportunityProfileIn,
)
from backend.services.radar_eligibility import _degree_category, evaluate_eligibility


def _opp(country="India", arrangement=None, india=True, **reqs) -> OpportunityOut:
    return OpportunityOut(
        id=1, company_name="Acme", normalized_company="acme", role_title="Intern",
        canonical_url="https://example.com/x", current_status=OpportunityStatus.OPEN_CONFIRMED,
        country=country, work_arrangement=arrangement, is_india_eligible=india,
        requirements=OpportunityRequirementsOut(**reqs),
    )


def _profile(**kw) -> UserOpportunityProfileIn:
    base = dict(degree="B.Tech Computer Science", academic_year=3, grad_year=2027, cgpa=8.0, cgpa_scale=10.0,
                active_backlogs=0, country_of_study="India", country_of_residence="India", skills=["python"])
    base.update(kw)
    return UserOpportunityProfileIn(**base)


def _cls(opp, profile=None):
    return evaluate_eligibility(opp, profile or _profile())[0]


# ---- 2. nothing checked must not be ELIGIBLE --------------------------------
def test_only_preferred_skills_is_insufficient():
    assert _cls(_opp(preferred_skills=["python"])) == EC.INSUFFICIENT_INFORMATION


def test_only_required_skills_is_insufficient():
    assert _cls(_opp(required_skills=["python"])) == EC.INSUFFICIENT_INFORMATION


def test_only_sponsorship_flag_is_insufficient():
    assert _cls(_opp(sponsorship_available=True)) == EC.INSUFFICIENT_INFORMATION


def test_false_flags_are_not_data():
    assert _cls(_opp(work_auth_required=False, no_active_backlogs=False)) == EC.INSUFFICIENT_INFORMATION


def test_countries_without_user_country_is_insufficient():
    p = _profile(country_of_study=None, country_of_residence=None)
    assert _cls(_opp(eligible_countries=["India"]), p) == EC.INSUFFICIENT_INFORMATION


def test_other_mandatory_requirements_cap_at_potential():
    opp = _opp(eligible_graduation_years=[2027], other_mandatory_requirements="Must know Rust")
    assert _cls(opp) == EC.POTENTIAL_MATCH


def test_unknown_requirements_cap_at_potential():
    opp = _opp(eligible_graduation_years=[2027], unknown_requirements=["security clearance"])
    assert _cls(opp) == EC.POTENTIAL_MATCH


def test_real_pass_still_eligible():
    assert _cls(_opp(eligible_graduation_years=[2027], preferred_skills=["go"])) == EC.ELIGIBLE


# ---- 3. unknown profile facts ----------------------------------------------
def test_model_default_backlogs_is_unknown():
    assert UserOpportunityProfileIn().active_backlogs is None


def test_unset_backlogs_is_unknown_not_pass():
    opp = _opp(no_active_backlogs=True, eligible_graduation_years=[2027])
    p = _profile(active_backlogs=None)
    c, _, reasons = evaluate_eligibility(opp, p)
    assert c == EC.POTENTIAL_MATCH
    assert any(r["field"] == "backlogs" and r["status"] == "unknown" for r in reasons)


def test_unset_backlogs_only_requirement_is_not_eligible():
    assert _cls(_opp(no_active_backlogs=True), _profile(active_backlogs=None)) != EC.ELIGIBLE


def test_missing_work_auth_abroad_is_unknown():
    opp = _opp(country="United States", arrangement="onsite", work_auth_required=True, eligible_countries=[])
    p = _profile(work_authorization=None)
    assert _cls(opp, p) == EC.POTENTIAL_MATCH


# ---- 5. degree categories ---------------------------------------------------
@pytest.mark.parametrize("text,cat", [
    ("B.Tech Mechanical Engineering", "undergrad"),
    ("B.E. Biomedical", "undergrad"),
    ("B.Tech Information Systems", "undergrad"),
    ("M.Tech", "masters"),
    ("MS in CS", "masters"),
    ("MBA", "masters"),
    ("BCA", "undergrad"),
    ("B.Sc", "undergrad"),
    ("PhD", "phd"),
    ("Bachelor of Engineering", "undergrad"),
])
def test_degree_category(text, cat):
    assert _degree_category(text) == cat


def test_mech_btech_not_ineligible_for_btech_listing():
    opp = _opp(eligible_degree_types=["B.Tech"])
    assert _cls(opp, _profile(degree="B.Tech Mechanical Engineering")) == EC.ELIGIBLE


# ---- 6. country logic -------------------------------------------------------
def test_us_candidate_fails_india_only_listing():
    opp = _opp(eligible_countries=["India"], india=True)
    p = _profile(country_of_study="USA", country_of_residence="USA")
    assert _cls(opp, p) == EC.INELIGIBLE


def test_short_country_name_not_matched_by_substring():
    opp = _opp(eligible_countries=["India"])
    p = _profile(country_of_study="In", country_of_residence="In")
    assert _cls(opp, p) == EC.INELIGIBLE


def test_usa_alias_matches_united_states():
    opp = _opp(eligible_countries=["United States"])
    p = _profile(country_of_study="USA", country_of_residence="USA")
    assert _cls(opp, p) == EC.ELIGIBLE


# ---- 8. GPA scale -----------------------------------------------------------
def test_gpa_missing_scale_large_min_is_percent():
    opp = _opp(min_gpa=75.0, gpa_scale=None)
    assert _cls(opp, _profile(cgpa=8.0, cgpa_scale=10.0)) == EC.ELIGIBLE
    assert _cls(opp, _profile(cgpa=6.0, cgpa_scale=10.0)) == EC.INELIGIBLE


def test_gpa_missing_scale_small_min_is_unknown():
    opp = _opp(min_gpa=3.0, gpa_scale=None)
    c, _, reasons = evaluate_eligibility(opp, _profile(cgpa=2.0))
    assert c != EC.INELIGIBLE
    assert any(r["field"] == "cgpa" and r["status"] == "unknown" for r in reasons)


# ---- 4/7. derive from resume ------------------------------------------------
def _resume(grade, location="", edu=None):
    return {"education": edu or [{"degree": "B.Tech", "institution": "X", "end_year": 2027, "cgpa_or_grade": grade}],
            "skills": ["python"], "location": location}


@pytest.mark.parametrize("grade,cgpa,scale", [
    ("CGPA: 8.5", 8.5, 10.0),
    ("GPA 3.6/4.0", 3.6, 4.0),
    ("CPI 9.1", 9.1, 10.0),
    ("8.2/10", 8.2, 10.0),
    ("3.8/4", 3.8, 4.0),
    ("85%", 85.0, 100.0),
    ("Top 10%", None, None),
    ("2026", None, None),
    ("CGPA 11.5", None, None),
    ("9.5/4", None, None),
    ("Batch of 2026", None, None),
])
def test_cgpa_parsing(grade, cgpa, scale):
    p = derive_profile_from_master_resume(_resume(grade))
    assert p is not None
    assert p.cgpa == cgpa
    if cgpa is not None:
        assert p.cgpa_scale == scale


def test_derive_never_raises_on_garbage():
    p = derive_profile_from_master_resume(_resume("CGPA 1e9999"))
    assert p is not None and p.cgpa is None


def test_derive_backlogs_unknown():
    assert derive_profile_from_master_resume(_resume("8/10")).active_backlogs is None


@pytest.mark.parametrize("loc,country", [
    ("Bhubaneswar, Odisha", None),
    ("Dwarka, Delhi", None),
    ("Calcutta", None),
    ("Pune, India", "India"),
    ("Seattle, WA, USA", "USA"),
    ("New York, NY, United States", "USA"),
    ("", None),
])
def test_country_derivation(loc, country):
    p = derive_profile_from_master_resume(_resume("8/10", location=loc))
    assert p.country_of_residence == country


def test_latest_education_by_end_year():
    edu = [
        {"degree": "B.Tech", "institution": "Old", "end_year": 2024, "cgpa_or_grade": "7/10"},
        {"degree": "M.Tech", "institution": "New", "end_year": 2027, "cgpa_or_grade": "9/10"},
    ]
    p = derive_profile_from_master_resume(_resume("", edu=edu))
    assert p.degree == "M.Tech" and p.grad_year == 2027


def test_first_education_when_no_years():
    edu = [{"degree": "B.Tech", "institution": "A"}, {"degree": "M.Tech", "institution": "B"}]
    assert derive_profile_from_master_resume(_resume("", edu=edu)).degree == "B.Tech"


# ---- 9/10. DB-backed -------------------------------------------------------
async def _seed(status, **reqs) -> int:
    from backend.memory.radar import upsert_opportunity, upsert_opportunity_requirements
    tag = uuid.uuid4().hex[:8]
    oid = await upsert_opportunity(
        company_name=f"AccCo{tag}", role_title=f"Intern {tag}", canonical_url=f"https://acc.example/{tag}",
        current_status=status, country="India", is_india_eligible=True,
    )
    await upsert_opportunity_requirements(oid, reqs)
    return oid


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_recommended_matches_eligible_stat_and_excludes_noise():
    user = f"acc_user_{uuid.uuid4().hex[:6]}"
    reqs = dict(eligible_graduation_years=[2027], eligible_degree_types=["B.Tech"])
    open_id = await _seed(OpportunityStatus.OPEN_CONFIRMED, **reqs)
    closed_id = await _seed(OpportunityStatus.CLOSED_CONFIRMED, **reqs)
    disc_id = await _seed(OpportunityStatus.DISCOVERED, **reqs)
    bad_id = await _seed(OpportunityStatus.OPEN_CONFIRMED, eligible_graduation_years=[2020])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": user}) as c:
        r = await c.put("/api/opportunities/profile", json={
            "degree": "B.Tech", "academic_year": 3, "grad_year": 2027, "cgpa": 8.0, "skills": ["python"]})
        assert r.status_code == 200
        rec = await c.get("/api/opportunities/recommended?limit=50")
        assert rec.status_code == 200
        ids = {o["id"] for o in rec.json()}
        assert open_id in ids
        assert closed_id not in ids and disc_id not in ids and bad_id not in ids
        assert all(o["eligibility_classification"] != "INELIGIBLE" for o in rec.json())
        strict = await c.get("/api/opportunities/recommended?limit=50&eligible_only=true")
        stats = await c.get("/api/opportunities/analytics")
        n_eligible = len(strict.json())
        assert n_eligible <= 50
        assert stats.json()["strong_matches_count"] == n_eligible


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_opening_soon_stat_matches_upcoming_list_filter():
    user = f"acc_user_{uuid.uuid4().hex[:6]}"
    await _seed(OpportunityStatus.UPCOMING_CONFIRMED, eligible_graduation_years=[2027])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": user}) as c:
        up = await c.get("/api/opportunities/upcoming")
        stats = await c.get("/api/opportunities/analytics")
        assert all(o["current_status"] in ("UPCOMING_CONFIRMED", "ANNOUNCED") for o in up.json())
        assert stats.json()["opening_soon_count"] == len(up.json())


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_unknown_opportunity_returns_404_and_bad_status_422():
    user = f"acc_user_{uuid.uuid4().hex[:6]}"
    oid = await _seed(OpportunityStatus.OPEN_CONFIRMED, eligible_graduation_years=[2027])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": user}) as c:
        missing = 2_000_000_000
        assert (await c.post(f"/api/opportunities/{missing}/save")).status_code == 404
        assert (await c.delete(f"/api/opportunities/{missing}/save")).status_code == 404
        assert (await c.post(f"/api/opportunities/{missing}/application", json={"application_status": "applied"})).status_code == 404
        assert (await c.post(f"/api/opportunities/{oid}/application", json={"application_status": ""})).status_code == 422
        assert (await c.post(f"/api/opportunities/{oid}/application", json={"application_status": "bogus"})).status_code == 422
        assert (await c.post(f"/api/opportunities/{oid}/application", json={"application_status": "applied"})).status_code == 200
        apps = await c.get("/api/opportunities/applications")
        stats = await c.get("/api/opportunities/analytics")
        assert stats.json()["applications_in_progress_count"] == len(apps.json()) == 1
