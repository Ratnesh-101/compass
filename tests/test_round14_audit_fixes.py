"""
Tests for Round 14 Hostile Audit Hardening:
- R14-G1: Rightmost X-Forwarded-For isolation against leftmost header spoofing.
- R14-A1 & R14-A2: Full text quote verification, countdown rejection, and UTC corroboration.
- R14-B1: zoneinfo (PDT vs PST around Nov 1 2026, EDT, IST, 1pm without colon, midnight).
- R14-F1: Warm cache raw results with per-caller authority badge isolation (User A pins, User B unpinned).
- R14-D1: Reasoning stream filtering (<think> blocks and reasoning_content stripped from SSE output).
"""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from backend.services.tavily_pipeline import (
    _raw_cache_key,
    _parse_time_and_tz,
    _parse_explicit_year_date,
    evaluate_deterministic_verdict,
    run_tavily_research,
    _RAW_SEARCH_CACHE,
)
from backend.services.tavily_authority import AuthorityTier
from backend.services.rate_limiter import enforce_mint_rate_limit
from backend.services.chat_stream import StreamingThinkFilter


def test_timezone_parsing_pt_edt_ist_and_midnight():
    """Verify zoneinfo time parsing, optional colon, midnight, and IST."""
    # 1. 10:00 am Pacific Time -> America/Los_Angeles
    h, m, tz = _parse_time_and_tz("10:00 am Pacific Time")
    assert h == 10 and m == 0
    assert tz == ZoneInfo("America/Los_Angeles")

    # 2. 1:00pm EDT -> America/New_York
    h, m, tz = _parse_time_and_tz("1:00pm EDT")
    assert h == 13 and m == 0
    assert tz == ZoneInfo("America/New_York")

    # 3. 1pm EDT (without colon)
    h, m, tz = _parse_time_and_tz("1pm EDT")
    assert h == 13 and m == 0
    assert tz == ZoneInfo("America/New_York")

    # 4. 11:30 pm IST -> Asia/Kolkata
    h, m, tz = _parse_time_and_tz("11:30 pm IST")
    assert h == 23 and m == 30
    assert tz == ZoneInfo("Asia/Kolkata")

    # 5. Midnight edge case -> 23:59 UTC
    h, m, tz = _parse_time_and_tz("before midnight")
    assert h == 23 and m == 59
    assert tz == ZoneInfo("UTC")


def test_pdt_vs_pst_and_ist_conversion():
    """Confirm PDT vs PST around Nov 1, 2026 and IST conversion:
    Oct 30 2026 10:00 PT (PDT) -> 17:00:00Z -> 22:30 IST.
    Nov 2 2026 10:00 PT (PST) -> 18:00:00Z -> 23:30 IST.
    """
    # Oct 30, 2026 (Before DST switch Nov 1)
    dt_oct, prov_oct = _parse_explicit_year_date(
        "Submission deadline: Friday, October 30, 2026 at 10:00 am Pacific Time"
    )
    assert dt_oct is not None
    assert prov_oct == "explicit_in_quote"
    assert dt_oct.tzinfo == ZoneInfo("America/Los_Angeles")
    utc_oct = dt_oct.astimezone(timezone.utc)
    assert utc_oct.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-10-30T17:00:00Z"
    ist_oct = dt_oct.astimezone(ZoneInfo("Asia/Kolkata"))
    assert ist_oct.strftime("%Y-%m-%d %H:%M") == "2026-10-30 22:30"

    # Nov 2, 2026 (After DST switch Nov 1)
    dt_nov, prov_nov = _parse_explicit_year_date(
        "Submission deadline: Monday, November 2, 2026 at 10:00 am Pacific Time"
    )
    assert dt_nov is not None
    assert dt_nov.tzinfo == ZoneInfo("America/Los_Angeles")
    utc_nov = dt_nov.astimezone(timezone.utc)
    assert utc_nov.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-11-02T18:00:00Z"
    ist_nov = dt_nov.astimezone(ZoneInfo("Asia/Kolkata"))
    assert ist_nov.strftime("%Y-%m-%d %H:%M") == "2026-11-02 23:30"


@pytest.mark.asyncio
async def test_warm_cache_raw_results_isolated_authority_badges(monkeypatch):
    """User A pins trusted_event_url and gets Tier 1 / User-trusted source.
    User B searches the same query with warm cache without pinned URL and must get Tier 2 / Platform Hosted,
    NEVER the pinned badge.
    """
    _RAW_SEARCH_CACHE.clear()

    mock_search = AsyncMock(return_value={
        "results": [
            {
                "url": "https://nebiusglobalaihackathon.devpost.com/rules",
                "title": "Nebius Global AI Hackathon Rules",
                "content": "Submission Period: Wednesday, August 26, 2026 (9:00 am Pacific Time) – Friday, October 30, 2026 (10:00 am Pacific Time)",
            }
        ]
    })
    mock_extract = AsyncMock(return_value={
        "results": [
            {
                "url": "https://nebiusglobalaihackathon.devpost.com/rules",
                "raw_content": "Official Rules. Submission Period: Wednesday, August 26, 2026 (9:00 am Pacific Time) – Friday, October 30, 2026 (10:00 am Pacific Time). All submissions close promptly.",
            }
        ]
    })

    monkeypatch.setattr("backend.services.tavily_pipeline.tavily_available", lambda: True)
    monkeypatch.setattr("backend.services.tavily_pipeline.tavily_search", mock_search)
    monkeypatch.setattr("backend.services.tavily_pipeline.tavily_extract", mock_extract)
    monkeypatch.setattr("backend.services.tavily_pipeline.persist_evidence_ledger", AsyncMock())

    # User A: pins URL
    res_a = await run_tavily_research(
        query="Nebius Global AI Hackathon deadline",
        trusted_event_url="https://nebiusglobalaihackathon.devpost.com",
    )
    assert res_a["verdict"] == "VERIFIED"
    assert res_a["cached"] is False
    badge_a = res_a["sources"][0]["authority_badge"]
    assert badge_a == "User-trusted source"

    calls_after_a = mock_search.call_count
    assert calls_after_a >= 1

    # User B: same query, NO pinned URL -> Warm cache hit, NO badge leak!
    res_b = await run_tavily_research(
        query="Nebius Global AI Hackathon deadline",
        trusted_event_url=None,
    )
    assert res_b["cached"] is True
    # mock_search must not have been called again (zero additional search calls)
    assert mock_search.call_count == calls_after_a
    source_b = res_b["sources"][0]
    assert source_b["authority_badge"] != "User-trusted source"
    assert source_b["authority_tier"] == AuthorityTier.TIER_2_TECHNICAL.value


def test_countdown_widget_text_is_never_verified_evidence():
    """Countdown widget strings like 'closes in 2 days 4 hours' must produce UNVERIFIED."""
    raw_page = "Submissions close in 2 days 4 hours left. Complete your project before time expires."
    claims = [{
        "claim": "Submissions close in 2 days 4 hours left",
        "source_url": "https://nebiusglobalaihackathon.devpost.com",
        "exact_quote": "Submissions close in 2 days 4 hours left",
        "extracted_date": None,
    }]
    sources = [{
        "url": "https://nebiusglobalaihackathon.devpost.com",
        "authority_tier": AuthorityTier.TIER_1_OFFICIAL.value,
        "authority_badge": "Official Organizer",
    }]

    overall, ledger = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=raw_page,
        sources=sources,
        target_entity="Nebius Global AI Hackathon",
    )
    assert overall == "NOT_FOUND" or overall == "UNVERIFIED"
    for item in ledger:
        assert item["verdict"] != "VERIFIED"


def test_tier2_corroboration_requires_matching_utc_instant():
    """Corroboration requires matching the explicit-year rule's UTC instant across official hosts."""
    raw = (
        "Devpost rules: Deadline is Friday, October 30, 2026 at 10:00 am Pacific Time. "
        "Devpost overview: Submission closes Friday, October 30, 2026 at 10:00 am Pacific Time. "
        "Blog: Deadline is October 31, 2026."
    )
    claims = [
        {
            "claim": "Deadline is Friday, October 30, 2026 at 10:00 am Pacific Time",
            "source_url": "https://devpost.com/page1",
            "exact_quote": "Deadline is Friday, October 30, 2026 at 10:00 am Pacific Time",
            "extracted_date": "October 30, 2026 at 10:00 am Pacific Time",
        },
        {
            "claim": "Submission closes Friday, October 30, 2026 at 10:00 am Pacific Time",
            "source_url": "https://devpost.com/page2",
            "exact_quote": "Submission closes Friday, October 30, 2026 at 10:00 am Pacific Time",
            "extracted_date": "October 30, 2026 at 10:00 am Pacific Time",
        },
    ]
    sources = [
        {"url": "https://devpost.com/page1", "authority_tier": AuthorityTier.TIER_2_TECHNICAL.value},
        {"url": "https://devpost.com/page2", "authority_tier": AuthorityTier.TIER_2_TECHNICAL.value},
    ]

    overall, ledger = evaluate_deterministic_verdict(
        claims=claims,
        raw_extracted_text=raw,
        sources=sources,
        target_entity=None,
    )
    assert overall == "VERIFIED"
    assert all(it["verdict"] == "VERIFIED" for it in ledger)


@pytest.mark.asyncio
async def test_rate_limiter_spoofed_leftmost_header_hits_same_bucket(monkeypatch):
    """Client cycling spoofed leftmost XFF entries still hits the exact same bucket
    anchored to the rightmost proxy-appended IP.
    """
    headers1 = {"x-forwarded-for": "10.0.0.1, 198.51.100.88"}
    req1 = MagicMock()
    req1.headers.get = lambda k, default=None: headers1.get(k.lower(), default)
    req1.client.host = "10.100.0.5"  # internal Render proxy container

    headers2 = {"x-forwarded-for": "10.0.0.2, 198.51.100.88"}
    req2 = MagicMock()
    req2.headers.get = lambda k, default=None: headers2.get(k.lower(), default)
    req2.client.host = "10.100.0.5"

    headers3 = {"x-forwarded-for": "1.2.3.4, 5.6.7.8, 198.51.100.88"}
    req3 = MagicMock()
    req3.headers.get = lambda k, default=None: headers3.get(k.lower(), default)
    req3.client.host = "10.100.0.5"

    recorded_keys = []
    async def mock_consume(key, capacity, refill_rate_per_sec):
        recorded_keys.append(key)
        return True, 0

    monkeypatch.setattr("backend.services.rate_limiter._consume_token", mock_consume)
    monkeypatch.setattr("backend.services.budgets.check_global_mint_cap", AsyncMock())
    monkeypatch.setattr("backend.dependencies._get_current_identity", lambda r: None)

    await enforce_mint_rate_limit(req1)
    await enforce_mint_rate_limit(req2)
    await enforce_mint_rate_limit(req3)

    assert len(recorded_keys) == 3
    # All 3 spoofed requests map strictly to the rightmost proxy IP bucket
    assert recorded_keys[0] == recorded_keys[1] == recorded_keys[2] == "mint:ip:198.51.100.88"


def test_streaming_think_filter_strips_reasoning_and_tags():
    """Verify StreamingThinkFilter removes <think>...</think> reasoning blocks across streamed chunks."""
    f = StreamingThinkFilter()
    chunks = [
        "Hello! ",
        "<th",
        "ink>Let me think through the problem step by step.</th",
        "ink>",
        "The verified deadline is ",
        "<think>internal reflection: check October 30</think>",
        "October 30, 2026.",
    ]
    emitted = []
    for c in chunks:
        tok = f.process(c)
        if tok:
            emitted.append(tok)

    result_text = "".join(emitted)
    assert "<think>" not in result_text
    assert "</think>" not in result_text
    assert "Let me think" not in result_text
    assert "internal reflection" not in result_text
    assert result_text == "Hello! The verified deadline is October 30, 2026."
