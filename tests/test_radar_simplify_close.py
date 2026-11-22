"""Tests for the Simplify dataset split, batch close, and ATS-first verification. No network, no database."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory import radar_close
from backend.models_radar import OpportunityStatus
from backend.services.radar_simplify import (
    fetch_simplify_dataset,
    fetch_simplify_opportunities,
    split_simplify_dataset,
    verify_candidates,
)

TS = 1_700_000_000


def _row(n, **over):
    base = {
        "active": True,
        "is_visible": True,
        "category": "Software",
        "url": f"https://example.com/jobs/{n}",
        "company_name": "Acme",
        "title": f"Engineer Intern {n}",
        "locations": ["Bangalore, India"],
        "date_posted": TS + n,
        "terms": ["Summer 2027"],
    }
    base.update(over)
    return base


# (1) split_simplify_dataset


def test_split_inactive_cse_rows_go_to_inactive_set_only():
    rows = [
        _row(1),
        _row(2, active=False),
        _row(3, is_visible=False),
    ]
    active, inactive = split_simplify_dataset(rows)
    assert [o["official_application_url"] for o in active] == ["https://example.com/jobs/1"]
    assert len(inactive) == 2
    active_urls = {o["canonical_url"] for o in active}
    assert not (inactive & active_urls)


def test_split_non_cse_categories_in_neither():
    rows = [
        _row(1, category="Product"),
        _row(2, category="Quant"),
        _row(3, category="Product", active=False),
        _row(4, category="Quant", is_visible=False),
    ]
    active, inactive = split_simplify_dataset(rows)
    assert active == []
    assert inactive == set()


def test_split_active_newest_first_deduped_and_limited():
    rows = [
        _row(1, url="https://a.example.com/j/1", date_posted=TS),
        _row(2, url="https://b.example.com/j/2", date_posted=TS + 1000),
        _row(3, url="https://a.example.com/j/1", date_posted=TS + 10),
        _row(4, url="https://c.example.com/j/3", date_posted=TS + 500),
    ]
    active, _ = split_simplify_dataset(rows)
    assert [o["official_application_url"] for o in active] == [
        "https://b.example.com/j/2",
        "https://c.example.com/j/3",
        "https://a.example.com/j/1",
    ]
    limited, _ = split_simplify_dataset(rows, limit=2)
    assert [o["official_application_url"] for o in limited] == [
        "https://b.example.com/j/2",
        "https://c.example.com/j/3",
    ]


@pytest.mark.parametrize("bad", [None, {"a": 1}, "text", 5])
def test_split_non_list_input(bad):
    assert split_simplify_dataset(bad) == ([], set())


def test_split_inactive_row_sharing_url_with_active_row_is_in_inactive_set():
    url = "https://example.com/jobs/shared"
    rows = [
        _row(1, url=url, date_posted=TS + 5),
        _row(2, url=url, active=False, date_posted=TS),
    ]
    active, inactive = split_simplify_dataset(rows)
    assert len(active) == 1
    assert active[0]["canonical_url"] in inactive


# (2) fetch_simplify_dataset / fetch_simplify_opportunities


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
async def test_fetch_dataset_returns_tuple():
    rows = [_row(1), _row(2, active=False)]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        result = await fetch_simplify_dataset()
    assert isinstance(result, tuple) and len(result) == 2
    active, inactive = result
    assert [o["official_application_url"] for o in active] == ["https://example.com/jobs/1"]
    assert isinstance(inactive, set) and len(inactive) == 1


@pytest.mark.asyncio
async def test_fetch_opportunities_returns_only_active_list():
    rows = [_row(1), _row(2, active=False)]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        out = await fetch_simplify_opportunities()
    assert isinstance(out, list)
    assert [o["official_application_url"] for o in out] == ["https://example.com/jobs/1"]


# (3) close_opportunities_by_canonical_urls (in-memory fallback)


def _mem_opp(url, status=OpportunityStatus.NEEDS_VERIFICATION, source_type="simplify_listings"):
    return {
        "canonical_url": url,
        "current_status": status,
        "verification_evidence": "orig",
        "sources": [{"source_type": source_type}],
    }


@pytest.fixture
def mem(monkeypatch):
    store = {}
    monkeypatch.setattr(radar_close, "get_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(radar_close, "_in_memory_opportunities", store)
    return store


@pytest.mark.asyncio
async def test_close_matching_open_rows(mem):
    mem["a"] = _mem_opp("https://x.example.com/1")
    mem["b"] = _mem_opp("https://x.example.com/2", status=OpportunityStatus.OPEN_CONFIRMED)
    mem["c"] = _mem_opp("https://x.example.com/3")  # not in the url set
    before = datetime.now(timezone.utc)
    n = await radar_close.close_opportunities_by_canonical_urls(
        {"https://x.example.com/1", "https://x.example.com/2"}, "simplify_listings", "gone upstream"
    )
    assert n == 2
    for key in ("a", "b"):
        assert mem[key]["current_status"] == OpportunityStatus.CLOSED_CONFIRMED
        assert mem[key]["verification_evidence"] == "gone upstream"
        assert mem[key]["last_verified_at"] >= before
    assert mem["c"]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION
    assert mem["c"]["verification_evidence"] == "orig"


@pytest.mark.asyncio
async def test_close_ignores_other_source_type(mem):
    mem["a"] = _mem_opp("https://x.example.com/1", source_type="jobspy")
    n = await radar_close.close_opportunities_by_canonical_urls(
        {"https://x.example.com/1"}, "simplify_listings", "ev"
    )
    assert n == 0
    assert mem["a"]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION
    assert "last_verified_at" not in mem["a"]
    assert mem["a"]["verification_evidence"] == "orig"


@pytest.mark.asyncio
async def test_close_does_not_count_already_closed_or_cancelled(mem):
    mem["a"] = _mem_opp("https://x.example.com/1", status=OpportunityStatus.CLOSED_CONFIRMED)
    mem["b"] = _mem_opp("https://x.example.com/2", status=OpportunityStatus.CANCELLED_CONFIRMED)
    mem["c"] = _mem_opp("https://x.example.com/3")
    n = await radar_close.close_opportunities_by_canonical_urls(
        {"https://x.example.com/1", "https://x.example.com/2", "https://x.example.com/3"},
        "simplify_listings",
        "ev",
    )
    assert n == 1
    assert mem["a"]["verification_evidence"] == "orig"
    assert mem["b"]["current_status"] == OpportunityStatus.CANCELLED_CONFIRMED
    assert mem["b"]["verification_evidence"] == "orig"
    assert mem["c"]["current_status"] == OpportunityStatus.CLOSED_CONFIRMED


@pytest.mark.asyncio
async def test_close_empty_set_returns_zero(mem):
    mem["a"] = _mem_opp("https://x.example.com/1")
    assert await radar_close.close_opportunities_by_canonical_urls(set(), "simplify_listings", "ev") == 0
    assert mem["a"]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION


@pytest.mark.asyncio
async def test_close_return_value_equals_rows_changed(mem):
    for i in range(5):
        mem[str(i)] = _mem_opp(f"https://x.example.com/{i}")
    urls = {f"https://x.example.com/{i}" for i in range(3)} | {"https://x.example.com/missing"}
    n = await radar_close.close_opportunities_by_canonical_urls(urls, "simplify_listings", "ev")
    changed = [o for o in mem.values() if o["current_status"] == OpportunityStatus.CLOSED_CONFIRMED]
    assert n == len(changed) == 3


# (4) verify_candidates orders ATS-specific URLs first


@pytest.mark.asyncio
async def test_verify_candidates_checks_ats_urls_first():
    ats = ["https://boards.greenhouse.io/acme/jobs/1", "https://jobs.lever.co/acme/2"]
    other = ["https://plain.example.com/a", "https://plain.example.com/b", "https://plain.example.com/c"]
    opps = [
        {"official_application_url": u, "role_title": "r", "current_status": OpportunityStatus.NEEDS_VERIFICATION}
        for u in [other[0], ats[0], other[1], ats[1], other[2]]
    ]
    checked = []

    async def recorder(url, status):
        checked.append(url)
        return OpportunityStatus.NEEDS_VERIFICATION, "ev", datetime.now(timezone.utc)

    with patch("backend.services.radar_verifier.verify_opportunity_status", side_effect=recorder), patch(
        "backend.services.radar_verifier.is_specific_ats_job_url", side_effect=lambda u: u in ats
    ):
        count = await verify_candidates(opps, max_checks=2)

    assert count == 0
    assert sorted(checked) == sorted(ats)
