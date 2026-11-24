"""Safety redesign tests for the Simplify sync: dataset sanity, demotion cap, delisted settlement.

No network, no database. The dataset's inactive flag is only a signal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory import radar_close
from backend.models_radar import OpportunityStatus
from backend.services import radar_simplify
from backend.services.radar_simplify import (
    LEGACY_CLOSE_EVIDENCE,
    SIMPLIFY_DELISTED_EVIDENCE,
    assess_dataset,
    fetch_simplify_dataset,
    fetch_simplify_dataset_checked,
    fetch_simplify_opportunities,
    plan_demotion,
    settle_delisted_listings,
)

TS = 1_700_000_000
SRC = "simplify_listings"
EVIDENCE = SIMPLIFY_DELISTED_EVIDENCE
MARKERS = (LEGACY_CLOSE_EVIDENCE, SIMPLIFY_DELISTED_EVIDENCE)


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


# (1) assess_dataset


def test_assess_dataset_rejects_small_total():
    ok, reason = assess_dataset(4999, 2000, {"u"}, {"a"})
    assert ok is False and reason


def test_assess_dataset_rejects_few_active():
    ok, reason = assess_dataset(10000, 999, {"u"}, {"a"})
    assert ok is False and reason


def test_assess_dataset_accepts_healthy():
    ok, _ = assess_dataset(10000, 2000, {"https://x/1"}, {"https://x/2"})
    assert ok is True


# (2) plan_demotion


def test_plan_demotion_removes_urls_that_are_also_active():
    to_demote, _ = plan_demotion({"a", "b", "c"}, {"b"}, 1000, 2)
    assert set(to_demote) == {"a", "c"}


def test_plan_demotion_cap_for_large_tracked_set():
    to_demote, _ = plan_demotion({"a"}, set(), 1000, 100)
    assert set(to_demote) == {"a"}
    to_demote, reason = plan_demotion({"a"}, set(), 1000, 101)
    assert not to_demote
    assert "safety cap" in reason


def test_plan_demotion_cap_floor_is_fifty():
    to_demote, _ = plan_demotion({"a"}, set(), 100, 50)
    assert set(to_demote) == {"a"}
    to_demote, reason = plan_demotion({"a"}, set(), 100, 51)
    assert not to_demote
    assert "safety cap" in reason


# (3) fetch_simplify_dataset_checked


@pytest.mark.asyncio
async def test_checked_rejects_non_list_payload():
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning({"a": 1})):
        with pytest.raises(ValueError):
            await fetch_simplify_dataset_checked()


@pytest.mark.asyncio
async def test_checked_rejects_malformed_rows():
    rows = [_row(i) for i in range(5)] + [{"foo": i} for i in range(5)]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        with pytest.raises(ValueError):
            await fetch_simplify_dataset_checked()


@pytest.mark.asyncio
async def test_checked_returns_triple_for_good_payload():
    rows = [_row(1), _row(2, active=False), _row(3)]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        active, inactive, total = await fetch_simplify_dataset_checked()
    assert [o["official_application_url"] for o in active] == [
        "https://example.com/jobs/3",
        "https://example.com/jobs/1",
    ]
    assert isinstance(inactive, set) and len(inactive) == 1
    assert total == 3


@pytest.mark.asyncio
async def test_old_fetch_shapes_unchanged():
    rows = [_row(1), _row(2, active=False)]
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        result = await fetch_simplify_dataset()
    assert isinstance(result, tuple) and len(result) == 2
    with patch("backend.services.radar_simplify.httpx.AsyncClient", _client_returning(rows)):
        out = await fetch_simplify_opportunities()
    assert isinstance(out, list) and len(out) == 1


# (4) in-memory fallback


def _mem_opp(url, status=OpportunityStatus.OPEN_CONFIRMED, source_type=SRC, evidence="orig", **extra):
    opp = {
        "canonical_url": url,
        "current_status": status,
        "verification_evidence": evidence,
        "sources": [{"source_type": source_type}],
    }
    opp.update(extra)
    return opp


@pytest.fixture
def mem(monkeypatch):
    store = {}
    monkeypatch.setattr(radar_close, "get_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(radar_close, "_in_memory_opportunities", store)
    return store


@pytest.mark.asyncio
async def test_count_open_by_source_and_matching(mem):
    mem["a"] = _mem_opp("https://x/1", OpportunityStatus.OPEN_CONFIRMED)
    mem["b"] = _mem_opp("https://x/2", OpportunityStatus.UPCOMING_CONFIRMED)
    mem["c"] = _mem_opp("https://x/3", OpportunityStatus.CLOSED_CONFIRMED)
    mem["d"] = _mem_opp("https://x/4", OpportunityStatus.OPEN_CONFIRMED, source_type="jobspy")
    assert await radar_close.count_open_by_source(SRC) == 2
    assert await radar_close.count_open_matching({"https://x/1", "https://x/3", "https://x/4"}, SRC) == 1


@pytest.mark.asyncio
async def test_demote_only_open_rows_of_right_source(mem):
    mem["a"] = _mem_opp("https://x/1", OpportunityStatus.OPEN_CONFIRMED)
    mem["b"] = _mem_opp("https://x/2", OpportunityStatus.UPCOMING_CONFIRMED)
    mem["c"] = _mem_opp("https://x/3", OpportunityStatus.CLOSED_CONFIRMED)
    mem["d"] = _mem_opp("https://x/4", OpportunityStatus.OPEN_CONFIRMED, source_type="jobspy")
    urls = {"https://x/1", "https://x/2", "https://x/3", "https://x/4"}
    n = await radar_close.demote_opportunities_by_canonical_urls(urls, SRC, EVIDENCE)
    assert n == 2
    for key in ("a", "b"):
        assert mem[key]["current_status"] == OpportunityStatus.NEEDS_VERIFICATION
        assert mem[key]["verification_evidence"] == EVIDENCE
    assert mem["c"]["current_status"] == OpportunityStatus.CLOSED_CONFIRMED
    assert mem["c"]["verification_evidence"] == "orig"
    assert mem["d"]["current_status"] == OpportunityStatus.OPEN_CONFIRMED
    assert mem["d"]["verification_evidence"] == "orig"


@pytest.mark.asyncio
async def test_reopen_only_marker_closed_rows(mem):
    mem["a"] = _mem_opp("https://x/1", OpportunityStatus.CLOSED_CONFIRMED, evidence=EVIDENCE)
    mem["b"] = _mem_opp(
        "https://x/2", OpportunityStatus.CLOSED_CONFIRMED, evidence="Official page returned HTTP 404"
    )
    n = await radar_close.reopen_wrongly_closed({"https://x/1", "https://x/2"}, SRC, MARKERS)
    assert n == 1
    assert mem["a"]["current_status"] != OpportunityStatus.CLOSED_CONFIRMED
    assert mem["b"]["current_status"] == OpportunityStatus.CLOSED_CONFIRMED
    assert mem["b"]["verification_evidence"] == "Official page returned HTTP 404"


@pytest.mark.asyncio
async def test_select_delisted_marker_only_oldest_first_limited(mem):
    now = datetime.now(timezone.utc)
    nv = OpportunityStatus.NEEDS_VERIFICATION
    for key, age, status, ev in [
        ("new", 1, nv, EVIDENCE),
        ("old", 30, nv, EVIDENCE),
        ("mid", 10, nv, EVIDENCE),
        ("plain", 50, nv, "Listed as active; not yet checked"),
        ("open", 60, OpportunityStatus.OPEN_CONFIRMED, EVIDENCE),
    ]:
        stamp = now - timedelta(days=age)
        mem[key] = _mem_opp(
            f"https://x/{key}", status, evidence=ev, updated_at=stamp, last_verified_at=stamp, created_at=stamp
        )
    rows = await radar_close.select_delisted_for_check(SRC, MARKERS, 2)
    urls = [r["application_url"] for r in rows]
    assert urls == ["https://x/old", "https://x/mid"]


# (5) settle_delisted_listings

UPDATE = "backend.services.radar_simplify.radar_memory.update_opportunity_verification"
SELECT = "backend.services.radar_simplify.select_delisted_for_check"


def _delisted(n):
    return {
        "id": f"id-{n}",
        "application_url": f"https://x/{n}",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "verification_evidence": EVIDENCE,
    }


def _verify_returning(status, evidence="ev"):
    return AsyncMock(return_value=(status, evidence, datetime.now(timezone.utc)))


def _statuses(update_mock):
    seen = []
    for call in update_mock.call_args_list:
        seen.extend(list(call.args) + list(call.kwargs.values()))
    return seen


async def _settle(verify, rows=None, **kw):
    update = AsyncMock()
    with patch(SELECT, AsyncMock(return_value=rows if rows is not None else [_delisted(1)])), patch(
        UPDATE, update
    ):
        result = await settle_delisted_listings(verify=verify, **kw)
    return result, update


def _get(result, key):
    return result[key] if isinstance(result, dict) else getattr(result, key)


@pytest.mark.asyncio
async def test_settle_closed_confirmed():
    result, update = await _settle(_verify_returning(OpportunityStatus.CLOSED_CONFIRMED))
    assert _get(result, "closed") == 1
    update.assert_awaited_once()
    assert OpportunityStatus.CLOSED_CONFIRMED in _statuses(update)


@pytest.mark.asyncio
async def test_settle_open_confirmed_reopens():
    result, update = await _settle(_verify_returning(OpportunityStatus.OPEN_CONFIRMED))
    assert _get(result, "reopened") == 1
    update.assert_awaited_once()
    assert OpportunityStatus.OPEN_CONFIRMED in _statuses(update)


@pytest.mark.asyncio
async def test_settle_fetch_failure_evidence_is_left_unchanged():
    verify = _verify_returning(
        OpportunityStatus.NEEDS_VERIFICATION,
        "Official page returned HTTP 503. Status retained pending recheck.",
    )
    result, update = await _settle(verify)
    update.assert_not_awaited()
    assert _get(result, "unchanged") == 1
    assert _get(result, "errors") == 0


@pytest.mark.asyncio
async def test_settle_exception_is_counted_and_not_raised():
    result, update = await _settle(AsyncMock(side_effect=RuntimeError("boom")), rows=[_delisted(1), _delisted(2)])
    update.assert_not_awaited()
    assert _get(result, "errors") == 2


@pytest.mark.asyncio
async def test_settle_other_status_unchanged():
    result, update = await _settle(_verify_returning(OpportunityStatus.NEEDS_VERIFICATION, "still unclear"))
    update.assert_not_awaited()
    assert _get(result, "closed") == 0
    assert _get(result, "reopened") == 0


@pytest.mark.asyncio
async def test_settle_dry_run_reports_without_updating():
    rows = [_delisted(1), _delisted(2)]
    verify = AsyncMock(
        side_effect=[
            (OpportunityStatus.CLOSED_CONFIRMED, "closed", datetime.now(timezone.utc)),
            (OpportunityStatus.OPEN_CONFIRMED, "open", datetime.now(timezone.utc)),
        ]
    )
    result, update = await _settle(verify, rows=rows, dry_run=True)
    update.assert_not_awaited()
    assert _get(result, "closed") == 1
    assert _get(result, "reopened") == 1


@pytest.mark.asyncio
async def test_settle_never_raises_when_select_fails():
    with patch(SELECT, AsyncMock(side_effect=RuntimeError("db down"))):
        result = await settle_delisted_listings(verify=_verify_returning(OpportunityStatus.CLOSED_CONFIRMED))
    assert result is not None


def test_module_exposes_expected_names():
    assert hasattr(radar_simplify, "settle_delisted_listings")
