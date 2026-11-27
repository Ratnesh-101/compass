"""Open-list pagination: offset applies after filtering and ranking. No network, no database."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.memory import radar
from backend.models_radar import EligibilityClassification
from backend.services import radar_quality

ROOT = Path(__file__).resolve().parent.parent


def _items():
    ok = EligibilityClassification.ELIGIBLE
    rows = [SimpleNamespace(id="drop", refine_drop=True, cls=ok)]
    rows.append(SimpleNamespace(id="inel", refine_drop=False, cls=EligibilityClassification.INELIGIBLE))
    # Deliberately unsorted ids; the rank key sorts them.
    for i in (5, 2, 7, 1, 6, 3, 4):
        rows.append(SimpleNamespace(id=f"r{i}", refine_drop=False, cls=ok))
    return rows


@pytest.fixture
def patched(monkeypatch):
    items = _items()

    async def fake_get_all(**kw):
        return items[: kw["page_size"]], len(items)

    monkeypatch.setattr(radar, "get_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(radar, "get_all_opportunities", fake_get_all)

    def enrich(item, _profile):
        item.eligibility_classification = item.cls
        return item

    monkeypatch.setattr(radar, "_enrich_opportunity", enrich)
    monkeypatch.setattr(
        radar_quality, "refine_listings",
        lambda raw, _c, country_filter=True: [i for i in raw if not i.refine_drop],
    )
    monkeypatch.setattr(radar_quality, "profile_country_of", lambda _p: "IN")
    monkeypatch.setattr(radar_quality, "recommendation_rank_key", lambda o, _p, _c: o.id)


async def _page(limit, offset):
    out = await radar.list_open_opportunities(
        "u", limit=limit, offset=offset, profile=SimpleNamespace()
    )
    return [o.id for o in out]


@pytest.mark.asyncio
async def test_pages_follow_ranked_order(patched):
    assert await _page(3, 0) == ["r1", "r2", "r3"]
    assert await _page(3, 3) == ["r4", "r5", "r6"]
    assert await _page(3, 6) == ["r7"]
    assert await _page(3, 7) == []


@pytest.mark.asyncio
async def test_union_of_pages_equals_full_list_without_duplicates(patched):
    full = await _page(None, 0)
    assert len(full) == 7
    union = []
    for off in (0, 3, 6, 9):
        union += await _page(3, off)
    assert union == full
    assert len(set(union)) == len(union)


@pytest.mark.asyncio
async def test_default_offset_is_zero(patched):
    out = await radar.list_open_opportunities("u", limit=2, profile=SimpleNamespace())
    assert [o.id for o in out] == ["r1", "r2"]


def test_route_query_bounds_allow_offset():
    src = (ROOT / "backend" / "routers" / "radar.py").read_text(encoding="utf-8")
    block = src[src.index('@router.get("/open"'):src.index('@router.get("/upcoming"')]
    assert re.search(r"offset: int = Query\(0, ge=0\)", block)
    assert "limit: int = Query(300, ge=1, le=500)" in block
    assert "X-Total-Count" in block
