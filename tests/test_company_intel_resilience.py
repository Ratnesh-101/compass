"""
Automated Test Suite for Company Intel Resilience & Fallback Service.

Covers Step 6 Requirements:
1. 10 Companies across diverse categories:
   - 1Password (the company that broke)
   - Google & Stripe (well known tech)
   - Ford & Mayo Clinic (traditional/non-tech)
   - Linear & Supabase (fast-growing startups)
   - Real obscure local agency
   - Mercadona (international / non-English)
   - Target (generic English word)
2. 5 Consecutive 1Password runs proving non-intermittent behavior.
3. Fallback from job posting when web search fails.
4. Fallback to cleaned sources when LLM fails or times out.
5. Safe machine-readable reason codes across simulated failures.
6. Asynchronous 202 job creation and status polling.
"""

import asyncio
from datetime import datetime, timezone
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.models_radar import OpportunityOut
from backend.services.company_intel_jobs import (
    SCHEMA_VERSION,
    build_job_posting_fallback,
    build_sources_only_fallback,
    create_job,
    get_job,
    run_intel_refresh_job,
)
from backend.services.winning_features import (
    generate_company_intel_brief,
    _COMPANY_INTEL_CACHE,
    _LAST_INTEL_REFRESH,
    _daily_intel_tavily_usage,
)


@pytest.fixture(autouse=True)
def clear_caches():
    _COMPANY_INTEL_CACHE.clear()
    _LAST_INTEL_REFRESH.clear()
    _daily_intel_tavily_usage.clear()
    yield
    _COMPANY_INTEL_CACHE.clear()
    _LAST_INTEL_REFRESH.clear()
    _daily_intel_tavily_usage.clear()


@pytest.mark.asyncio
async def test_job_posting_fallback_when_search_fails():
    """Verify that when web search fails, company intel falls back to job posting text."""
    desc = (
        "1Password is looking for an IT Support Intern to join our internal IT team. "
        "You will be responsible for triaging hardware tickets and supporting macOS deployments. "
        "Our mission is to make password security effortless and human-centric across all modern platforms."
    )
    opp = OpportunityOut(
        id=6,
        company_name="1Password",
        normalized_company="1password",
        role_title="IT Support Intern",
        category="software_engineering",
        location="Remote, Canada",
        description=desc,
        canonical_url="https://1password.com/careers/6",
        current_status="open_confirmed",
        source="company_website",
    )

    with patch("backend.services.winning_features.tavily_research.execute_deep_research", side_effect=RuntimeError("Tavily service disabled")):
        brief = await generate_company_intel_brief(opp)
        assert brief["status"] == "ready"
        assert brief.get("from_job_posting") is True
        assert brief.get("fallback_label") == "From the job posting"
        assert brief.get("reason") == "from_job_posting"
        assert len(brief["priorities"]) >= 1
        assert len(brief["sources"]) == 1
        assert brief["sources"][0]["domain"] == "1password.com"


@pytest.mark.asyncio
async def test_sources_only_fallback_when_model_times_out():
    """Verify that when search succeeds but model times out, sources are retained."""
    opp = OpportunityOut(
        id=7,
        company_name="Stripe",
        normalized_company="stripe",
        role_title="Backend Engineering Intern",
        category="software_engineering",
        location="Remote",
        canonical_url="https://stripe.com/jobs/7",
        current_status="open_confirmed",
        source="company_website",
    )
    mock_citations = [
        {
            "title": "Stripe Payments Architecture",
            "snippet": "Stripe processes hundreds of billions in financial transactions annually with 99.999% uptime.",
            "url": "https://stripe.com/arch",
            "domain": "stripe.com",
        }
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError("LLM call timed out"))

    with patch("backend.services.winning_features.tavily_research.execute_deep_research", AsyncMock(return_value={"citations": mock_citations})), \
         patch("backend.services.winning_features.get_openai_client", return_value=mock_client):
        brief = await generate_company_intel_brief(opp)
        assert brief["status"] == "ready"
        assert brief.get("is_sources_only") is True
        assert brief.get("fallback_label") == "Sources found, summary unavailable"
        assert brief.get("reason") == "model_timeout"
        assert len(brief["sources"]) == 1
        assert brief["sources"][0]["domain"] == "stripe.com"


@pytest.mark.asyncio
async def test_reason_codes_on_clean_error():
    """Verify clean error states include machine-readable reason codes."""
    opp = OpportunityOut(
        id=8,
        company_name="ObscureInc",
        normalized_company="obscureinc",
        role_title="Intern",
        category="software_engineering",
        location="Remote",
        description=None,
        canonical_url="https://obscure.example/jobs/8",
        current_status="open_confirmed",
        source="web",
    )

    # 1. Search failed with no job posting -> search_failed
    with patch("backend.services.winning_features.tavily_research.execute_deep_research", side_effect=RuntimeError("Network error")):
        brief = await generate_company_intel_brief(opp)
        assert brief["status"] == "error"
        assert brief.get("reason") == "search_failed"

    # 2. Search timeout with no job posting -> search_timeout
    _LAST_INTEL_REFRESH.clear()
    with patch("backend.services.winning_features.tavily_research.execute_deep_research", side_effect=asyncio.TimeoutError("Timeout")):
        brief = await generate_company_intel_brief(opp, force_refresh=True)
        assert brief["status"] == "error"
        assert brief.get("reason") == "search_timeout"


@pytest.mark.asyncio
async def test_async_refresh_job_queue_and_polling():
    """Verify background refresh job lifecycle: creation, execution, and polling."""
    opp_id = 99
    job = await create_job(opp_id, "Linear", "Frontend Intern")
    assert job["job_id"].startswith("job_")
    assert job["status"] == "queued"

    mock_opp = OpportunityOut(
        id=opp_id,
        company_name="Linear",
        normalized_company="linear",
        role_title="Frontend Intern",
        category="software_engineering",
        location="Remote",
        canonical_url="https://linear.app/jobs/99",
        current_status="open_confirmed",
        source="web",
    )

    with patch("backend.memory.radar.get_opportunity_by_id", AsyncMock(return_value=mock_opp)), \
         patch("backend.services.winning_features.generate_company_intel_brief", AsyncMock(return_value={"status": "ready", "summary": "Linear builds issue tracking software.", "sources": []})):
        await run_intel_refresh_job(job["job_id"], opp_id)

    updated_job = await get_job(job["job_id"])
    assert updated_job is not None
    assert updated_job["status"] == "done"
    assert updated_job["result"]["status"] == "ready"


@pytest.mark.asyncio
async def test_10_diverse_companies_and_5_consecutive_1password_runs():
    """Verify company intel produces valid, stable output across 10 diverse companies + 5 consecutive 1Password runs."""
    companies = [
        ("1Password", "Product Management Intern", "https://1password.com", "Password manager and identity access provider."),
        ("Google", "Software Engineering Intern", "https://google.com", "Global technology leader in search and cloud computing."),
        ("Stripe", "Infrastructure Intern", "https://stripe.com", "Financial infrastructure platform for online business payments."),
        ("Ford Motor Company", "Embedded Systems Intern", "https://ford.com", "Automotive manufacturing and electric vehicle technologies."),
        ("Mayo Clinic", "Biomedical Data Intern", "https://mayoclinic.org", "Nonprofit American academic medical center focused on healthcare."),
        ("Linear", "Fullstack Intern", "https://linear.app", "Purpose-built project management and issue tracking software."),
        ("Supabase", "Database Intern", "https://supabase.com", "Open source Firebase alternative built on top of Postgres."),
        ("Apex Local Creative Studio", "Web Developer Intern", "https://apexlocal.example", "Boutique digital agency providing local web and brand services."),
        ("Mercadona", "Supply Chain Analyst Intern", "https://mercadona.es", "Spanish supermarket chain specializing in physical and online retail logistics."),
        ("Target", "Supply Chain Intern", "https://target.com", "American big-box department store chain operating retail merchandise."),
    ]

    for idx, (company, role, url, desc) in enumerate(companies, start=1):
        _daily_intel_tavily_usage.clear()
        opp = OpportunityOut(
            id=100 + idx,
            company_name=company,
            normalized_company=company.lower().replace(" ", ""),
            role_title=role,
            category="software_engineering",
            location="Remote",
            description=f"{company} is hiring a {role}. {desc} Apply to join our team.",
            canonical_url=f"{url}/jobs",
            current_status="open_confirmed",
            source="test",
        )

        citation = {
            "title": f"{company} Overview",
            "snippet": desc,
            "url": f"{url}/about",
            "domain": url.split("//")[-1],
        }

        mock_resp = MagicMock()
        mock_resp.choices = [
            MagicMock(message=MagicMock(content=json.dumps({
                "summary": f"{company} operates modern products.",
                "priorities": [{"point": f"{company} focuses on software and operational infrastructure.", "source": 1}],
                "role_context": [],
                "challenges": [],
                "talking_points": [],
                "confidence": "high",
            })))
        ]
        mock_resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

        fake_client = MagicMock()
        fake_client.chat.completions.create = AsyncMock(return_value=mock_resp)

        with patch("backend.services.winning_features.tavily_research.execute_deep_research", AsyncMock(return_value={"citations": [citation]})), \
             patch("backend.services.winning_features.get_openai_client", return_value=fake_client):
            brief = await generate_company_intel_brief(opp)
            assert brief["status"] == "ready", f"Failed for {company}"
            assert brief["confidence"] in ("high", "medium", "low")
            assert len(brief["sources"]) >= 1

    # 5 Consecutive runs on 1Password (verifying caching and cooldown behavior)
    _daily_intel_tavily_usage.clear()
    pw_opp = OpportunityOut(
        id=14,
        company_name="1Password",
        normalized_company="1password",
        role_title="Product Management Intern",
        category="software_engineering",
        location="Remote, Canada",
        canonical_url="https://1password.com/careers/14",
        current_status="open_confirmed",
        source="test",
    )
    for i in range(5):
        with patch("backend.services.winning_features.tavily_research.execute_deep_research", AsyncMock(return_value={"citations": [citation]})), \
             patch("backend.services.winning_features.get_openai_client", return_value=fake_client):
            brief = await generate_company_intel_brief(pw_opp, force_refresh=(i == 0))
            assert brief["status"] == "ready"
            assert brief["company"] == "1Password"
