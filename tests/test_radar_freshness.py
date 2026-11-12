"""
Compass — Internship Radar Freshness Verification Tests.

Automated tests for:
1. Pure functions in backend/services/radar_freshness.py:
   - RECENCY_FRESH_DAYS constant
   - verification_age_days (exact dates, future dates, fallbacks, unparsable/missing dates)
   - is_fresh_open (open confirmed & <= 14d, boundaries, non-open, passed deadlines)
   - needs_recheck (open confirmed & (>14d or None), non-open statuses)
2. OpportunityOut schema fields (verification_age_days, needs_recheck with safe defaults)
3. OpportunityOverviewStats schema (stale_open_count)
4. _enrich_opportunity integration in backend/routers/radar.py
5. get_radar_overview_stats in-memory branch verification
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest

from backend.models_radar import (
    OpportunityOut,
    OpportunityOverviewStats,
    OpportunitySourceOut,
    OpportunityStatus,
)
from backend.services.radar_freshness import (
    RECENCY_FRESH_DAYS,
    is_fresh_open,
    needs_recheck,
    verification_age_days,
)
from backend.routers.radar import _enrich_opportunity
from backend.memory.radar import (
    _in_memory_opportunities,
    _in_memory_user_opps,
    get_radar_overview_stats,
)


# ---------------------------------------------------------------------------
# 1. Pure Function: RECENCY_FRESH_DAYS Constant
# ---------------------------------------------------------------------------

def test_recency_fresh_days_constant():
    """Verify standard freshness window constant is 14 days."""
    assert RECENCY_FRESH_DAYS == 14


# ---------------------------------------------------------------------------
# 2. Pure Function: verification_age_days
# ---------------------------------------------------------------------------

def test_verification_age_days_exact():
    """Calculates whole days elapsed since verification date."""
    ref_today = date(2026, 11, 12)

    # Verified today -> 0 days
    assert verification_age_days({"last_verified_at": date(2026, 11, 12)}, today=ref_today) == 0

    # Verified yesterday -> 1 day
    assert verification_age_days({"last_verified_at": date(2026, 11, 11)}, today=ref_today) == 1

    # Verified exactly 14 days ago (fresh boundary) -> 14 days
    assert verification_age_days({"last_verified_at": date(2026, 10, 29)}, today=ref_today) == 14

    # Verified 15 days ago (stale threshold) -> 15 days
    assert verification_age_days({"last_verified_at": date(2026, 10, 28)}, today=ref_today) == 15

    # Verified 45 days ago -> 45 days
    assert verification_age_days({"last_verified_at": date(2026, 9, 28)}, today=ref_today) == 45


def test_verification_age_days_future_dates():
    """Future dates count as 0 elapsed whole days (never rejected unless unparsable)."""
    ref_today = date(2026, 11, 12)

    # Tomorrow
    assert verification_age_days({"last_verified_at": date(2026, 11, 13)}, today=ref_today) == 0

    # One week ahead
    assert verification_age_days({"last_verified_at": date(2026, 11, 19)}, today=ref_today) == 0

    # Future datetime timestamp
    future_dt = datetime(2026, 11, 12, 23, 59, 59, tzinfo=timezone.utc)
    assert verification_age_days({"last_verified_at": future_dt}, today=ref_today) == 0


def test_verification_age_days_fallback_to_last_checked_at():
    """Falls back to last_checked_at when last_verified_at is missing."""
    ref_today = date(2026, 11, 12)

    # last_verified_at is None, last_checked_at is 3 days ago
    row = {"last_verified_at": None, "last_checked_at": date(2026, 11, 9)}
    assert verification_age_days(row, today=ref_today) == 3

    # When both are present, last_verified_at takes precedence
    row_both = {
        "last_verified_at": date(2026, 11, 5),
        "last_checked_at": date(2026, 11, 10),
    }
    assert verification_age_days(row_both, today=ref_today) == 7


def test_verification_age_days_fallback_to_sources():
    """Falls back to newest source check when direct dates are absent."""
    ref_today = date(2026, 11, 12)

    row = {
        "last_verified_at": None,
        "last_checked_at": None,
        "sources": [
            {"source_name": "careers", "last_checked_at": date(2026, 11, 8)},
            {"source_name": "aggregator", "last_checked_at": date(2026, 11, 10)},
        ],
    }
    # Newest source was checked on 2026-11-10 -> 2 days ago
    assert verification_age_days(row, today=ref_today) == 2


def test_verification_age_days_missing_and_unparsable():
    """Returns None for missing, null, or unparsable verification dates."""
    ref_today = date(2026, 11, 12)

    assert verification_age_days(None, today=ref_today) is None
    assert verification_age_days({}, today=ref_today) is None
    assert verification_age_days({"last_verified_at": None, "last_checked_at": None}, today=ref_today) is None
    assert verification_age_days({"last_verified_at": "not-a-valid-date"}, today=ref_today) is None
    assert verification_age_days({"last_verified_at": "none"}, today=ref_today) is None
    assert verification_age_days({"last_verified_at": "nan"}, today=ref_today) is None
    assert verification_age_days({"last_verified_at": ""}, today=ref_today) is None


def test_verification_age_days_string_formats():
    """Handles various ISO and standard date string formats."""
    ref_today = date(2026, 11, 12)

    # ISO string with Z
    assert verification_age_days({"last_verified_at": "2026-11-10T15:00:00Z"}, today=ref_today) == 2

    # ISO string with timezone offset
    assert verification_age_days({"last_verified_at": "2026-11-10T15:00:00+00:00"}, today=ref_today) == 2

    # Date-only string YYYY-MM-DD
    assert verification_age_days({"last_verified_at": "2026-11-08"}, today=ref_today) == 4


# ---------------------------------------------------------------------------
# 3. Pure Function: is_fresh_open
# ---------------------------------------------------------------------------

def test_is_fresh_open_rules():
    """A listing is fresh open ONLY if OPEN_CONFIRMED and verified within <= 14 days."""
    ref_today = date(2026, 11, 12)

    # 1. Fresh open (verified 2 days ago)
    assert is_fresh_open(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today - timedelta(days=2)},
        today=ref_today,
    ) is True

    # 2. Fresh open boundary (verified exactly 14 days ago)
    assert is_fresh_open(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today - timedelta(days=14)},
        today=ref_today,
    ) is True

    # 3. Stale open (verified 15 days ago) -> False
    assert is_fresh_open(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today - timedelta(days=15)},
        today=ref_today,
    ) is False

    # 4. Open confirmed without any date -> False (no date = NOT fresh)
    assert is_fresh_open(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": None},
        today=ref_today,
    ) is False

    # 5. Open confirmed with unparsable date -> False
    assert is_fresh_open(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": "invalid-timestamp"},
        today=ref_today,
    ) is False

    # 6. Future parsable date -> True (future dates count as fresh unless unparsable)
    assert is_fresh_open(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today + timedelta(days=1)},
        today=ref_today,
    ) is True

    # 7. Passed application deadline -> False
    assert is_fresh_open(
        {
            "current_status": OpportunityStatus.OPEN_CONFIRMED,
            "last_verified_at": ref_today - timedelta(days=1),
            "confirmed_close_date": ref_today - timedelta(days=1),
        },
        today=ref_today,
    ) is False

    # 8. Future close date -> True
    assert is_fresh_open(
        {
            "current_status": OpportunityStatus.OPEN_CONFIRMED,
            "last_verified_at": ref_today - timedelta(days=1),
            "confirmed_close_date": ref_today + timedelta(days=5),
        },
        today=ref_today,
    ) is True


def test_is_fresh_open_non_open_statuses():
    """Non-OPEN_CONFIRMED statuses are NEVER fresh open, even if recently verified."""
    ref_today = date(2026, 11, 12)
    recent_date = ref_today - timedelta(days=1)

    for st in (
        OpportunityStatus.UPCOMING_CONFIRMED,
        OpportunityStatus.ANNOUNCED,
        OpportunityStatus.DISCOVERED,
        OpportunityStatus.NEEDS_VERIFICATION,
        OpportunityStatus.CLOSED_CONFIRMED,
        OpportunityStatus.CANCELLED_CONFIRMED,
        OpportunityStatus.STATUS_UNKNOWN,
    ):
        assert is_fresh_open({"current_status": st, "last_verified_at": recent_date}, today=ref_today) is False


# ---------------------------------------------------------------------------
# 4. Pure Function: needs_recheck
# ---------------------------------------------------------------------------

def test_needs_recheck_rules():
    """needs_recheck is True for OPEN_CONFIRMED when age > 14 or date is None."""
    ref_today = date(2026, 11, 12)

    # 1. Fresh open (5 days ago) -> False
    assert needs_recheck(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today - timedelta(days=5)},
        today=ref_today,
    ) is False

    # 2. Fresh open boundary (14 days ago) -> False
    assert needs_recheck(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today - timedelta(days=14)},
        today=ref_today,
    ) is False

    # 3. Stale open (15 days ago) -> True
    assert needs_recheck(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today - timedelta(days=15)},
        today=ref_today,
    ) is True

    # 4. Missing verification date -> True
    assert needs_recheck(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": None},
        today=ref_today,
    ) is True

    # 5. Unparsable date -> True
    assert needs_recheck(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": "unparsable"},
        today=ref_today,
    ) is True

    # 6. Future parsable date -> False
    assert needs_recheck(
        {"current_status": OpportunityStatus.OPEN_CONFIRMED, "last_verified_at": ref_today + timedelta(days=2)},
        today=ref_today,
    ) is False

    # 7. Passed deadline -> False (deadline passed = closed, not open needs recheck)
    assert needs_recheck(
        {
            "current_status": OpportunityStatus.OPEN_CONFIRMED,
            "last_verified_at": ref_today - timedelta(days=20),
            "confirmed_close_date": ref_today - timedelta(days=1),
        },
        today=ref_today,
    ) is False


def test_needs_recheck_non_open_statuses():
    """needs_recheck is strictly False for any non-OPEN_CONFIRMED listing."""
    ref_today = date(2026, 11, 12)

    for st in (
        OpportunityStatus.UPCOMING_CONFIRMED,
        OpportunityStatus.ANNOUNCED,
        OpportunityStatus.DISCOVERED,
        OpportunityStatus.NEEDS_VERIFICATION,
        OpportunityStatus.CLOSED_CONFIRMED,
        OpportunityStatus.CANCELLED_CONFIRMED,
    ):
        # Even with no date or very old date, needs_recheck is False because status is not OPEN_CONFIRMED
        assert needs_recheck({"current_status": st, "last_verified_at": None}, today=ref_today) is False
        assert needs_recheck(
            {"current_status": st, "last_verified_at": ref_today - timedelta(days=40)},
            today=ref_today,
        ) is False


# ---------------------------------------------------------------------------
# 5. Pydantic Models: OpportunityOut & OpportunityOverviewStats
# ---------------------------------------------------------------------------

def test_opportunity_out_model_freshness_fields():
    """Verify OpportunityOut includes verification_age_days and needs_recheck with safe defaults."""
    opp = OpportunityOut(
        id=1,
        company_name="Google",
        normalized_company="google",
        role_title="Software Engineering Intern",
        canonical_url="https://careers.google.com/jobs/1",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
    )
    assert opp.verification_age_days is None
    assert opp.needs_recheck is False

    # Explicit values
    opp_custom = OpportunityOut(
        id=2,
        company_name="Microsoft",
        normalized_company="microsoft",
        role_title="Research Intern",
        canonical_url="https://careers.microsoft.com/jobs/2",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        verification_age_days=18,
        needs_recheck=True,
    )
    assert opp_custom.verification_age_days == 18
    assert opp_custom.needs_recheck is True

    # Serialized dict contains new fields
    dumped = opp_custom.model_dump()
    assert "verification_age_days" in dumped
    assert dumped["verification_age_days"] == 18
    assert "needs_recheck" in dumped
    assert dumped["needs_recheck"] is True


def test_overview_stats_model_stale_open_count():
    """Verify OpportunityOverviewStats includes stale_open_count with safe default 0."""
    stats = OpportunityOverviewStats()
    assert stats.verified_open_count == 0
    assert stats.stale_open_count == 0

    stats_custom = OpportunityOverviewStats(
        verified_open_count=12,
        stale_open_count=5,
        total_tracked_opportunities=20,
    )
    assert stats_custom.verified_open_count == 12
    assert stats_custom.stale_open_count == 5

    dumped = stats_custom.model_dump()
    assert "verified_open_count" in dumped
    assert "stale_open_count" in dumped
    assert dumped["verified_open_count"] == 12
    assert dumped["stale_open_count"] == 5


# ---------------------------------------------------------------------------
# 6. Route Enrichment: _enrich_opportunity
# ---------------------------------------------------------------------------

def test_enrich_opportunity_populates_freshness_metadata():
    """Verify _enrich_opportunity sets verification_age_days and needs_recheck."""
    now = datetime.now(timezone.utc)

    # 1. Fresh open listing (verified 3 days ago)
    opp_fresh = OpportunityOut(
        id=101,
        company_name="FreshCorp",
        normalized_company="freshcorp",
        role_title="SWE Intern",
        canonical_url="https://example.com/fresh",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        last_verified_at=now - timedelta(days=3),
    )
    enriched_fresh = _enrich_opportunity(opp_fresh, profile=None)
    assert enriched_fresh.verification_age_days == 3
    assert enriched_fresh.needs_recheck is False

    # 2. Stale open listing (verified 22 days ago)
    opp_stale = OpportunityOut(
        id=102,
        company_name="StaleCorp",
        normalized_company="stalecorp",
        role_title="Data Intern",
        canonical_url="https://example.com/stale",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        last_verified_at=now - timedelta(days=22),
    )
    enriched_stale = _enrich_opportunity(opp_stale, profile=None)
    assert enriched_stale.verification_age_days == 22
    assert enriched_stale.needs_recheck is True

    # 3. Unverified open listing (no date)
    opp_unverified = OpportunityOut(
        id=103,
        company_name="UnverifiedCorp",
        normalized_company="unverifiedcorp",
        role_title="Cloud Intern",
        canonical_url="https://example.com/unverified",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        last_verified_at=None,
    )
    enriched_unverified = _enrich_opportunity(opp_unverified, profile=None)
    assert enriched_unverified.verification_age_days is None
    assert enriched_unverified.needs_recheck is True

    # 4. Passed deadline -> transitions to CLOSED_CONFIRMED; needs_recheck is False
    opp_passed_deadline = OpportunityOut(
        id=104,
        company_name="PassedCorp",
        normalized_company="passedcorp",
        role_title="Backend Intern",
        canonical_url="https://example.com/passed",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
        confirmed_close_date=datetime.now(timezone.utc).date() - timedelta(days=2),
        last_verified_at=now - timedelta(days=20),
    )
    enriched_passed = _enrich_opportunity(opp_passed_deadline, profile=None)
    assert enriched_passed.current_status == OpportunityStatus.CLOSED_CONFIRMED
    assert enriched_passed.needs_recheck is False


# ---------------------------------------------------------------------------
# 7. In-Memory Overview Stats Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_memory_get_radar_overview_stats():
    """Verify get_radar_overview_stats in-memory branch divides open into fresh & stale."""
    today = datetime.now(timezone.utc).date()
    now_utc = datetime.now(timezone.utc)

    # Save original in-memory state
    orig_opps = dict(_in_memory_opportunities)
    _in_memory_opportunities.clear()

    try:
        # 1. Fresh open (verified 2 days ago)
        _in_memory_opportunities[1] = {
            "id": 1,
            "company_name": "A",
            "role_title": "Role A",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": now_utc - timedelta(days=2),
            "employer_type": "startup",
        }
        # 2. Fresh open boundary (verified 14 days ago)
        _in_memory_opportunities[2] = {
            "id": 2,
            "company_name": "B",
            "role_title": "Role B",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": now_utc - timedelta(days=14),
            "employer_type": "enterprise",
        }
        # 3. Stale open (verified 16 days ago)
        _in_memory_opportunities[3] = {
            "id": 3,
            "company_name": "C",
            "role_title": "Role C",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": now_utc - timedelta(days=16),
            "employer_type": "research",
        }
        # 4. Stale open (no date at all)
        _in_memory_opportunities[4] = {
            "id": 4,
            "company_name": "D",
            "role_title": "Role D",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": None,
            "employer_type": "government",
        }
        # 5. Fresh open via sources fallback (checked 4 days ago)
        _in_memory_opportunities[5] = {
            "id": 5,
            "company_name": "E",
            "role_title": "Role E",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": None,
            "sources": [{"last_checked_at": today - timedelta(days=4)}],
            "employer_type": "open_source",
        }
        # 6. Passed deadline (closed confirmed)
        _in_memory_opportunities[6] = {
            "id": 6,
            "company_name": "F",
            "role_title": "Role F",
            "current_status": "OPEN_CONFIRMED",
            "confirmed_close_date": today - timedelta(days=1),
            "last_verified_at": now_utc,
            "employer_type": "startup",
        }
        # 7. Upcoming confirmed opening
        _in_memory_opportunities[7] = {
            "id": 7,
            "company_name": "G",
            "role_title": "Role G",
            "current_status": "UPCOMING_CONFIRMED",
            "last_verified_at": now_utc,
            "employer_type": "enterprise",
        }

        # Force in-memory branch by mocking get_pool to return None
        with patch("backend.memory.radar.get_pool", AsyncMock(return_value=None)):
            stats = await get_radar_overview_stats(user_id="test_freshness_user")

        # 3 fresh open (1, 2, 5)
        assert stats["verified_open_count"] == 3
        # 2 stale open (3, 4)
        assert stats["stale_open_count"] == 2
        # 1 opening soon (7)
        assert stats["opening_soon_count"] == 1
        # Total tracked = 7
        assert stats["total_tracked_opportunities"] == 7

    finally:
        # Restore original in-memory opportunities
        _in_memory_opportunities.clear()
        _in_memory_opportunities.update(orig_opps)
