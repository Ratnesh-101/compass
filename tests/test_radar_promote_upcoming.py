"""DB-free tests for promote_upcoming_opportunities and the curated upsert guard."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.services import radar_reverify

DT = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
FAIL_EVIDENCE = "Official page returned HTTP 503. Status retained pending recheck."
UPCOMING_EVIDENCE = "Reachable official portal; recruitment cycle remains upcoming."


def _row(opp_id: int) -> dict:
    return {
        "id": opp_id,
        "application_url": f"https://a.example/{opp_id}",
        "current_status": "UPCOMING_CONFIRMED",
        "last_verified_at": None,
    }


async def _verify(url, current_status=None):
    if url.endswith("/1"):
        return ("OPEN_CONFIRMED", "Verified open via x", DT)
    if url.endswith("/2"):
        return ("CLOSED_CONFIRMED", "removed", DT)
    if url.endswith("/3"):
        return ("UPCOMING_CONFIRMED", FAIL_EVIDENCE, DT)
    if url.endswith("/4"):
        return ("UPCOMING_CONFIRMED", UPCOMING_EVIDENCE, DT)
    raise RuntimeError("boom")


def _setup(monkeypatch, rows):
    async def fake_select(limit=radar_reverify.DEFAULT_BATCH_SIZE):
        return rows

    update = AsyncMock()
    monkeypatch.setattr(radar_reverify, "select_upcoming_opportunities", fake_select)
    monkeypatch.setattr(radar_reverify.radar_memory, "update_opportunity_verification", update)
    return update


@pytest.mark.asyncio
async def test_promote_upcoming_mixed_outcomes(monkeypatch):
    update = _setup(monkeypatch, [_row(i) for i in range(1, 6)])
    result = await radar_reverify.promote_upcoming_opportunities(verify=_verify)
    assert result == {"checked": 5, "promoted": 1, "closed": 1, "errors": 2, "dry_run": False}
    assert update.await_count == 2
    first, second = update.await_args_list
    assert first.kwargs["opportunity_id"] == 1
    assert first.kwargs["current_status"] == "OPEN_CONFIRMED"
    assert second.kwargs["opportunity_id"] == 2
    assert second.kwargs["current_status"] == "CLOSED_CONFIRMED"


@pytest.mark.asyncio
async def test_promote_upcoming_dry_run_writes_nothing(monkeypatch):
    update = _setup(monkeypatch, [_row(i) for i in range(1, 6)])
    result = await radar_reverify.promote_upcoming_opportunities(dry_run=True, verify=_verify)
    assert result["promoted"] == 1
    assert result["closed"] == 1
    assert result["dry_run"] is True
    update.assert_not_called()


@pytest.mark.asyncio
async def test_promote_upcoming_no_rows(monkeypatch):
    update = _setup(monkeypatch, [])
    result = await radar_reverify.promote_upcoming_opportunities(limit=0, verify=_verify)
    assert result == {"checked": 0, "promoted": 0, "closed": 0, "errors": 0, "dry_run": False}
    update.assert_not_called()


@pytest.mark.asyncio
async def test_select_upcoming_limit_zero_returns_empty():
    assert await radar_reverify.select_upcoming_opportunities(limit=0) == []


def test_curated_upsert_does_not_demote_open_to_upcoming():
    src = Path(__file__).resolve().parent.parent / "backend" / "memory" / "radar.py"
    text = src.read_text(encoding="utf-8")
    needle = "opportunities.current_status = 'OPEN_CONFIRMED' AND"
    clauses = [
        line
        for line in text.splitlines()
        if needle in line and "UPCOMING_CONFIRMED" in line
    ]
    assert len(clauses) >= 2, clauses
