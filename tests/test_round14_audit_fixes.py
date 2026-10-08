"""
Tests for Round 14 Hostile Audit Hardening:
- Finding R14-A1 & R14-A2: Verbatim quote preservation past 3,000 chars and verdict logic.
- Finding R14-B1: Timezone parsing (PT, EDT, IST, 1pm without colon, midnight) and IST formatting.
- Finding R14-F1: Cross-user cache key isolation of pinned trusted URLs.
- Finding R14-G1: Rate limiter untrusted edge peer isolation against header spoofing.
- Finding R14-E1: Hallucination defense on zero-deadline and conflicting pages.
"""

from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import MagicMock

from backend.services.tavily_pipeline import (
    _cache_key,
    _parse_time_and_tz,
    _parse_explicit_year_date,
    evaluate_deterministic_verdict,
)
from backend.services.tavily_authority import AuthorityTier
from backend.services.rate_limiter import enforce_mint_rate_limit


def test_timezone_parsing_pt_edt_ist_and_midnight():
    """Verify flexible time formats, optional colon, midnight, and IST."""
    # 1. 10:00 am Pacific Time
    h, m, tz = _parse_time_and_tz("10:00 am Pacific Time")
    assert h == 10 and m == 0
    assert tz == timezone(timedelta(hours=-7))

    # 2. 1:00pm EDT
    h, m, tz = _parse_time_and_tz("1:00pm EDT")
    assert h == 13 and m == 0
    assert tz == timezone(timedelta(hours=-4))

    # 3. 1pm EDT (without colon)
    h, m, tz = _parse_time_and_tz("1pm EDT")
    assert h == 13 and m == 0
    assert tz == timezone(timedelta(hours=-4))

    # 4. 11:30 pm IST
    h, m, tz = _parse_time_and_tz("11:30 pm IST")
    assert h == 23 and m == 30
    assert tz == timezone(timedelta(hours=5, minutes=30))

    # 5. Midnight edge case
    h, m, tz = _parse_time_and_tz("before midnight")
    assert h == 23 and m == 59


def test_ist_conversion_for_pacific_deadline():
    """Confirm 10:00 AM PDT on Oct 30, 2026 converts to 22:30 IST on same day."""
    dt, prov = _parse_explicit_year_date(
        "Submission Period: Wednesday, August 26, 2026 (9:00 am Pacific Time) – Friday, October 30, 2026 (10:00 am Pacific Time)"
    )
    assert dt is not None
    assert prov == "explicit_in_quote"
    
    # Normalize to UTC
    utc_dt = dt.astimezone(timezone.utc)
    assert utc_dt.hour == 17
    assert utc_dt.minute == 0

    # Convert to IST
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    ist_dt = dt.astimezone(ist_tz)
    assert ist_dt.hour == 22
    assert ist_dt.minute == 30
    assert ist_dt.day == 30
    assert ist_dt.month == 10


def test_cross_user_cache_isolation_for_pinned_url():
    """Ensure User A's pinned URL produces a distinct cache key from User B's unpinned query."""
    key_pinned = _cache_key("nebius hackathon deadline", ["devpost.com"], trusted_event_url="https://nebiusglobalaihackathon.devpost.com")
    key_unpinned = _cache_key("nebius hackathon deadline", ["devpost.com"], trusted_event_url=None)
    key_user_b = _cache_key("nebius hackathon deadline", ["devpost.com"], trusted_event_url="https://otherhackathon.devpost.com")

    assert key_pinned != key_unpinned
    assert key_pinned != key_user_b


def test_verbatim_quote_evaluation_and_ledger_enrichment():
    """Ensure claims past 3,000 chars are evaluated VERIFIED and have normalized UTC & IST fields."""
    padding = "A" * 4000  # simulate page content before the rule
    rule = "Submission Period: Wednesday, August 26, 2026 (9:00 am Pacific Time) – Friday, October 30, 2026 (10:00 am Pacific Time)"
    full_text = f"{padding}\n\n{rule}\n\nAdditional text"

    claims = [{
        "claim": rule,
        "source_url": "https://nebiusglobalaihackathon.devpost.com/rules",
        "exact_quote": rule,
        "extracted_date": rule,
    }]
    sources = [{
        "url": "https://nebiusglobalaihackathon.devpost.com/rules",
        "authority_tier": AuthorityTier.TIER_1_OFFICIAL.value,
        "authority_badge": "User-trusted source",
    }]

    overall, ledger = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=full_text,
        sources=sources,
        target_entity="Nebius Global AI Hackathon",
    )

    assert overall == "VERIFIED"
    assert len(ledger) == 1
    item = ledger[0]
    assert item["verdict"] == "VERIFIED"
    assert item["authority_badge"] == "User-trusted source"
    assert item["normalized_utc"] == "2026-10-30T17:00:00Z"
    assert "10:30 PM IST" in item["local_deadline_ist"]
    assert item["exact_quote"] == rule
    assert item["fetched_at"] is not None


def test_hallucination_defense_on_page_without_deadlines():
    """Verify a page with zero deadline semantics produces NOT_FOUND without hallucinated dates."""
    marketing_text = (
        "Welcome to our innovative platform. Join us to empower developers worldwide. "
        "We are pioneering next-generation computing. All rights reserved. Subscribe to our newsletter."
    )
    claims = [{
        "claim": "Join us to empower developers worldwide.",
        "source_url": "https://example.com/about",
        "exact_quote": "Join us to empower developers worldwide.",
        "extracted_date": None,
    }]
    sources = [{
        "url": "https://example.com/about",
        "authority_tier": AuthorityTier.TIER_3_GENERAL.value,
        "authority_badge": "General Web",
    }]

    overall, ledger = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=marketing_text,
        sources=sources,
        target_entity="Example",
    )

    assert overall == "NOT_FOUND"
    assert len(ledger) == 0


def test_conflicting_deadlines_across_sources():
    """Verify distinct conflicting dates across sources return CONFLICTING."""
    corpus = "Deadline: October 30, 2026. Other page: Deadline is November 15, 2026."
    claims = [
        {
            "claim": "Submission deadline: October 30, 2026",
            "source_url": "https://example.com/source1",
            "exact_quote": "Deadline: October 30, 2026",
            "extracted_date": "October 30, 2026",
        },
        {
            "claim": "Submission deadline: November 15, 2026",
            "source_url": "https://example.com/source2",
            "exact_quote": "Deadline is November 15, 2026",
            "extracted_date": "November 15, 2026",
        },
    ]
    sources = [
        {"url": "https://example.com/source1", "authority_tier": AuthorityTier.TIER_1_OFFICIAL.value},
        {"url": "https://example.com/source2", "authority_tier": AuthorityTier.TIER_1_OFFICIAL.value},
    ]

    overall, ledger = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=corpus,
        sources=sources,
        target_entity="Example",
    )

    assert overall == "CONFLICTING"
    assert all(it["verdict"] == "CONFLICTING" for it in ledger)


@pytest.mark.asyncio
async def test_rate_limiter_spoofed_header_isolated_to_peer(monkeypatch):
    """Ensure untrusted edge requests use TCP peer host and reject header spoofing."""
    headers1 = {"x-forwarded-for": "1.1.1.1"}
    req1 = MagicMock()
    req1.headers.get = lambda k, default=None: headers1.get(k.lower(), default)
    req1.client.host = "192.168.1.100"

    headers2 = {"x-forwarded-for": "2.2.2.2"}
    req2 = MagicMock()
    req2.headers.get = lambda k, default=None: headers2.get(k.lower(), default)
    req2.client.host = "192.168.1.100"

    # Mock token consumer to record key used
    recorded_keys = []
    async def mock_consume(key, capacity, refill_rate_per_sec):
        recorded_keys.append(key)
        return True, 0

    async def mock_global_cap():
        return None

    monkeypatch.setattr("backend.services.rate_limiter._consume_token", mock_consume)
    monkeypatch.setattr("backend.services.budgets.check_global_mint_cap", mock_global_cap)
    monkeypatch.setattr("backend.services.security.is_edge_ip_trusted", lambda r: False)
    monkeypatch.setattr("backend.dependencies._get_current_identity", lambda r: None)

    await enforce_mint_rate_limit(req1)
    await enforce_mint_rate_limit(req2)

    assert len(recorded_keys) == 2
    # Both spoofed requests share the same physical peer bucket
    assert recorded_keys[0] == recorded_keys[1] == "mint:untrusted:192.168.1.100"
