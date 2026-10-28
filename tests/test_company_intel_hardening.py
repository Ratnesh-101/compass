"""
Follow-up hardening for the company intel brief: citation URLs must be http(s) links, and the daily
Tavily intel budget is charged for every search sub-query that actually runs.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.models_radar import OpportunityOut
from backend.services import winning_features
from backend.services.winning_features import (
    _COMPANY_INTEL_CACHE,
    _LAST_INTEL_REFRESH,
    clean_search_sources,
    generate_company_intel_brief,
)


@pytest.fixture(autouse=True)
def clear_intel_state():
    _COMPANY_INTEL_CACHE.clear()
    _LAST_INTEL_REFRESH.clear()
    yield
    _COMPANY_INTEL_CACHE.clear()
    _LAST_INTEL_REFRESH.clear()


def _opp(company="1Password", opp_id=202):
    return OpportunityOut(
        id=opp_id,
        company_name=company,
        normalized_company=company.lower(),
        role_title="Backend Engineer",
        category="software_engineering",
        location="Remote, Canada",
        canonical_url="https://1password.com/careers/202",
        current_status="open_confirmed",
        source="devpost",
    )


def _citation(url):
    return {
        "title": "1Password Security Model",
        "snippet": "1Password uses AES-256 bit encryption and dual-key architecture for credential management.",
        "url": url,
        "domain": "1password.com",
    }


@pytest.mark.parametrize(
    "bad_url",
    ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<script>1</script>", "//evil.example/x", "not a url", ""],
)
def test_non_http_citation_urls_are_never_linked(bad_url):
    cleaned = clean_search_sources([_citation(bad_url)], company_name="1Password")
    assert cleaned, "the source text is still useful, only the link must go"
    assert all(s["url"] == "" for s in cleaned)


def test_http_and_https_citation_urls_are_kept():
    cleaned = clean_search_sources(
        [_citation("https://1password.com/security"), _citation("http://1password.com/legacy-notes")],
        company_name="1Password",
    )
    assert {s["url"] for s in cleaned} >= {"https://1password.com/security"}


@pytest.mark.asyncio
async def test_intel_budget_is_charged_per_search_subquery():
    charged = []

    def record(cost=1):
        charged.append(cost)
        return True

    research = AsyncMock(return_value={"citations": []})
    with patch.object(winning_features, "check_intel_tavily_budget", record), \
         patch.object(winning_features.tavily_research, "execute_deep_research", research):
        await generate_company_intel_brief(_opp())

    expected = len(
        winning_features.tavily_research.decompose_query(
            "Current strategic goals, recent technical milestones, and core engineering "
            "challenges for 1Password specifically regarding Backend Engineer roles in Remote, Canada.",
            max_subqueries=winning_features.INTEL_MAX_SUBQUERIES,
        )
    )
    assert expected >= 1
    assert charged == [expected]
    assert research.await_args.kwargs["max_subqueries"] == winning_features.INTEL_MAX_SUBQUERIES


@pytest.mark.asyncio
async def test_intel_request_is_refused_when_the_remaining_budget_cannot_cover_the_searches():
    winning_features._daily_intel_tavily_usage.clear()
    from datetime import date

    winning_features._daily_intel_tavily_usage[date.today().isoformat()] = winning_features.MAX_DAILY_INTEL_TAVILY_CREDITS - 1
    research = AsyncMock(return_value={"citations": []})
    topic_queries = len(
        winning_features.tavily_research.decompose_query(
            "Current strategic goals, recent technical milestones, and core engineering "
            "challenges for 1Password specifically regarding Backend Engineer roles in Remote, Canada.",
            max_subqueries=winning_features.INTEL_MAX_SUBQUERIES,
        )
    )
    assert topic_queries == 3
    try:
        with patch.object(winning_features.tavily_research, "execute_deep_research", research):
            with pytest.raises(HTTPException) as excinfo:
                await generate_company_intel_brief(_opp(opp_id=303))
            assert excinfo.value.status_code == 429
            research.assert_not_awaited()
    finally:
        winning_features._daily_intel_tavily_usage.clear()
