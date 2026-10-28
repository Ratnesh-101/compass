"""
Compass — Internship Radar Test Suite.

Unit and integration tests for:
1. Deterministic eligibility engine (academic year, graduation batch, country, work auth).
2. Historical recruitment cycle prediction engine (confidence scoring, windows).
3. URL canonicalization and source parsing.
4. Verification state machine and prompt injection fencing.
5. FastAPI radar endpoints (listing, recommended, open, watchlist, tracking, profile, sync).
6. AI Assistant grounded skill execution.
"""
from datetime import date, datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.models_radar import (
    ConfidenceLevel,
    EligibilityClassification,
    OpportunityCycleOut,
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunityStatus,
    UserOpportunityProfileIn,
)
from backend.services.radar_eligibility import evaluate_eligibility
from backend.services.radar_prediction import estimate_recruitment_cycle
from backend.services.radar_sources import (
    canonicalize_url,
    normalize_company_name,
    parse_markdown_table_opportunities,
)
from backend.services.radar_verifier import verify_opportunity_status
from backend.skills.handlers.radar import handle_query_internship_radar


# ===========================================================================
# 1. Eligibility Evaluation Tests
# ===========================================================================

def test_eligibility_strong_match():
    opp = OpportunityOut(
        id=1,
        company_name="Google India",
        normalized_company="Google",
        role_title="STEP Intern 2026",
        opportunity_type="internship",
        category="swe",
        canonical_url="https://careers.google.com/jobs/results/step",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="India",
        is_india_eligible=True,
        requirements=OpportunityRequirementsOut(
            eligible_degree_types=["B.Tech", "BS"],
            eligible_academic_years=[2],
            eligible_graduation_years=[2027, 2028],
            eligible_countries=["India"],
            work_auth_required=False,
        ),
    )
    profile = UserOpportunityProfileIn(
        degree="B.Tech Computer Science",
        academic_year=2,
        grad_year=2027,
        country_of_study="India",
    )
    classification, explanation, reasons = evaluate_eligibility(opp, profile)
    assert classification == EligibilityClassification.ELIGIBLE
    assert "Confirmed eligible" in explanation
    assert any(r["field"] == "academic_year" and r["status"] == "pass" for r in reasons)
    assert any(r["field"] == "grad_year" and r["status"] == "pass" for r in reasons)


def test_eligibility_ineligible_academic_year():
    opp = OpportunityOut(
        id=2,
        company_name="Google India",
        normalized_company="Google",
        role_title="STEP Intern",
        opportunity_type="internship",
        category="swe",
        canonical_url="https://careers.google.com/step",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        requirements=OpportunityRequirementsOut(
            eligible_academic_years=[1, 2],
        ),
    )
    # Student in 4th year
    profile = UserOpportunityProfileIn(
        academic_year=4,
        grad_year=2026,
    )
    classification, explanation, reasons = evaluate_eligibility(opp, profile)
    assert classification == EligibilityClassification.INELIGIBLE
    assert "Ineligible" in explanation
    assert any(r["field"] == "academic_year" and r["status"] == "fail" for r in reasons)


def test_eligibility_insufficient_information_when_profile_empty():
    opp = OpportunityOut(
        id=3,
        company_name="Amazon India",
        normalized_company="Amazon",
        role_title="SDE Intern",
        opportunity_type="internship",
        category="swe",
        canonical_url="https://amazon.jobs/sde",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        requirements=OpportunityRequirementsOut(
            eligible_academic_years=[3],
            eligible_graduation_years=[2027],
        ),
    )
    # Empty profile
    classification, explanation, reasons = evaluate_eligibility(opp, None)
    assert classification == EligibilityClassification.INSUFFICIENT_INFORMATION
    assert "Complete your profile" in explanation


def test_eligibility_potential_match_when_unknown_requirements():
    opp = OpportunityOut(
        id=4,
        company_name="NVIDIA",
        normalized_company="NVIDIA",
        role_title="Deep Learning Intern",
        opportunity_type="internship",
        category="ai_ml",
        canonical_url="https://nvidia.com/jobs/dl",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        country="US",
        is_india_eligible=False,
        requirements=OpportunityRequirementsOut(
            eligible_academic_years=[3],
            work_auth_required=True,
            sponsorship_available=None,  # Unconfirmed sponsorship
        ),
    )
    profile = UserOpportunityProfileIn(
        academic_year=3,
        grad_year=2027,
        country_of_study="India",
    )
    classification, explanation, reasons = evaluate_eligibility(opp, profile)
    assert classification in (EligibilityClassification.POTENTIAL_MATCH, EligibilityClassification.INELIGIBLE)


# ===========================================================================
# 2. Recruitment Cycle Prediction Tests
# ===========================================================================

def test_prediction_high_confidence_consistent_cycles():
    cycles = [
        OpportunityCycleOut(cycle_year=2023, observed_open_date=date(2023, 8, 15)),
        OpportunityCycleOut(cycle_year=2024, observed_open_date=date(2024, 8, 18)),
        OpportunityCycleOut(cycle_year=2025, observed_open_date=date(2025, 8, 20)),
    ]
    pred = estimate_recruitment_cycle(cycles)
    assert pred.confidence == ConfidenceLevel.HIGH
    assert pred.verified_cycles_count == 3
    assert "August" in (pred.estimated_open_window or "")
    assert pred.last_observed_cycle == 2025


def test_prediction_medium_confidence():
    cycles = [
        OpportunityCycleOut(cycle_year=2024, observed_open_date=date(2024, 1, 10)),
        OpportunityCycleOut(cycle_year=2025, observed_open_date=date(2025, 2, 5)),
    ]
    pred = estimate_recruitment_cycle(cycles)
    assert pred.confidence == ConfidenceLevel.MEDIUM
    assert pred.verified_cycles_count == 2


def test_prediction_unknown_when_no_cycles():
    pred = estimate_recruitment_cycle([])
    assert pred.confidence == ConfidenceLevel.UNKNOWN
    assert pred.estimated_open_window is None
    assert "No reliable opening-window estimate" in pred.evidence_basis


# ===========================================================================
# 3. Source Adapters & Canonicalization Tests
# ===========================================================================

def test_canonicalize_url():
    raw = "https://careers.google.com/jobs/results/123/?utm_source=linkedin&utm_medium=job_post&ref=social#"
    expected = "https://careers.google.com/jobs/results/123"
    assert canonicalize_url(raw) == expected


def test_normalize_company_name():
    assert normalize_company_name("Google LLC") == "Google"
    assert normalize_company_name("Microsoft Corporation") == "Microsoft"
    assert normalize_company_name("Razorpay Software Pvt Ltd") == "Razorpay Software"


def test_parse_markdown_table():
    md = """
| Company | Role | Location | Application Link |
| :--- | :--- | :--- | :--- |
| [Google](https://google.com) | STEP Intern | Bengaluru, India | [Apply](https://careers.google.com/step?utm_source=gh) |
| [Uber](https://uber.com) | SWE Intern | Hyderabad, India | [Apply](https://uber.com/jobs/swe) |
    """
    results = parse_markdown_table_opportunities(md, "test_repo", "https://github.com/test/repo")
    assert len(results) == 2
    assert results[0]["company_name"] == "Google"
    assert results[0]["role_title"] == "STEP Intern"
    assert results[0]["canonical_url"] == "https://careers.google.com/step"
    assert results[0]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION


# ===========================================================================
# 4. Status Verification Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_verifier_detects_closed_notice(monkeypatch):
    from backend.services import radar_verifier

    async def fake(url, *args, **kwargs):
        return (200, "Thank you for your interest. Applications have closed for the Summer 2026 session.", {}, url)

    monkeypatch.setattr(radar_verifier, "safe_http_get_with_url", fake)
    monkeypatch.setattr(radar_verifier, "tavily_available", lambda: False)

    status, evidence, _ = await verify_opportunity_status("https://example.com/jobs/closed-job")
    assert status == OpportunityStatus.CLOSED_CONFIRMED
    assert "Verified closed" in evidence


# ===========================================================================
# 5. FastAPI Endpoints Integration Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_radar_api_unauthenticated_rejected():
    """Unauthenticated access to user radar endpoints must return 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauth_client:
        res = await unauth_client.get("/api/opportunities")
        assert res.status_code == 401
        assert "authentication" in res.json()["detail"].lower()


@pytest.mark.timeout(180)
@pytest.mark.asyncio
async def test_radar_api_endpoints(monkeypatch):
    async def mock_gh(*args, **kwargs):
        return []

    async def mock_ats(*args, **kwargs):
        return []

    async def mock_jobspy(*args, **kwargs):
        return {
            "status": "success",
            "sources_attempted": 0,
            "sources_succeeded": 0,
            "sources_failed": 0,
            "raw_results": 0,
            "internship_matches": 0,
            "normalized_results": 0,
            "verified_within_24h": 0,
            "approximate_recency": 0,
            "unknown_posting_time": 0,
            "duplicates_removed": 0,
            "opportunities": [],
            "errors": [],
        }

    monkeypatch.setattr("backend.services.radar_sync.fetch_github_markdown_opportunities", mock_gh)
    monkeypatch.setattr("backend.services.radar_sync.fetch_all_public_ats_opportunities", mock_ats)
    monkeypatch.setattr("backend.services.radar_sync.tavily_available", lambda: False)
    monkeypatch.setattr("backend.services.radar_sync.discover_jobspy_opportunities", mock_jobspy)
    monkeypatch.setattr("backend.services.radar_jobspy.discover_jobspy_opportunities", mock_jobspy)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"x-user-id": "candidate_radar_user"}) as client:
        # 1. Trigger sync (seeds curated opportunities quickly, requires admin)
        sync_res = await client.post(
            "/api/opportunities/sync?source=curated",
            headers={"x-user-id": "admin"},
        )
        assert sync_res.status_code == 200
        assert sync_res.json()["status"] in ("completed", "completed_with_errors")

        # 2. List opportunities
        list_res = await client.get("/api/opportunities")
        assert list_res.status_code == 200
        data = list_res.json()
        assert "opportunities" in data
        assert data["total"] >= 1

        # 3. Analytics
        stats_res = await client.get("/api/opportunities/analytics")
        assert stats_res.status_code == 200
        assert "total_tracked_opportunities" in stats_res.json()

        # 4. Profile PUT & GET
        prof_res = await client.put(
            "/api/opportunities/profile",
            json={
                "degree": "B.Tech",
                "academic_year": 3,
                "grad_year": 2027,
                "country_of_study": "India",
                "skills": ["Python", "PyTorch"],
            },
        )
        assert prof_res.status_code == 200
        assert prof_res.json()["academic_year"] == 3

        # 5. Save opportunity
        first_id = data["opportunities"][0]["id"]
        save_res = await client.post(f"/api/opportunities/{first_id}/save")
        assert save_res.status_code == 200
        assert save_res.json()["saved"] is True

        # 6. Verify watchlist contains it
        wl_res = await client.get("/api/opportunities/watchlist")
        assert wl_res.status_code == 200
        wl_ids = [o["id"] for o in wl_res.json()]
        assert first_id in wl_ids

        # 7. Update application state
        app_res = await client.post(
            f"/api/opportunities/{first_id}/application",
            json={"application_status": "interviewing", "private_notes": "Round 1 cleared"},
        )
        assert app_res.status_code == 200
        assert app_res.json()["application_status"] == "interviewing"

        # 8. Unsave opportunity
        unsave_res = await client.delete(f"/api/opportunities/{first_id}/save")
        assert unsave_res.status_code == 200
        assert unsave_res.json()["saved"] is False
    import asyncio
    await asyncio.sleep(0.05)


# ===========================================================================
# 6. AI Assistant Grounded Skill Execution
# ===========================================================================

@pytest.mark.asyncio
async def test_ai_radar_skill_execution():
    res = await handle_query_internship_radar({"query": "Google", "india_only": True})
    assert res["success"] is True
    assert "Compass Internship Radar" in res["summary"]


# ===========================================================================
# 7. Strict Recency, Cross-Site Dedup, Degree Filtering, & Degraded Status
# ===========================================================================

def test_injected_clock_read_time_recency():
    """
    Section 4 Requirement:
    Test with an injected clock:
    - A row verified at ingest (exact timestamp 2h ago) is NOT verified 25h later.
    - A date_only row is NEVER verified.
    - Future timestamps are NEVER verified.
    """
    from datetime import timedelta
    from backend.routers.radar import compute_is_verified_within_24h

    ingest_time = datetime(2026, 10, 21, 10, 0, 0, tzinfo=timezone.utc)
    posted_at = datetime(2026, 10, 21, 8, 0, 0, tzinfo=timezone.utc)  # 2 hours before ingest

    # At ingest (2h old, exact precision) -> VERIFIED
    assert compute_is_verified_within_24h(posted_at, "exact", now_utc=ingest_time) is True

    # 21 hours later (23h old, exact precision) -> Still VERIFIED
    clock_21h_later = ingest_time + timedelta(hours=21)
    assert compute_is_verified_within_24h(posted_at, "exact", now_utc=clock_21h_later) is True

    # 25 hours later (27h old, exact precision) -> NOT VERIFIED
    clock_25h_later = ingest_time + timedelta(hours=25)
    assert compute_is_verified_within_24h(posted_at, "exact", now_utc=clock_25h_later) is False

    # date_only precision -> NEVER verified within 24h
    recent_date_only = datetime(2026, 10, 21, 0, 0, 0, tzinfo=timezone.utc)
    assert compute_is_verified_within_24h(recent_date_only, "date_only", now_utc=ingest_time) is False

    # unknown precision -> NEVER verified within 24h
    assert compute_is_verified_within_24h(recent_date_only, "unknown", now_utc=ingest_time) is False

    # Future timestamp -> NEVER verified
    future_time = ingest_time + timedelta(hours=2)
    assert compute_is_verified_within_24h(future_time, "exact", now_utc=ingest_time) is False


@pytest.mark.asyncio
async def test_cross_site_dedup_and_location_isolation():
    """
    Section 5 Requirement:
    - Same job on two sites (Indeed & LinkedIn) with different URLs merges (1 opportunity, 2 source rows).
    - Same company/title in different locations does NOT merge.
    """
    import uuid
    from backend.memory.radar import upsert_opportunity, add_opportunity_source, get_opportunity_by_id

    test_company = f"DedupCorp_{uuid.uuid4().hex[:6]}"

    # Site A: Indeed in Bengaluru
    opp_id_indeed = await upsert_opportunity(
        company_name=f"{test_company}, Inc.",
        role_title="Software Engineering Intern",
        location="Bengaluru, Karnataka, India",
        canonical_url=f"https://indeed.com/viewjob?jk={test_company}_blr_1",
        official_application_url=f"https://indeed.com/viewjob?jk={test_company}_blr_1",
    )
    await add_opportunity_source(
        opportunity_id=opp_id_indeed,
        source_name="JobSpy Indeed",
        source_type="jobspy_indeed",
        source_url=f"https://indeed.com/viewjob?jk={test_company}_blr_1",
    )

    # Site B: LinkedIn with direct career page URL in Bengaluru
    opp_id_linkedin = await upsert_opportunity(
        company_name=test_company,
        role_title="Software Engineering Intern",
        location="Bengaluru, Karnataka, India",
        canonical_url=f"https://linkedin.com/jobs/view/{test_company}_blr_2",
        official_application_url="https://careers.google.com/jobs/results/12345",
    )
    await add_opportunity_source(
        opportunity_id=opp_id_linkedin,
        source_name="JobSpy LinkedIn",
        source_type="jobspy_linkedin",
        source_url=f"https://linkedin.com/jobs/view/{test_company}_blr_2",
    )

    # Must MERGE into 1 opportunity with 2 sources and prefer direct application URL
    assert opp_id_indeed == opp_id_linkedin
    merged_opp = await get_opportunity_by_id(opp_id_indeed)
    assert merged_opp is not None
    assert len(merged_opp.sources) == 2
    assert {s.source_type for s in merged_opp.sources} == {"jobspy_indeed", "jobspy_linkedin"}
    assert merged_opp.official_application_url == "https://careers.google.com/jobs/results/12345"

    # Site C: Same company and role, but in different location (Hyderabad)
    opp_id_hyd = await upsert_opportunity(
        company_name=test_company,
        role_title="Software Engineering Intern",
        location="Hyderabad, Telangana, India",
        canonical_url=f"https://indeed.com/viewjob?jk={test_company}_hyd_3",
        official_application_url=f"https://indeed.com/viewjob?jk={test_company}_hyd_3",
    )
    # Must NOT merge (remains isolated by location)
    assert opp_id_hyd != opp_id_indeed


def test_eligibility_nubank_phd_excluded_for_btech():
    """
    Section 6 Requirement:
    Nubank PhD role must be flagged/excluded (INELIGIBLE) for a B.Tech student with degree reason.
    """
    from backend.models_radar import (
        OpportunityOut,
        OpportunityRequirementsOut,
        OpportunityStatus,
        UserOpportunityProfileIn,
        EligibilityClassification,
    )
    from backend.services.radar_eligibility import evaluate_eligibility

    btech_profile = UserOpportunityProfileIn(
        academic_year=3,
        grad_year=2026,
        degree="B.Tech in Computer Science",
        country_of_study="India",
        skills=["Python", "Machine Learning"],
    )

    nubank_phd_opp = OpportunityOut(
        id=999,
        company_name="Nubank",
        normalized_company="nubank",
        role_title="Machine Learning Scientist Intern (PhD)",
        opportunity_type="internship",
        category="ai_ml",
        location="Bengaluru, Karnataka, India",
        country="India",
        is_india_eligible=True,
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        canonical_url="https://nubank.com/jobs/phd_intern",
        requirements=OpportunityRequirementsOut(
            eligible_degree_types=["PhD", "Doctoral"],
            eligible_academic_years=[4, 5],
            eligible_graduation_years=[2026, 2027],
            eligible_countries=["India"],
            work_auth_required=False,
            required_skills=["Python", "Deep Learning"],
        ),
    )

    classification, explanation, reasons = evaluate_eligibility(nubank_phd_opp, btech_profile)
    assert classification == EligibilityClassification.INELIGIBLE
    failed_reasons = [r for r in reasons if r["status"] == "fail"]
    assert any(r["field"] == "degree" for r in failed_reasons)
    assert "degree" in explanation.lower() or "academic" in explanation.lower()


@pytest.mark.asyncio
async def test_jobspy_all_empty_or_failed_returns_degraded():
    """
    Section 7 Requirement:
    If all JobSpy sites return 0 or fail, the run status must be 'degraded' and logged,
    not silent success.
    """
    from unittest.mock import patch
    import pandas as pd
    from backend.services.radar_jobspy import discover_jobspy_opportunities

    empty_df = pd.DataFrame()

    with patch("jobspy.scrape_jobs", return_value=empty_df):
        summary = await discover_jobspy_opportunities(
            sites=["indeed", "linkedin"],
            search_terms=["intern"],
            location="India",
        )
        assert summary["status"] == "degraded"
        assert summary["raw_results"] == 0
        assert summary["empty_sources"] == 2


@pytest.mark.asyncio
async def test_radar_sync_restricted_to_admin(monkeypatch):
    """POST /api/opportunities/sync must reject unauthenticated, guest, and normal users with 403.
    Only admin / nightly automated tasks with admin credentials can trigger it.
    """
    from backend.main import app
    from httpx import AsyncClient, ASGITransport
    from backend.services.radar_sync import run_radar_sync

    async def mock_sync(*args, **kwargs):
        return {"status": "completed", "sources_synced": []}

    monkeypatch.setattr("backend.routers.radar.run_radar_sync", mock_sync)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated -> 403 Forbidden
        res_unauth = await client.post("/api/opportunities/sync")
        assert res_unauth.status_code == 403
        assert "Forbidden" in res_unauth.json()["detail"] or "Admin" in res_unauth.json()["detail"]

        # 2. Guest user -> 403 Forbidden
        res_guest = await client.post("/api/opportunities/sync", headers={"x-guest-id": "guest_12345"})
        assert res_guest.status_code == 403

        # 3. Normal non-admin user -> 403 Forbidden
        res_user = await client.post("/api/opportunities/sync", headers={"x-user-id": "student_user"})
        assert res_user.status_code == 403

        # 4. Admin user -> 200 OK
        res_admin = await client.post("/api/opportunities/sync", headers={"x-user-id": "admin"})
        assert res_admin.status_code == 200
        assert res_admin.json()["status"] == "completed"


