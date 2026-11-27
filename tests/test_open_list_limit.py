"""list_open_opportunities truncates after filtering. No network, no database."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.memory import radar
from backend.models_radar import EligibilityClassification
from backend.services import radar_quality


def _items():
    # r1/r3 are dropped by refinement, e2/e4 by eligibility; 5 candidates -> 1 eligible
    # after placing ineligible ones first, so a page cut before filtering loses rows.
    return [
        SimpleNamespace(id="bad1", refine_drop=True, cls=EligibilityClassification.ELIGIBLE),
        SimpleNamespace(id="bad2", refine_drop=False, cls=EligibilityClassification.INELIGIBLE),
        SimpleNamespace(id="ok1", refine_drop=False, cls=EligibilityClassification.ELIGIBLE),
        SimpleNamespace(id="ok2", refine_drop=False, cls=EligibilityClassification.ELIGIBLE),
        SimpleNamespace(id="ok3", refine_drop=False, cls=EligibilityClassification.ELIGIBLE),
    ]


@pytest.fixture
def patched(monkeypatch):
    items = _items()
    calls = {}

    async def fake_get_all(**kw):
        calls.update(kw)
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
    return calls


@pytest.mark.asyncio
async def test_limit_applies_after_filtering(patched):
    out = await radar.list_open_opportunities("u", limit=3, profile=SimpleNamespace())
    assert [o.id for o in out] == ["ok1", "ok2", "ok3"]
    assert patched["page_size"] == 600


@pytest.mark.asyncio
async def test_no_limit_returns_all_eligible(patched):
    out = await radar.list_open_opportunities("u", limit=None, profile=SimpleNamespace())
    assert [o.id for o in out] == ["ok1", "ok2", "ok3"]
    assert patched["page_size"] == 600


@pytest.mark.asyncio
async def test_candidate_page_capped_at_1000(patched):
    await radar.list_open_opportunities("u", limit=500, profile=SimpleNamespace())
    assert patched["page_size"] == 1000
