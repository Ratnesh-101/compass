"""India-only radar analytics counters. No network, no database."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.memory import radar

ROUTER_SRC = Path(__file__).resolve().parents[1] / "backend" / "routers" / "radar.py"


def _opp(n, status, india, verified_at):
    return {
        "id": f"opp-{n}",
        "current_status": status,
        "is_india_eligible": india,
        "last_verified_at": verified_at,
        "confirmed_close_date": None,
    }


@pytest.fixture
def mem(monkeypatch):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=40)
    rows = [
        _opp(1, "OPEN_CONFIRMED", True, now),
        _opp(2, "OPEN_CONFIRMED", True, now),
        _opp(3, "OPEN_CONFIRMED", False, now),
        _opp(4, "OPEN_CONFIRMED", True, old),
        _opp(5, "UPCOMING_CONFIRMED", True, now),
        _opp(6, "UPCOMING_CONFIRMED", False, now),
    ]
    store = {r["id"]: r for r in rows}
    monkeypatch.setattr(radar, "get_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(radar, "_in_memory_opportunities", store)

    async def fake_list_open(user_id, india_only=True, **_kw):
        # The card must equal the Open Now list: same function, same filters.
        return [
            r for r in store.values()
            if r["current_status"] == "OPEN_CONFIRMED"
            and r["last_verified_at"] >= now - timedelta(days=30)
            and (r["is_india_eligible"] or not india_only)
        ]

    monkeypatch.setattr(radar, "list_open_opportunities", fake_list_open)
    return store


def _counts(stats):
    return {
        k: stats[k]
        for k in (
            "verified_open_count",
            "stale_open_count",
            "opening_soon_count",
            "total_tracked_opportunities",
        )
    }


@pytest.mark.asyncio
async def test_india_only_false_counts_everything(mem):
    stats = await radar.get_radar_overview_stats("u1", india_only=False)
    assert stats["verified_open_count"] == 3
    assert stats["stale_open_count"] == 1
    assert stats["opening_soon_count"] == 2
    assert stats["total_tracked_opportunities"] == 6


@pytest.mark.asyncio
async def test_india_only_true_counts_only_india_rows(mem):
    stats = await radar.get_radar_overview_stats("u1", india_only=True)
    assert stats["verified_open_count"] == 2
    assert stats["stale_open_count"] == 1
    assert stats["opening_soon_count"] == 1
    assert stats["total_tracked_opportunities"] == 4


@pytest.mark.asyncio
async def test_default_equals_india_only_false(mem):
    default = await radar.get_radar_overview_stats("u1")
    explicit = await radar.get_radar_overview_stats("u1", india_only=False)
    assert _counts(default) == _counts(explicit)


def test_analytics_route_declares_and_passes_india_only():
    src = ROUTER_SRC.read_text(encoding="utf-8")
    start = src.index('@router.get("/analytics"')
    end = src.index("@router.get(", start + 1)
    block = src[start:end]
    assert re.search(r"india_only\s*:\s*bool\s*=\s*Query\(", block)
    assert re.search(r"get_radar_overview_stats\([^)]*india_only", block)
