"""Regression tests for radar/matching fixes (each fails on the pre-fix code)."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.memory import radar as radar_mem
from backend.models_radar import OpportunityStatus, UserOpportunityProfileIn
from backend.routers.auth import create_session
from backend.services.career_job_match import analyze_job_and_match


async def _insert_opportunity(key: str, n: int) -> int:
    """Insert via SQL with the DB-generated id (the in-process id sequence can collide with test data)."""
    pool = await radar_mem.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO opportunities (id, company_name, normalized_company, role_title, canonical_url, current_status) "
            "VALUES ((SELECT COALESCE(MAX(id), 0) + 1 FROM opportunities), $1, $2, $3, $4, 'NEEDS_VERIFICATION') RETURNING id",
            f"Co{key}", f"co{key}", f"Role {n}", f"https://co{key}.example/jobs/{n}",
        )


async def _cleanup(key: str, user: str = "") -> None:
    """Remove rows created by these tests so the shared test DB (and its id sequence) stays clean."""
    pool = await radar_mem.get_pool()
    async with pool.acquire() as conn:
        ids = [r["id"] for r in await conn.fetch("SELECT id FROM opportunities WHERE normalized_company = $1", f"co{key}")]
        for table in ("user_opportunities", "opportunity_requirements", "opportunity_sources", "opportunity_cycles"):
            await conn.execute(f"DELETE FROM {table} WHERE opportunity_id = ANY($1::int[])", ids)  # nosec B608
        await conn.execute("DELETE FROM opportunities WHERE id = ANY($1::int[])", ids)


def _uid() -> str:
    return uuid.uuid4().hex[:10]


async def test_auto_prepare_skips_ineligible_opportunities():
    from backend.services import career_auto_prepare as cap

    reqs = SimpleNamespace(
        required_skills=["Python"], eligible_academic_years=[], eligible_graduation_years=[2020],
        eligible_degree_types=[], eligible_countries=[],
    )
    opp = SimpleNamespace(id=1, company_name="X", requirements=reqs)
    profile = UserOpportunityProfileIn(auto_prepare_strongest_matches=True, grad_year=2027, degree="B.Tech")
    master = SimpleNamespace(content=SimpleNamespace(
        full_name="A B", email="a@b.co", education=[1], skills=["Python"], projects=[],
    ))
    with patch("backend.memory.radar.get_user_opportunity_profile", AsyncMock(return_value=profile)), \
         patch("backend.memory.radar.get_user_saved_opportunities", AsyncMock(return_value=[opp])), \
         patch("backend.memory.career.get_master_resume", AsyncMock(return_value=master)), \
         patch.object(cap, "evaluate_eligibility", return_value=("INELIGIBLE", "x", [])):
        result = await cap.execute_auto_prepare_for_user("u1")
    assert result["status"] == "no_eligible_opportunities"


async def test_opportunity_detail_loads_requirement_flags():
    key = _uid()
    opp_id = await _insert_opportunity(key, 0)
    try:
        await _check_detail_flags(opp_id)
    finally:
        await _cleanup(key)


async def _check_detail_flags(opp_id: int) -> None:
    await radar_mem.upsert_opportunity_requirements(opp_id, {
        "preferred_skills": ["Go"], "gpa_scale": 4.0, "no_active_backlogs": True,
        "has_conflicting_requirements": True, "min_gpa": 3.0,
    })
    opp = await radar_mem.get_opportunity_by_id(opp_id)
    assert opp.requirements.gpa_scale == 4.0
    assert opp.requirements.no_active_backlogs is True
    assert opp.requirements.has_conflicting_requirements is True
    assert opp.requirements.preferred_skills == ["Go"]


async def test_saved_and_applied_not_truncated_at_100():
    user = f"u{_uid()}"
    key = _uid()
    ids = []
    try:
        for i in range(105):
            ids.append(await _insert_opportunity(key, i))
        for oid in ids:
            await radar_mem.upsert_user_saved_opportunity(user, oid)
            await radar_mem.upsert_user_application_status(user, oid, "applied")
        saved = await radar_mem.get_user_saved_opportunities(user)
        applied = await radar_mem.get_user_application_tracking(user)
    finally:
        await _cleanup(key)
    assert {o.id for o in saved} == set(ids)
    assert {o.id for o in applied} == set(ids)


async def test_verify_unchanged_status_still_persists_last_verified_at(client):
    now = datetime.now(timezone.utc)
    opp = SimpleNamespace(
        id=7, current_status=OpportunityStatus.NEEDS_VERIFICATION,
        official_application_url="https://boards.greenhouse.io/acme/jobs/1",
        canonical_url="https://boards.greenhouse.io/acme/jobs/1", last_verified_at=None,
    )
    update = AsyncMock()
    history = AsyncMock()
    with patch("backend.routers.radar.get_opportunity_by_id", AsyncMock(return_value=opp)), \
         patch("backend.routers.radar.verify_opportunity_status",
               AsyncMock(return_value=(OpportunityStatus.NEEDS_VERIFICATION, "same", now))), \
         patch("backend.routers.radar.update_opportunity_status", update), \
         patch("backend.routers.radar.add_status_history", history):
        res = await client.post(
            "/api/opportunities/7/verify",
            headers={"Authorization": f"Bearer {create_session('radar@example.com')}"},
        )
    assert res.status_code == 200
    update.assert_awaited_once()
    history.assert_not_awaited()


def test_cpp_keyword_detected_when_followed_by_space():
    opp = SimpleNamespace(
        id=1, company_name="Co", location=None, role_title="Engineer", category="x", description="We use C++ daily.", requirements=None,
    )
    master = SimpleNamespace(
        full_name="A", skills=["C++"], projects=[], education=[], experience=[], summary="",
    )
    report = analyze_job_and_match(opp, master)
    assert "C++" in report.required_skills
