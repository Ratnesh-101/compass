"""Regression tests for the independent radar/career review findings (no database)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.models_radar import OpportunityStatus as OS
from backend.services import radar_jd
from backend.services.career_cover_letter import validate_cover_letter
from backend.services.radar_quality import merge_duplicates, yearly_salary_exceeds_internship_range
from tests.test_radar_data_trust import _opp


# ---- finding 3: Indian pay formats ------------------------------------------------------------
@pytest.mark.parametrize("pay", ["28 LPA", "18-24 LPA", "20 Lakh per annum", "INR 25 lakhs per year", "USD 90,000 / year"])
def test_full_time_yearly_salaries_are_recognised(pay):
    assert yearly_salary_exceeds_internship_range(pay) is True


@pytest.mark.parametrize("pay", ["3 LPA", "INR 15,000 / month", "$25/hour", "Stipend: 20k per month", None, ""])
def test_internship_sized_pay_is_not_flagged(pay):
    assert yearly_salary_exceeds_internship_range(pay) is False


# ---- finding 2 and 4: merged duplicates keep the row and the notes the user touched -------------
def test_the_row_the_user_saved_is_the_one_shown():
    strong = _opp(oid=101, status=OS.OPEN_CONFIRMED)
    saved_but_weaker = _opp(oid=102, status=OS.DISCOVERED).model_copy(update={"is_saved": True})
    merged = merge_duplicates([strong, saved_but_weaker])
    assert merged.id == 102 and merged.is_saved is True  # Unsave sends DELETE for 102, so it really unsaves


def test_notes_and_personal_deadline_survive_without_an_application_stage():
    best = _opp(oid=101, status=OS.OPEN_CONFIRMED)
    noted = _opp(oid=102, status=OS.DISCOVERED).model_copy(
        update={"private_notes": "Met recruiter at the career fair", "personal_deadline": "2026-12-01"}
    )
    merged = merge_duplicates([best, noted])
    assert merged.private_notes == "Met recruiter at the career fair"
    assert str(merged.personal_deadline).startswith("2026-12-01")


# ---- finding 1: a re-check demotion must not be undone by the detail save --------------------------
@pytest.mark.asyncio
async def test_detail_save_writes_the_status_stored_now_not_the_stale_one(monkeypatch):
    stale = _opp(oid=5, status=OS.OPEN_CONFIRMED)
    upsert = AsyncMock(return_value=5)
    monkeypatch.setattr(radar_jd.radar_memory, "upsert_opportunity", upsert)
    monkeypatch.setattr(
        radar_jd.radar_memory, "get_opportunity_by_id",
        AsyncMock(return_value=SimpleNamespace(current_status=OS.NEEDS_VERIFICATION)),
    )
    monkeypatch.setattr(radar_jd.radar_memory, "get_pool", AsyncMock(return_value=object()))
    await radar_jd._persist(stale, "A real description of the role.", None, None)
    assert upsert.await_args.kwargs["current_status"] == OS.NEEDS_VERIFICATION


@pytest.mark.asyncio
async def test_detail_save_falls_back_to_the_given_status_if_the_lookup_fails(monkeypatch):
    opp = _opp(oid=6, status=OS.OPEN_CONFIRMED)
    upsert = AsyncMock(return_value=6)
    monkeypatch.setattr(radar_jd.radar_memory, "upsert_opportunity", upsert)
    monkeypatch.setattr(radar_jd.radar_memory, "get_opportunity_by_id", AsyncMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(radar_jd.radar_memory, "get_pool", AsyncMock(return_value=object()))
    await radar_jd._persist(opp, "desc", None, None)
    assert upsert.await_args.kwargs["current_status"] == OS.OPEN_CONFIRMED


def test_the_recheck_endpoint_passes_the_listing_with_its_new_status():
    src = open("backend/routers/radar.py", encoding="utf-8").read()
    assert 'opp.model_copy(update={"current_status": new_status})' in src
    assert "opportunity=fresh_opp" in src


# ---- finding 5: the ATS check is rate limited like its sibling --------------------------------------
def test_ats_check_has_a_rate_limit_dependency():
    from backend.dependencies import rate_limit
    from backend.routers.career_flow import router

    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/ats-check"))
    assert any(dep.dependency is rate_limit for dep in route.dependencies)


# ---- finding 6: an upcoming calendar year is not an invented figure ----------------------------------
LETTER = (
    "Dear Hiring Team,\n\nI am applying for the Summer 2027 internship at Acme. I built a library app with React.\n\n"
    "Sincerely,\nPriya Sharma"
)


def test_a_near_calendar_year_is_allowed_even_if_the_posting_does_not_repeat_it():
    problems = validate_cover_letter(LETTER, full_name="Priya Sharma", company="Acme", source_text="Summer internship at Acme. React.")
    assert not any("figures" in p for p in problems), problems


def test_an_invented_number_is_still_rejected():
    bad = LETTER.replace("a library app", "a library app used by 5000 students")
    problems = validate_cover_letter(bad, full_name="Priya Sharma", company="Acme", source_text="Summer internship at Acme. React.")
    assert any("figures" in p and "5000" in p for p in problems), problems


# ---- All Listings tab uses the same refinement as the recommendations ---------------------------------
@pytest.mark.asyncio
async def test_all_listings_tab_drops_senior_and_non_india_rows(monkeypatch):
    from backend.routers import radar as radar_router

    india_intern = _opp(oid=1, company="Acme", title="Software Intern", country="India", location="Pune, India")
    senior_us = _opp(oid=2, company="BigCo", title="Sr IT Project Specialist", country="USA", location="Remote, USA", india=False,
                     compensation="USD 90,000 / year")
    monkeypatch.setattr(radar_router, "_get_or_create_user_id", lambda request: "u1")
    monkeypatch.setattr(radar_router, "get_user_opportunity_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(radar_router, "get_all_opportunities", AsyncMock(return_value=([india_intern, senior_us], 2)))
    resp = await radar_router.list_opportunities_endpoint(
        request=SimpleNamespace(), status=None, category=None, employer_type=None, work_arrangement=None,
        country=None, search=None, india_only=True, verified_only=False, recent_24h=False, page=1, page_size=20,
    )
    titles = [o.role_title for o in resp.opportunities]
    assert titles == ["Software Intern"], titles
