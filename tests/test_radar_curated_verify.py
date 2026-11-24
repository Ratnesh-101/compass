"""Tests for curated-listing re-verification and the Simplify India flag fix. No network, no database."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.memory import radar_close
from backend.models_radar import OpportunityStatus
from backend.services import radar_curated_verify as rcv
from backend.services.radar_curated_verify import fix_simplify_india_flags, verify_curated_listings

S = OpportunityStatus
FETCH_FAIL = "Official page returned HTTP 503. Status retained pending recheck."
COUNTER_KEYS = {"checked", "open", "closed", "needs_verification", "unchanged", "errors"}
OLD_TS = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _url(n):
    return f"https://curated.example.com/jobs/{n}"


def _opp(n, status=S.NEEDS_VERIFICATION, **over):
    row = {
        "canonical_url": _url(n),
        "official_application_url": _url(n),
        "role_title": f"Intern {n}",
        "current_status": status,
        "verification_evidence": "orig",
        "last_verified_at": OLD_TS,
        "sources": [{"source_type": "curated"}],
    }
    row.update(over)
    return row


def _item(n, status=S.NEEDS_VERIFICATION):
    return {
        "canonical_url": _url(n),
        "official_application_url": _url(n),
        "role_title": f"Intern {n}",
        "current_status": status,
    }


def _verifier(outcomes):
    """Build a verify callable returning (status, evidence, checked_at) per URL, or raising."""
    calls = []

    async def verify(url, status, *args, **kwargs):
        calls.append(url)
        out = outcomes[url]
        if isinstance(out, Exception):
            raise out
        st, ev = out
        return st, ev, datetime.now(timezone.utc)

    verify.calls = calls
    return verify


@pytest.fixture
def mem(monkeypatch):
    store = {}
    monkeypatch.setattr(radar_close, "get_pool", _none_pool)
    monkeypatch.setattr(radar_close, "_in_memory_opportunities", store)
    for mod in (rcv,):
        if hasattr(mod, "get_pool"):
            monkeypatch.setattr(mod, "get_pool", _none_pool)
        if hasattr(mod, "_in_memory_opportunities"):
            monkeypatch.setattr(mod, "_in_memory_opportunities", store)
    return store


async def _none_pool():
    return None


async def _run(mem, rows, outcomes, **kw):
    for i, r in enumerate(rows):
        mem[f"k{i}"] = r
    items = [_item(i, r["current_status"]) for i, r in enumerate(rows)]
    verify = _verifier(outcomes)
    counters = await verify_curated_listings(items, verify=verify, **kw)
    return counters, verify


@pytest.mark.asyncio
async def test_open_confirmed_refreshes_timestamp(mem):
    before = datetime.now(timezone.utc)
    counters, _ = await _run(mem, [_opp(0, S.OPEN_CONFIRMED)], {_url(0): (S.OPEN_CONFIRMED, "page live")})
    assert mem["k0"]["current_status"] == S.OPEN_CONFIRMED
    assert mem["k0"]["last_verified_at"] >= before
    assert counters["checked"] == 1 and counters["open"] == 1


@pytest.mark.asyncio
async def test_needs_verification_row_becomes_open_confirmed(mem):
    counters, _ = await _run(mem, [_opp(0)], {_url(0): (S.OPEN_CONFIRMED, "apply button")})
    assert mem["k0"]["current_status"] == S.OPEN_CONFIRMED
    assert counters["open"] == 1


@pytest.mark.asyncio
async def test_closed_confirmed_outcome_closes_row(mem):
    counters, _ = await _run(
        mem, [_opp(0, S.OPEN_CONFIRMED)], {_url(0): (S.CLOSED_CONFIRMED, "no longer accepting")}
    )
    assert mem["k0"]["current_status"] == S.CLOSED_CONFIRMED
    assert counters["closed"] == 1 and counters["checked"] == 1


@pytest.mark.parametrize("outcome", [S.NEEDS_VERIFICATION, S.STATUS_UNKNOWN])
@pytest.mark.asyncio
async def test_unclear_outcome_demotes_with_evidence(mem, outcome):
    counters, _ = await _run(mem, [_opp(0, S.OPEN_CONFIRMED)], {_url(0): (outcome, "page unclear")})
    assert mem["k0"]["current_status"] == S.NEEDS_VERIFICATION
    assert mem["k0"]["verification_evidence"] == "page unclear"
    assert counters["needs_verification"] == 1


@pytest.mark.asyncio
async def test_fetch_failure_leaves_row_untouched_and_counts_error(mem):
    row = _opp(0, S.OPEN_CONFIRMED)
    counters, _ = await _run(mem, [row], {_url(0): (S.NEEDS_VERIFICATION, FETCH_FAIL)})
    assert mem["k0"]["current_status"] == S.OPEN_CONFIRMED
    assert mem["k0"]["verification_evidence"] == "orig"
    assert mem["k0"]["last_verified_at"] == OLD_TS
    assert counters["errors"] == 1
    assert counters["needs_verification"] == 0


@pytest.mark.asyncio
async def test_exception_leaves_row_untouched_and_never_raises(mem):
    counters, _ = await _run(
        mem,
        [_opp(0, S.OPEN_CONFIRMED), _opp(1)],
        {_url(0): RuntimeError("boom"), _url(1): (S.OPEN_CONFIRMED, "ok")},
    )
    assert mem["k0"]["current_status"] == S.OPEN_CONFIRMED
    assert mem["k0"]["verification_evidence"] == "orig"
    assert counters["errors"] == 1
    assert mem["k1"]["current_status"] == S.OPEN_CONFIRMED
    assert counters["open"] == 1


@pytest.mark.parametrize("closed", [S.CLOSED_CONFIRMED, S.CANCELLED_CONFIRMED])
@pytest.mark.asyncio
async def test_closed_and_cancelled_rows_never_touched(mem, closed):
    await _run(mem, [_opp(0, closed)], {_url(0): (S.OPEN_CONFIRMED, "page live")})
    assert mem["k0"]["current_status"] == closed
    assert mem["k0"]["verification_evidence"] == "orig"
    assert mem["k0"]["last_verified_at"] == OLD_TS


@pytest.mark.asyncio
async def test_counters_dict_has_expected_keys_and_adds_up(mem):
    rows = [_opp(0), _opp(1, S.OPEN_CONFIRMED), _opp(2, S.OPEN_CONFIRMED), _opp(3)]
    counters, _ = await _run(
        mem,
        rows,
        {
            _url(0): (S.OPEN_CONFIRMED, "a"),
            _url(1): (S.CLOSED_CONFIRMED, "b"),
            _url(2): (S.STATUS_UNKNOWN, "c"),
            _url(3): RuntimeError("x"),
        },
    )
    assert COUNTER_KEYS <= set(counters)
    assert counters["checked"] == 4 or counters["checked"] == 3
    assert (counters["open"], counters["closed"], counters["needs_verification"], counters["errors"]) == (1, 1, 1, 1)


@pytest.mark.asyncio
async def test_empty_items_returns_zero_counters(mem):
    counters = await verify_curated_listings([], verify=_verifier({}))
    assert COUNTER_KEYS <= set(counters)
    assert all(counters[k] == 0 for k in COUNTER_KEYS)


@pytest.mark.asyncio
async def test_budget_stops_further_checks(mem):
    rows = [_opp(i) for i in range(5)]
    outcomes = {_url(i): (S.OPEN_CONFIRMED, "ok") for i in range(5)}
    counters, verify = await _run(mem, rows, outcomes, max_checks=2)
    assert len(verify.calls) == 2
    assert counters["checked"] == 2
    assert sum(1 for r in mem.values() if r["current_status"] == S.OPEN_CONFIRMED) == 2


# fix_simplify_india_flags


def _loc_row(location, *, india=True, country="India", source="simplify_listings", status=S.CLOSED_CONFIRMED):
    return {
        "canonical_url": f"https://x.example.com/{location}",
        "location": location,
        "is_india_eligible": india,
        "country": country,
        "current_status": status,
        "sources": [{"source_type": source}],
        "source_type": source,
    }


@pytest.mark.asyncio
async def test_fix_flags_corrects_indianapolis_and_indiana_keeps_pune(mem):
    mem["a"] = _loc_row("Indianapolis, IN")
    mem["b"] = _loc_row("Pune, Maharashtra, India")
    mem["c"] = _loc_row("Indiana")
    n = await fix_simplify_india_flags()
    assert mem["a"]["is_india_eligible"] is False and mem["a"]["country"] == "USA"
    assert mem["b"]["is_india_eligible"] is True and mem["b"]["country"] == "India"
    assert mem["c"]["is_india_eligible"] is False
    assert n == 2


@pytest.mark.asyncio
async def test_fix_flags_ignores_other_source_types(mem):
    mem["a"] = _loc_row("Indianapolis, IN", source="jobspy")
    n = await fix_simplify_india_flags()
    assert n == 0
    assert mem["a"]["is_india_eligible"] is True and mem["a"]["country"] == "India"


@pytest.mark.asyncio
async def test_fix_flags_is_idempotent(mem):
    mem["a"] = _loc_row("Indianapolis, IN")
    mem["b"] = _loc_row("Indiana", status=S.OPEN_CONFIRMED)
    mem["c"] = _loc_row("Pune, Maharashtra, India")
    assert await fix_simplify_india_flags() == 2
    assert await fix_simplify_india_flags() == 0


def test_radar_sync_imports_and_calls_new_functions():
    src = (Path(__file__).resolve().parent.parent / "backend" / "services" / "radar_sync.py").read_text(
        encoding="utf-8"
    )
    assert "verify_curated_listings" in src
    assert "fix_simplify_india_flags" in src
    assert "import" in src.split("verify_curated_listings")[0].splitlines()[-1] or "radar_curated_verify" in src
    assert "verify_curated_listings(" in src
    assert "fix_simplify_india_flags(" in src
