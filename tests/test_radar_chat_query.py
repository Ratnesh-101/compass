"""DB-free tests for the chat internship query: keyword extraction, fallback and India widening."""
from __future__ import annotations

import pytest

import backend.routers.radar as radar_router
from backend.models_radar import OpportunityOut, OpportunityStatus
from backend.skills.handlers import radar as radar_handler
from backend.skills.handlers.radar import extract_search_keywords, handle_query_internship_radar

LONG_QUERY = "Find internships for a 3rd-year B.Tech student in India"


def make_item(idx: int, company: str, role: str, category: str | None = None, description: str | None = None):
    return OpportunityOut(
        id=idx,
        company_name=company,
        normalized_company=company.lower(),
        role_title=role,
        category=category,
        description=description,
        canonical_url=f"https://example.com/{idx}",
        current_status=OpportunityStatus.OPEN_CONFIRMED,
    )


def three_items():
    return [
        make_item(1, "Acme", "Software Intern", "swe"),
        make_item(2, "Globex", "Data Intern", "data"),
        make_item(3, "Initech", "Cloud Intern", "cloud"),
    ]


@pytest.fixture
def patch_data(monkeypatch):
    calls: list[bool] = []

    def install(items=None, worldwide_items=None):
        async def fake_profile(*_a, **_k):
            return None

        async def fake_recommended(*_a, **kwargs):
            india_only = kwargs.get("india_only", True)
            calls.append(bool(india_only))
            if worldwide_items is not None:
                return list(items or []) if india_only else list(worldwide_items)
            return list(items or [])

        monkeypatch.setattr(radar_handler, "get_user_opportunity_profile", fake_profile)
        monkeypatch.setattr(radar_router, "recommended_for_user", fake_recommended)
        return calls

    return install


# ---- extract_search_keywords ----

def test_keywords_all_filler_is_empty():
    assert extract_search_keywords(LONG_QUERY) == []


def test_keywords_backend_kept():
    assert "backend" in extract_search_keywords("find me backend internships in India")


def test_keywords_ai_ml_query_drops_filler():
    kws = extract_search_keywords("AI ML internship for CSE students")
    for filler in ("internship", "for", "students", "student", "internships"):
        assert filler not in kws
    assert 1 <= len(kws) <= 4


def test_keywords_max_four_distinct():
    kws = extract_search_keywords("rust golang python java kotlin swift scala rust")
    assert len(kws) <= 4
    assert len(set(kws)) == len(kws)


def test_keywords_punctuation_and_case():
    kws = extract_search_keywords("FIND Python, Django!!! internships?")
    assert "python" in kws
    assert all(k == k.lower() and k.isalnum() or "-" in k or "+" in k or "#" in k for k in kws)


def test_keywords_empty():
    assert extract_search_keywords("") == []


# ---- handler ----

@pytest.mark.asyncio
async def test_handler_generic_sentence_returns_all_without_not_found(patch_data):
    patch_data(three_items())
    res = await handle_query_internship_radar({"query": LONG_QUERY})
    assert res["data"]["count"] == 3
    for name in ("Acme", "Globex", "Initech"):
        assert name in res["summary"]
    assert "could not find" not in res["summary"].lower()


@pytest.mark.asyncio
async def test_handler_unmatched_keywords_fall_back_honestly(patch_data):
    patch_data(three_items())
    res = await handle_query_internship_radar({"query": "rust embedded internships"})
    assert res["data"]["count"] == 3
    assert "Acme" in res["summary"]
    low = res["summary"].lower()
    assert "rust" in low
    assert "not find" in low or "did not find" in low or "no roles" in low


@pytest.mark.asyncio
async def test_handler_keyword_match_only_when_found(patch_data):
    items = [
        make_item(1, "Acme", "Java Intern", "swe"),
        make_item(2, "Globex", "Python Developer Intern", "swe"),
    ]
    patch_data(items)
    res = await handle_query_internship_radar({"query": "python internships"})
    assert res["data"]["opportunities"][0]["company"] == "Globex"
    assert res["data"]["count"] == 1
    assert "Globex" in res["summary"]
    assert "Acme" not in res["summary"]


@pytest.mark.asyncio
async def test_handler_category_inferred_from_query(patch_data):
    items = [
        make_item(1, "Acme", "Software Intern", "swe"),
        make_item(2, "Globex", "Machine Intern", "ai_ml"),
    ]
    patch_data(items)
    res = await handle_query_internship_radar({"query": "AI ML internship for CSE students", "category": "general"})
    assert res["data"]["opportunities"][0]["company"] == "Globex"


@pytest.mark.asyncio
async def test_handler_widens_to_worldwide(patch_data):
    calls = patch_data(items=[], worldwide_items=three_items())
    res = await handle_query_internship_radar({"query": "internships", "india_only": True})
    assert res["summary"].startswith("I did not find India-based matches")
    assert res["data"]["widened_to_worldwide"] is True
    assert res["data"]["count"] == 3
    assert calls[:2] == [True, False]


@pytest.mark.asyncio
async def test_handler_both_empty(patch_data):
    patch_data(items=[], worldwide_items=[])
    res = await handle_query_internship_radar({"query": "internships", "india_only": True})
    assert "could not find an open internship" in res["summary"]
    assert res["data"]["count"] == 0


@pytest.mark.asyncio
async def test_handler_result_shape(patch_data):
    patch_data(three_items())
    res = await handle_query_internship_radar({"query": LONG_QUERY})
    assert {"success", "data", "summary", "response"} <= set(res)
    assert res["success"] is True
    assert {"count", "opportunities", "see_all_hint"} <= set(res["data"])
    assert isinstance(res["data"]["opportunities"], list)
