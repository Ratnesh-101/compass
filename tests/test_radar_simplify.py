"""Unit tests for the SimplifyJobs radar adapter. No network, no database."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models_radar import OpportunityStatus
from backend.services.radar_simplify import (
    fetch_simplify_opportunities,
    normalize_simplify_listing,
    verify_candidates,
)

PAST_TS = 1_700_000_000  # 2023-11-14 UTC


def _item(**over):
    base = {
        "active": True,
        "is_visible": True,
        "category": "Software",
        "url": "https://example.com/jobs/1",
        "company_name": "Acme",
        "title": "Software Engineer Intern",
        "locations": ["Bangalore, India"],
        "date_posted": PAST_TS,
        "terms": ["Summer 2027"],
    }
    base.update(over)
    return base


# (1) normalize_simplify_listing


@pytest.mark.parametrize(
    "over",
    [
        {"active": False},
        {"is_visible": False},
        {"category": "Product"},
        {"category": "Quant"},
        {"url": ""},
        {"url": None},
        {"company_name": ""},
        {"title": ""},
    ],
)
def test_normalize_skips_ineligible(over):
    assert normalize_simplify_listing(_item(**over)) is None


@pytest.mark.parametrize("cat", ["Software", "AI/ML/Data", "Hardware"])
def test_normalize_keeps_cse_categories(cat):
    assert normalize_simplify_listing(_item(category=cat)) is not None


def test_normalize_fields_and_utc_epoch():
    out = normalize_simplify_listing(_item())
    assert out["current_status"] == OpportunityStatus.NEEDS_VERIFICATION
    assert out["posted_at_precision"] == "exact"
    expected = datetime.fromtimestamp(PAST_TS, tz=timezone.utc)
    assert out["posted_at"] == expected.isoformat()
    assert datetime.fromisoformat(out["posted_at"]).utcoffset().total_seconds() == 0
    assert out["is_india_eligible"] is True


def test_normalize_india_eligibility_only_when_india_present():
    out = normalize_simplify_listing(_item(locations=["New York, NY"]))
    assert out["is_india_eligible"] is False


def test_normalize_future_date_is_unknown():
    future = int(datetime.now(timezone.utc).timestamp()) + 10 * 86400
    out = normalize_simplify_listing(_item(date_posted=future))
    assert out["posted_at"] is None
    assert out["posted_at_precision"] == "unknown"


# (2) fetch_simplify_opportunities


def _client_returning(payload):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = b"{}"
    resp.json = MagicMock(return_value=payload)
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_fetch_dedupes_sorts_and_limits():
    rows = [
        _item(url="https://a.example.com/j/1", title="Old", date_posted=PAST_TS),
        _item(url="https://b.example.com/j/2", title="New", date_posted=PAST_TS + 1000),
        _item(url="https://a.example.com/j/1", title="Old dup", date_posted=PAST_TS),
        _item(url="https://c.example.com/j/3", title="Mid", date_posted=PAST_TS + 500),
    ]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        out = await fetch_simplify_opportunities()
        assert [o["role_title"] for o in out] == ["New", "Mid", "Old"]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        limited = await fetch_simplify_opportunities(limit=2)
        assert [o["role_title"] for o in limited] == ["New", "Mid"]


@pytest.mark.asyncio
async def test_fetch_rejects_non_list_payload():
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning({"a": 1})):
        with pytest.raises(ValueError, match="unexpected Simplify file layout"):
            await fetch_simplify_opportunities()


# (3) verify_candidates


def _opp(url):
    return {
        "official_application_url": url,
        "role_title": "r",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "verification_evidence": "orig",
        "application_url_checked": False,
    }


@pytest.mark.asyncio
async def test_verify_candidates_promotes_closes_and_leaves_untouched():
    opps = [_opp("https://o.example.com"), _opp("https://c.example.com"), _opp("https://e.example.com")]
    now = datetime.now(timezone.utc)

    async def fake(url, status):
        if "o.example" in url:
            return OpportunityStatus.OPEN_CONFIRMED, "open ev", now
        if "c.example" in url:
            return OpportunityStatus.CLOSED_CONFIRMED, "closed ev", now
        raise RuntimeError("network down")

    with patch("backend.services.radar_verifier.verify_opportunity_status", side_effect=fake):
        count = await verify_candidates(opps)

    assert count == 1
    assert opps[0]["current_status"] == OpportunityStatus.OPEN_CONFIRMED
    assert opps[0]["application_url_checked"] is True
    assert opps[0]["last_verified_at"] == now
    assert opps[1]["current_status"] == OpportunityStatus.CLOSED_CONFIRMED
    assert opps[2]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION
    assert opps[2]["verification_evidence"] == "orig"
    assert opps[2]["application_url_checked"] is False
