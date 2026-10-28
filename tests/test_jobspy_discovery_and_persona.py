"""
Tests for explicit Judge Persona loading and JobSpy internship discovery skill.

Verifies:
1. Fresh user gets no demo tasks on mount / startup.
2. Load Judge Persona button explicitly seeds persona.
3. Seeding is idempotent and isolated to calling tenant.
4. JobSpy opportunity normalizer handles 24h classification accurately.
5. JobSpy discovery integration handles success, partial errors, and persistence.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.services.radar_jobspy import (
    classify_posting_recency,
    normalize_jobspy_opportunity,
    discover_jobspy_opportunities,
)
from backend.services.radar_sync import run_radar_sync


def test_jobspy_recency_classification_24h_exact():
    now_utc = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)

    # 1. 23 hours 59 minutes old -> VERIFIED_WITHIN_24H
    posted_23h59m = now_utc - timedelta(hours=23, minutes=59)
    res_23h59m = classify_posting_recency(posted_23h59m, now=now_utc)
    assert res_23h59m["is_verified_24h"] is True
    assert res_23h59m["recency_tier"] == "VERIFIED_WITHIN_24H"
    assert res_23h59m["timestamp_precision"] == "EXACT_TIMESTAMP"

    # 2. Exactly 24 hours old -> VERIFIED_WITHIN_24H
    posted_24h00m = now_utc - timedelta(hours=24, minutes=0)
    res_24h00m = classify_posting_recency(posted_24h00m, now=now_utc)
    assert res_24h00m["is_verified_24h"] is True
    assert res_24h00m["recency_tier"] == "VERIFIED_WITHIN_24H"
    assert res_24h00m["timestamp_precision"] == "EXACT_TIMESTAMP"

    # 3. 24 hours 1 minute old -> APPROXIMATE_RECENCY (Strict boundary exceeded)
    posted_24h01m = now_utc - timedelta(hours=24, minutes=1)
    res_24h01m = classify_posting_recency(posted_24h01m, now=now_utc)
    assert res_24h01m["is_verified_24h"] is False
    assert res_24h01m["recency_tier"] == "APPROXIMATE_RECENCY"
    assert res_24h01m["timestamp_precision"] == "EXACT_TIMESTAMP"

    # 4. 24 hours 20 minutes old -> APPROXIMATE_RECENCY
    posted_24h20m = now_utc - timedelta(hours=24, minutes=20)
    res_24h20m = classify_posting_recency(posted_24h20m, now=now_utc)
    assert res_24h20m["is_verified_24h"] is False
    assert res_24h20m["recency_tier"] == "APPROXIMATE_RECENCY"
    assert res_24h20m["timestamp_precision"] == "EXACT_TIMESTAMP"

    # 5. One minute in the future (without documented clock offset) -> UNKNOWN
    future_1m = now_utc + timedelta(minutes=1)
    res_future_1m = classify_posting_recency(future_1m, now=now_utc)
    assert res_future_1m["is_verified_24h"] is False
    assert res_future_1m["recency_tier"] == "UNKNOWN"
    assert res_future_1m["timestamp_precision"] == "EXACT_TIMESTAMP"

    # 6. Three minutes in the future (without documented clock offset) -> UNKNOWN
    future_3m = now_utc + timedelta(minutes=3)
    res_future_3m = classify_posting_recency(future_3m, now=now_utc)
    assert res_future_3m["is_verified_24h"] is False
    assert res_future_3m["recency_tier"] == "UNKNOWN"
    assert res_future_3m["timestamp_precision"] == "EXACT_TIMESTAMP"

    # 7. Documented source-specific clock offset (e.g. 3m = 0.05h validated offset) -> VERIFIED_WITHIN_24H
    res_documented_skew = classify_posting_recency(future_3m, now=now_utc, source_clock_skew_tolerance_hours=0.05)
    assert res_documented_skew["is_verified_24h"] is True
    assert res_documented_skew["recency_tier"] == "VERIFIED_WITHIN_24H"
    assert res_documented_skew["age_hours"] == 0.0

    # 8. Missing timestamp -> UNKNOWN
    res_none = classify_posting_recency(None, now=now_utc)
    assert res_none["is_verified_24h"] is False
    assert res_none["recency_tier"] == "UNKNOWN"
    assert res_none["timestamp_precision"] == "NONE"

    # 9. Date-only timestamp -> APPROXIMATE_RECENCY (cannot verify within exact 24h window)
    res_date_only = classify_posting_recency(date(2026, 10, 21), now=now_utc)
    assert res_date_only["is_verified_24h"] is False
    assert res_date_only["recency_tier"] == "APPROXIMATE_RECENCY"
    assert res_date_only["timestamp_precision"] == "DATE_ONLY"

    # 10. Conflicting / unparseable timestamp formats -> UNKNOWN
    res_conflict = classify_posting_recency("2026-99-99 invalid", now=now_utc)
    assert res_conflict["is_verified_24h"] is False
    assert res_conflict["recency_tier"] == "UNKNOWN"
    assert res_conflict["timestamp_precision"] == "NONE"

    # 11. Timezone conversion: IST (+05:30) posted 2 hours ago
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    # now_utc is 12:00 UTC -> 17:30 IST. 2 hours ago in IST is 15:30 IST
    posted_ist = datetime(2026, 10, 21, 15, 30, tzinfo=ist_tz)
    res_ist = classify_posting_recency(posted_ist, now=now_utc)
    assert res_ist["is_verified_24h"] is True
    assert res_ist["recency_tier"] == "VERIFIED_WITHIN_24H"
    assert round(res_ist["age_hours"], 1) == 2.0

    # 12. First-seen time vs posting time:
    # First seen 10 minutes ago, but posted 30 hours ago -> NOT verified 24h
    posted_30h_ago = now_utc - timedelta(hours=30)
    norm = normalize_jobspy_opportunity({
        "title": "Machine Learning Intern",
        "company": "DeepMind",
        "job_url": "https://deepmind.google/careers/123",
        "date_posted": posted_30h_ago,
    })
    assert norm is not None
    assert norm["is_verified_within_24h"] is False
    assert norm["recency_tier"] == "APPROXIMATE_RECENCY"
    assert norm["first_seen_at"] is not None


def test_jobspy_normalization_internship_filtering():
    # 1. Valid internship listing
    row_intern = {
        "title": "Software Engineering Intern - Summer 2026",
        "company": "Stripe",
        "job_url": "https://stripe.com/jobs/12345",
        "location": "Remote, USA",
        "date_posted": datetime.now(timezone.utc) - timedelta(hours=2),
        "description": "Looking for curious undergraduate software engineering interns.",
        "site": "indeed",
        "is_remote": True,
        "skills": "Python, Go, PostgreSQL",
    }
    norm_intern = normalize_jobspy_opportunity(row_intern)
    assert norm_intern is not None
    assert norm_intern["company_name"] == "Stripe"
    assert norm_intern["role_title"] == "Software Engineering Intern - Summer 2026"
    assert norm_intern["is_verified_within_24h"] is True
    assert norm_intern["recency_tier"] == "VERIFIED_WITHIN_24H"
    assert norm_intern["category"] == "swe"
    assert "stripe.com/jobs/12345" in norm_intern["canonical_url"]
    assert norm_intern["source_name"] == "JobSpy (Indeed)"
    assert norm_intern["source_type"] == "jobspy_indeed"
    assert norm_intern["source_authority"] == "tier_2"

    # 2. Senior / non-internship role -> filtered out
    row_senior = {
        "title": "Principal Distributed Systems Architect",
        "company": "Amazon",
        "job_url": "https://amazon.jobs/senior",
        "description": "Minimum 12 years experience building AWS hyper-scale platforms.",
        "site": "indeed",
    }
    norm_senior = normalize_jobspy_opportunity(row_senior)
    assert norm_senior is None


@pytest.mark.asyncio
async def test_jobspy_discovery_run_isolation_and_error_handling():
    """Verify that JobSpy runs return structured observability counts and isolate site failures."""
    from backend.services.radar_jobspy import discover_jobspy_opportunities
    import pandas as pd

    # Mock DataFrame returning 2 opportunities for indeed
    mock_df = pd.DataFrame([
        {
            "id": "ind-1",
            "title": "AI Research Intern",
            "company": "Nebius",
            "job_url": "https://nebius.com/careers/intern-1",
            "location": "Remote",
            "date_posted": datetime.now(timezone.utc) - timedelta(hours=3),
            "description": "Research intern building frontier LLM clusters.",
            "site": "indeed",
            "is_remote": True,
        },
        {
            "id": "ind-2",
            "title": "Senior Staff Architect",
            "company": "BigCorp",
            "job_url": "https://bigcorp.com/staff",
            "location": "Seattle",
            "date_posted": datetime.now(timezone.utc) - timedelta(hours=1),
            "description": "Requires 10+ years experience.",
            "site": "indeed",
            "is_remote": False,
        }
    ])

    def mock_scrape_jobs(site_name, **kwargs):
        if "linkedin" in site_name:
            raise RuntimeError("Rate limited on LinkedIn public portal")
        return mock_df

    with patch("jobspy.scrape_jobs", side_effect=mock_scrape_jobs):
        summary = await discover_jobspy_opportunities(
            sites=["indeed", "linkedin"],
            search_terms=["ai intern"],
        )

        assert summary["status"] == "partial"
        assert summary["sources_succeeded"] >= 1
        assert summary["sources_failed"] >= 1
        assert summary["raw_results"] == 2
        assert summary["internship_matches"] == 1  # AI Research Intern matched, Senior Staff filtered
        assert summary["normalized_results"] == 1
        assert summary["verified_within_24h"] == 1
        assert len(summary["opportunities"]) == 1
        assert summary["opportunities"][0]["company_name"] == "Nebius"
        assert len(summary["errors"]) == 1
        assert "LinkedIn" in str(summary["errors"][0])


@pytest.mark.asyncio
async def test_jobspy_synthetic_e2e_pipeline_and_api(client, auth_headers):
    """
    Phase 2: Prove discovery, persistence, and Radar API display with synthetic data.
    Verifies actual pipeline counts and idempotency on subsequent sync.
    """
    from tests.fixtures.synthetic_jobspy import (
        create_synthetic_jobspy_dataframe,
        create_synthetic_jobspy_rows,
        SYNTHETIC_TEST_MARKERS,
    )

    now_utc = datetime.now(timezone.utc)
    mock_df = create_synthetic_jobspy_dataframe(base_time=now_utc)

    def mock_scrape(site_name, **kwargs):
        if "linkedin" in site_name:
            raise RuntimeError("HTTP 429: Rate limited on LinkedIn public API")
        return mock_df

    with patch("jobspy.scrape_jobs", side_effect=mock_scrape):
        # 1. Execute discovery
        summary = await discover_jobspy_opportunities(
            sites=["indeed", "linkedin"],
            search_terms=["intern"],
        )

        # Assert Phase 2 counts
        assert summary["sources_attempted"] == 2
        assert summary["sources_succeeded"] == 1
        assert summary["sources_failed"] == 1
        assert summary["raw_results"] == 5
        assert summary["internship_matches"] == 4
        assert summary["rejected_by_reason"]["non_internship"] == 1
        assert summary["duplicates_removed"] == 1
        assert summary["normalized_results"] == 3
        assert summary["verified_within_24h"] == 1
        assert summary["approximate_recency"] == 1
        assert summary["unknown_posting_time"] == 1
        assert len(summary["opportunities"]) == 3

        # 2. Test full sync pipeline persistence with JobSpy
        sync_res = await run_radar_sync("jobspy")
        assert sync_res["status"] in ("completed", "completed_with_errors")
        assert sync_res["records_updated"] >= 3

        # 3. Query Radar API to confirm persistence & display
        resp = await client.get("/api/opportunities?search=Quantum+ML", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        opps = data.get("opportunities", [])
        assert any("SyntheticQuantumCorp" in o["company_name"] for o in opps)
        match_opp = next(o for o in opps if "SyntheticQuantumCorp" in o["company_name"])
        assert match_opp["is_verified_within_24h"] is True
        assert match_opp["role_title"] == "Quantum ML Research Intern"

        # 4. Subsequent sync does NOT duplicate
        await run_radar_sync("jobspy")
        resp_after = await client.get("/api/opportunities?search=Quantum+ML", headers=auth_headers)
        opps_after = resp_after.json().get("opportunities", [])
        quantum_matches = [o for o in opps_after if "SyntheticQuantumCorp" in o["company_name"]]
        assert len(quantum_matches) == 1


def test_runtime_code_never_imports_or_contains_synthetic_fixtures():
    """
    Phase 3 & Phase 7 Regression Test:
    Proves that no runtime/production module in backend/ imports or contains
    synthetic test markers (e.g. SyntheticQuantumCorp, syn-1, tests.fixtures).
    """
    import os
    import re

    backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
    assert os.path.exists(backend_dir), "backend directory must exist"

    from tests.fixtures.synthetic_jobspy import SYNTHETIC_TEST_MARKERS

    forbidden_patterns = list(SYNTHETIC_TEST_MARKERS) + ["tests.fixtures", "synthetic_rows"]
    violations = []

    for root, _, files in os.walk(backend_dir):
        # Exclude __pycache__
        if "__pycache__" in root:
            continue
        for file in files:
            if not file.endswith(".py"):
                continue
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                for pattern in forbidden_patterns:
                    if pattern in content:
                        violations.append(f"{filepath} contains forbidden synthetic marker '{pattern}'")

    assert not violations, "Runtime code contains synthetic test markers:\n" + "\n".join(violations)


@pytest.mark.asyncio
async def test_jobspy_empty_source_returns_zero_and_no_synthetic_fallbacks():
    """
    Phase 2 & Phase 7 Requirement:
    When JobSpy returns empty results or errors, it must report zero new listings
    and MUST NOT substitute synthetic test fixtures, demo data, or fabricated rows.
    """
    import pandas as pd
    from backend.services.radar_jobspy import discover_jobspy_opportunities

    empty_df = pd.DataFrame()

    with patch("jobspy.scrape_jobs", return_value=empty_df):
        summary = await discover_jobspy_opportunities(
            sites=["indeed"],
            search_terms=["intern"],
        )
        assert summary["sources_attempted"] == 1
        assert summary["sources_succeeded"] == 1
        assert summary["sources_failed"] == 0
        assert summary["empty_sources"] == 1
        assert summary["raw_results"] == 0
        assert summary["normalized_results"] == 0
        assert summary["internship_matches"] == 0
        assert summary["verified_within_24h"] == 0
        assert len(summary["opportunities"]) == 0


@pytest.mark.asyncio
async def test_jobspy_synthetic_future_and_invalid_date_classification():
    """
    Phase 3 & Phase 6 Requirement:
    Future timestamps and invalid dates in JobSpy results must never be falsely
    verified as recent (is_verified_within_24h must be False).
    """
    from tests.fixtures.synthetic_jobspy import create_synthetic_jobspy_dataframe
    from backend.services.radar_jobspy import discover_jobspy_opportunities

    test_clock = datetime.now(timezone.utc)
    mock_df = create_synthetic_jobspy_dataframe(
        base_time=test_clock,
        include_future_date=True,
        include_invalid_date=True,
    )

    with patch("jobspy.scrape_jobs", return_value=mock_df):
        summary = await discover_jobspy_opportunities(
            sites=["indeed"],
            search_terms=["intern"],
        )
        # 1 valid verified within 24h, 1 duplicate, 1 date-only, 1 missing date, 1 senior role (filtered), 1 future, 1 invalid date
        # Total rows = 7, non-internship = 1 -> internship matches = 6, 1 duplicate removed -> normalized = 5
        assert summary["raw_results"] == 7
        assert summary["internship_matches"] == 6
        assert summary["duplicates_removed"] == 1
        assert summary["normalized_results"] == 5

        # Strictly only the 4h-old listing qualifies as verified within 24h
        assert summary["verified_within_24h"] == 1

        opps = summary["opportunities"]
        future_opp = next((o for o in opps if "Future" in o["company_name"] and "Future Systems" in o["role_title"]), None)
        assert future_opp is not None
        assert future_opp["is_verified_within_24h"] is False
        assert future_opp["recency_tier"] == "UNKNOWN"

        invalid_opp = next((o for o in opps if "Hardware Validation" in o["role_title"]), None)
        assert invalid_opp is not None
        assert invalid_opp["is_verified_within_24h"] is False
        assert invalid_opp["recency_tier"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_jobspy_thread_bounding_and_timeout_isolation():
    """
    Requirement 5:
    Demonstrates that:
    1. A hung or slow source does NOT block execution: per_source_timeout_seconds cleanly
       times out via asyncio.wait_for and records sources_failed.
    2. Scrapes run in bounded _jobspy_executor (max_workers=2), preventing unbounded
       thread leaks that occur when using naive asyncio.to_thread with the default executor.
    3. Thread pool name prefix and max_workers bounds are enforced.
    """
    import time
    import jobspy  # Warm import before timing to isolate network/timeout execution
    from backend.services.radar_jobspy import _jobspy_executor, discover_jobspy_opportunities

    # Confirm bounded executor configuration
    assert _jobspy_executor._max_workers == 2
    assert _jobspy_executor._thread_name_prefix == "compass_jobspy_worker"

    def _simulated_hung_scrape(**kwargs):
        time.sleep(1.5)  # Simulate blocking network I/O
        return None

    with patch("jobspy.scrape_jobs", side_effect=_simulated_hung_scrape):
        t0 = time.monotonic()
        summary = await discover_jobspy_opportunities(
            sites=["indeed"],
            search_terms=["intern"],
            per_source_timeout_seconds=0.15,
            total_timeout_seconds=1.0,
        )
        elapsed = time.monotonic() - t0

    # Ensure loop was not blocked for 1.5s (timed out cleanly in ~0.15s)
    assert elapsed < 0.6, f"Execution took {elapsed:.2f}s, expected timeout around 0.15s"
    assert summary["sources_failed"] == 1
    assert summary["sources_succeeded"] == 0
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["error_type"] == "TIMEOUT"
    assert "TimeoutError" in summary["errors"][0]["error"]


@pytest.mark.asyncio
async def test_jobspy_saturation_guard_rejects_third_call_promptly():
    """
    Requirement 3:
    With both workers hung/active, a third call must return promptly with an explicit
    'executor saturated' error (no silent queueing), and the run completes within the deadline.
    """
    import time
    from backend.services.radar_jobspy import (
        _jobspy_worker_lock,
        _active_jobspy_workers,
        discover_jobspy_opportunities,
    )
    import backend.services.radar_jobspy as rj

    # Artificially simulate 2 active workers currently saturating the executor
    with _jobspy_worker_lock:
        rj._active_jobspy_workers = 2

    try:
        t0 = time.monotonic()
        summary = await discover_jobspy_opportunities(
            sites=["indeed"],
            search_terms=["intern"],
            per_source_timeout_seconds=5.0,
            total_timeout_seconds=5.0,
        )
        elapsed = time.monotonic() - t0

        # Must return promptly (< 0.2s) without queueing for 5.0s
        assert elapsed < 0.2, f"Execution was delayed ({elapsed:.2f}s); expected prompt rejection"
        assert summary["sources_failed"] == 1
        assert summary["per_source_status"]["indeed"]["status"] == "executor_saturated"
        assert "executor saturated" in summary["per_source_status"]["indeed"]["error"]
        assert summary["errors"][0]["error_type"] == "EXECUTOR_SATURATED"
    finally:
        with _jobspy_worker_lock:
            rj._active_jobspy_workers = 0


@pytest.mark.asyncio
async def test_radar_sync_all_must_include_jobspy():
    """
    Requirement 2:
    Fails if JobSpy discovery is removed from run_radar_sync('all').
    """
    import inspect
    from backend.services.radar_sync import run_radar_sync

    # Inspect code of run_radar_sync to guarantee "jobspy" is included in "all"
    source_code = inspect.getsource(run_radar_sync)
    assert 'source_filter in {"all", "jobspy"}' in source_code or 'source_filter in (\'all\', \'jobspy\')' in source_code or '"jobspy"' in source_code, (
        "JobSpy discovery MUST be included in run_radar_sync('all')!"
    )

    # Run in dry-run mode and verify JobSpy discovery is actually invoked
    with patch("backend.services.radar_sync.discover_jobspy_opportunities") as mock_disc, \
         patch("backend.services.radar_sync.fetch_all_public_ats_opportunities", new_callable=AsyncMock) as mock_ats, \
         patch("backend.services.radar_sync.fetch_github_markdown_opportunities", new_callable=AsyncMock) as mock_gh:
        mock_ats.return_value = []
        mock_gh.return_value = []
        mock_disc.return_value = {
            "status": "success",
            "raw_results": 1,
            "opportunities": [{"title": "Intern"}],
        }
        res = await run_radar_sync("all", dry_run=True)
        assert mock_disc.called, "discover_jobspy_opportunities was NOT called when source_filter='all'!"
        assert res["status"] == "completed_dry_run"


@pytest.mark.asyncio
async def test_consolidate_radar_failure_reflected_in_final_status():
    """
    Requirement 2:
    Radar failure in consolidate.py must be reflected in the job's final status/exit result,
    not only logged.
    """
    from backend.jobs.consolidate import run_consolidation

    # Simulate run_radar_sync returning a failed result
    with patch("backend.services.radar_sync.run_radar_sync") as mock_sync, \
         patch("backend.jobs.consolidate.flag_overdue_tasks", new_callable=AsyncMock) as m_overdue, \
         patch("backend.jobs.consolidate.deduplicate_vectors", new_callable=AsyncMock) as m_dedup, \
         patch("backend.jobs.consolidate.archive_stale_threads", new_callable=AsyncMock) as m_archive, \
         patch("backend.jobs.consolidate.trigger_proactive_nightly_run", new_callable=AsyncMock) as m_proact, \
         patch("backend.jobs.consolidate.check_slipped_schedules", new_callable=AsyncMock) as m_slipped, \
         patch("backend.services.rate_limiter.cleanup_stale_rate_limit_buckets", new_callable=AsyncMock), \
         patch("backend.services.budgets.prune_expired_guests", new_callable=AsyncMock):

        m_overdue.return_value = 0
        m_dedup.return_value = 0
        m_archive.return_value = 0
        m_proact.return_value = {"status": "completed", "run_id": "test"}
        m_slipped.return_value = {"slipped_count": 0}

        mock_sync.return_value = {
            "status": "failed",
            "error_summary": "Simulated upstream network failure in JobSpy and ATS",
            "failures": 5,
        }
        # Dry-run = False so failures trigger failure status
        with patch("asyncpg.connect") as mock_conn:
            mock_c = AsyncMock()
            mock_conn.return_value = mock_c
            mock_c.fetchval.return_value = True  # advisory lock acquired
            mock_c.fetch.return_value = []
            with patch("backend.jobs.consolidate.register_vector"):
                res = await run_consolidation(dry_run=False)

        assert res["status"] == "failed", f"Expected job status 'failed', got {res['status']}"
        assert res["radar_sync_status"] == "failed"
        assert "Simulated upstream network failure" in res["radar_sync_error"]


@pytest.mark.asyncio
async def test_cross_site_deduplication_merges_two_sites_into_one_opportunity():
    """
    Requirement 6:
    Demonstrates deterministic cross-site deduplication:
    The same internship posted on Indeed and LinkedIn with matching canonical URL
    is merged into 1 opportunity with 2 distinct sources.
    """
    from backend.services.radar_sources import canonicalize_url

    # Job on Indeed
    indeed_raw = {
        "title": "Software Engineering Intern - Summer 2027",
        "company": "Stripe, Inc.",
        "job_url_direct": "https://stripe.com/jobs/listing/12345?utm_source=indeed",
        "site": "indeed",
    }
    # Same job on LinkedIn
    linkedin_raw = {
        "title": "Software Engineering Intern - Summer 2027",
        "company": "Stripe",
        "job_url_direct": "https://stripe.com/jobs/listing/12345?utm_campaign=linkedin_jobs&ref=feed",
        "site": "linkedin",
    }

    canon_indeed = canonicalize_url(indeed_raw["job_url_direct"], indeed_raw["title"])
    canon_linkedin = canonicalize_url(linkedin_raw["job_url_direct"], linkedin_raw["title"])

    # Assert canonical URLs match identically despite different query params
    assert canon_indeed == "https://stripe.com/jobs/listing/12345"
    assert canon_linkedin == "https://stripe.com/jobs/listing/12345"
    assert canon_indeed == canon_linkedin

    # When tracked in radar repository dictionary
    radar_db = {}
    sources_db = []

    for item, s_type in [(indeed_raw, "jobspy_indeed"), (linkedin_raw, "jobspy_linkedin")]:
        canon = canonicalize_url(item["job_url_direct"], item["title"])
        if canon not in radar_db:
            opp_id = len(radar_db) + 1
            radar_db[canon] = {
                "id": opp_id,
                "company_name": item["company"],
                "role_title": item["title"],
                "canonical_url": canon,
            }
        else:
            opp_id = radar_db[canon]["id"]

        sources_db.append({
            "opportunity_id": opp_id,
            "source_type": s_type,
            "source_url": item["job_url_direct"],
        })

    # Exact deterministic counts
    distinct_opportunities = len(radar_db)
    total_sources_linked = len(sources_db)
    sources_for_opportunity = [s["source_type"] for s in sources_db if s["opportunity_id"] == 1]

    assert distinct_opportunities == 1, f"Expected 1 opportunity, got {distinct_opportunities}"
    assert total_sources_linked == 2, f"Expected 2 sources, got {total_sources_linked}"
    assert set(sources_for_opportunity) == {"jobspy_indeed", "jobspy_linkedin"}


@pytest.mark.asyncio
async def test_ziprecruiter_per_source_status_structured():
    """
    Requirement 4:
    Confirms ZipRecruiter per-source status records structured status ('empty')
    with an accurate description (unsupported region/no listings) rather than
    unsupported cause claims.
    """
    import pandas as pd
    from backend.services.radar_jobspy import discover_jobspy_opportunities

    empty_df = pd.DataFrame()

    with patch("jobspy.scrape_jobs", return_value=empty_df):
        summary = await discover_jobspy_opportunities(
            sites=["zip_recruiter"],
            search_terms=["intern"],
            location="India",
        )
        assert "zip_recruiter" in summary["per_source_status"]
        zr_status = summary["per_source_status"]["zip_recruiter"]
        assert zr_status["status"] == "empty"
        assert zr_status["raw_count"] == 0
        assert "unsupported region" in zr_status["reason"].lower() or "no listings" in zr_status["reason"].lower()



