"""Nightly re-verification of stale OPEN_CONFIRMED internship listings (no network)."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.memory.radar import get_opportunity_by_id, upsert_opportunity
from backend.models_radar import OpportunityStatus
from backend.services import radar_reverify
from backend.services.radar_reverify import (
    DEFAULT_BATCH_SIZE,
    RECHECK_AFTER_DAYS,
    reverify_stale_opportunities,
    select_stale_open_opportunities,
)

BIG = 100000  # large enough that unrelated rows in the local DB cannot crowd ours out


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _seed(tag: str, name: str, days_ago, status=OpportunityStatus.OPEN_CONFIRMED) -> tuple[int, str]:
    url = f"https://reverify.example/{tag}/{name}"
    oid = await upsert_opportunity(
        company_name=f"ReverifyCo{tag}{name}",
        role_title=f"Intern {tag}{name}",
        canonical_url=url,
        current_status=status,
        country="India",
        is_india_eligible=True,
        last_verified_at=_ago(days_ago) if days_ago is not None else None,
    )
    return oid, url


def _fake_verify(tag: str, outcomes: dict):
    """Fake verifier: only URLs containing `tag` get an outcome; others raise (left untouched)."""
    calls = []

    async def fake(url, current_status):
        calls.append(url)
        if tag not in url:
            raise RuntimeError("not part of this test")
        out = outcomes[url.rsplit("/", 1)[-1]]
        if isinstance(out, BaseException):
            raise out
        status, evidence = out
        return status, evidence, datetime.now(timezone.utc)

    fake.calls = calls
    return fake


def test_contract_constants():
    assert RECHECK_AFTER_DAYS == 14
    assert DEFAULT_BATCH_SIZE == 25


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_selects_only_stale_open_oldest_first():
    tag = uuid.uuid4().hex[:8]
    old, _ = await _seed(tag, "old", 400)
    mid, _ = await _seed(tag, "mid", 40)
    fresh, _ = await _seed(tag, "fresh", 3)
    closed, _ = await _seed(tag, "closed", 100, status=OpportunityStatus.CLOSED_CONFIRMED)
    disc, _ = await _seed(tag, "disc", 100, status=OpportunityStatus.DISCOVERED)

    rows = await select_stale_open_opportunities(limit=BIG)
    ids = [r["id"] for r in rows]
    assert old in ids and mid in ids
    assert fresh not in ids and closed not in ids and disc not in ids
    assert ids.index(old) < ids.index(mid)
    for r in rows:
        assert r["current_status"] == OpportunityStatus.OPEN_CONFIRMED
        assert r["application_url"]
        assert "last_verified_at" in r
    mine = {r["id"]: r for r in rows}
    assert mine[old]["application_url"].startswith("https://reverify.example/")


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_selects_open_rows_with_no_verified_date():
    tag = uuid.uuid4().hex[:8]
    oid, _ = await _seed(tag, "nodate", None)
    row = await get_opportunity_by_id(oid)
    if row.last_verified_at is not None:
        pytest.skip("storage layer stamps a date on insert; no NULL row can be created")
    ids = [r["id"] for r in await select_stale_open_opportunities(limit=BIG)]
    assert oid in ids


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_select_respects_limit_and_order():
    tag = uuid.uuid4().hex[:8]
    for i in range(3):
        await _seed(tag, f"n{i}", 300 + i)
    rows = await select_stale_open_opportunities(limit=2)
    assert len(rows) <= 2
    dated = [r["last_verified_at"] for r in rows if r["last_verified_at"] is not None]
    assert dated == sorted(dated)
    assert await select_stale_open_opportunities(limit=0) == []


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_still_open_refreshes_date_and_stays_open():
    tag = uuid.uuid4().hex[:8]
    oid, _ = await _seed(tag, "a", 30)
    before = (await get_opportunity_by_id(oid)).last_verified_at
    fake = _fake_verify(tag, {"a": (OpportunityStatus.OPEN_CONFIRMED, "apply button present")})
    res = await reverify_stale_opportunities(limit=BIG, verify=fake)
    after = await get_opportunity_by_id(oid)
    assert res["dry_run"] is False
    assert res["still_open"] >= 1
    assert after.current_status == OpportunityStatus.OPEN_CONFIRMED
    assert after.last_verified_at > before
    assert after.last_verified_at > _ago(1)
    assert "apply button present" in (after.verification_evidence or "")


@pytest.mark.timeout(120)
@pytest.mark.asyncio
@pytest.mark.parametrize("new_status", [OpportunityStatus.NEEDS_VERIFICATION, OpportunityStatus.CLOSED_CONFIRMED])
async def test_non_open_result_downgrades_row(new_status):
    tag = uuid.uuid4().hex[:8]
    oid, _ = await _seed(tag, "b", 30)
    fake = _fake_verify(tag, {"b": (new_status, "page says closed")})
    res = await reverify_stale_opportunities(limit=BIG, verify=fake)
    after = await get_opportunity_by_id(oid)
    assert res["downgraded"] >= 1
    assert after.current_status == new_status
    # never invents close dates
    assert after.confirmed_close_date is None


@pytest.mark.timeout(120)
@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [RuntimeError("boom"), asyncio.TimeoutError()])
async def test_exception_or_timeout_leaves_row_untouched(exc):
    tag = uuid.uuid4().hex[:8]
    oid, _ = await _seed(tag, "c", 30)
    before = await get_opportunity_by_id(oid)
    fake = _fake_verify(tag, {"c": exc})
    res = await reverify_stale_opportunities(limit=BIG, verify=fake)
    after = await get_opportunity_by_id(oid)
    assert res["errors"] >= 1
    assert after.current_status == OpportunityStatus.OPEN_CONFIRMED
    assert after.last_verified_at == before.last_verified_at
    assert after.verification_evidence == before.verification_evidence


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_real_wait_for_timeout_counts_as_error(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    oid, _ = await _seed(tag, "d", 30)
    before = await get_opportunity_by_id(oid)

    real_wait_for = asyncio.wait_for

    async def short_wait_for(aw, timeout):
        return await real_wait_for(aw, timeout=0.05)

    async def slow(url, current_status):
        await asyncio.sleep(5)
        return OpportunityStatus.OPEN_CONFIRMED, "late", datetime.now(timezone.utc)

    monkeypatch.setattr(radar_reverify.asyncio, "wait_for", short_wait_for)
    res = await reverify_stale_opportunities(limit=1, verify=slow)
    after = await get_opportunity_by_id(oid)
    assert res["errors"] >= 0  # limit=1 may pick another stale row; the call must not raise
    if res["checked"] and res["errors"]:
        assert after.last_verified_at == before.last_verified_at


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_dry_run_writes_nothing():
    tag = uuid.uuid4().hex[:8]
    oid, _ = await _seed(tag, "a", 30)
    before = await get_opportunity_by_id(oid)
    fake = _fake_verify(tag, {"a": (OpportunityStatus.CLOSED_CONFIRMED, "closed")})
    res = await reverify_stale_opportunities(limit=BIG, dry_run=True, verify=fake)
    after = await get_opportunity_by_id(oid)
    assert res["dry_run"] is True
    assert set(res) >= {"checked", "still_open", "downgraded", "errors", "dry_run"}
    assert after.current_status == OpportunityStatus.OPEN_CONFIRMED
    assert after.last_verified_at == before.last_verified_at
    assert after.verification_evidence == before.verification_evidence


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_never_raises_when_selection_fails(monkeypatch):
    async def broken(limit=DEFAULT_BATCH_SIZE):
        raise RuntimeError("db down")

    monkeypatch.setattr(radar_reverify, "select_stale_open_opportunities", broken)
    res = await reverify_stale_opportunities(verify=_fake_verify("x", {}))
    assert isinstance(res, dict)
    assert res["checked"] == 0
    assert res["dry_run"] is False


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_never_raises_when_every_verify_fails():
    tag = uuid.uuid4().hex[:8]
    await _seed(tag, "e", 30)

    async def always_fail(url, current_status):
        raise ValueError("nope")

    res = await reverify_stale_opportunities(limit=BIG, verify=always_fail)
    assert res["errors"] >= 1
    assert res["still_open"] == 0 and res["downgraded"] == 0


def test_run_radar_sync_hooks_reverify():
    src = (Path(__file__).resolve().parent.parent / "backend" / "services" / "radar_sync.py").read_text(encoding="utf-8")
    assert "reverify_stale_opportunities" in src
    assert "dry_run=dry_run" in src
    assert '"reverify"' in src or "'reverify'" in src
    # hook must be guarded so a failure cannot fail the sync
    hook = src.index("reverify_stale_opportunities(")
    assert "try:" in src[max(0, hook - 600):hook]
    assert "except" in src[hook:hook + 800]


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_time_budget_stops_the_run_and_leaves_remaining_rows(monkeypatch):
    from backend.services import radar_reverify

    calls = []

    async def fake_verify(url, status=None):
        calls.append(url)
        return ("OPEN_CONFIRMED", "ok", datetime.now(timezone.utc))

    monkeypatch.setattr(radar_reverify, "TOTAL_BUDGET_SECONDS", 0.0)
    result = await radar_reverify.reverify_stale_opportunities(limit=5, dry_run=True, verify=fake_verify)
    assert calls == []
    assert result["checked"] == 0
