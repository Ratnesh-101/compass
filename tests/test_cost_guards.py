"""
Tests for Cost Guards (Commit 2b):
1. /company-intel and /feasibility per-identity rate limit + daily cap:
   - company-intel: 10/day for guests, admin exempt.
   - feasibility: 5/day for guests, admin exempt.
   - 429 status + Retry-After header + stable code.
2. 24h cache per opportunity (cache hit = zero Tavily calls).
3. Separate Tavily sub-budget (30 credits/day) that cannot starve verification.
4. Non-ASCII Authorization header must not 500 (safe bytes compare).
5. simulate_ats_parsing output labeled honestly as "estimate".
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient

from backend.dependencies import generate_guest_token
from backend.models_radar import OpportunityOut
from backend.services.rate_limiter import (
    _DAILY_ACTION_USAGE,
    _MEM_BUCKETS,
    check_identity_daily_cap,
    safe_token_compare,
)
from backend.services.winning_features import (
    _COMPANY_INTEL_CACHE,
    _daily_intel_tavily_usage,
    check_intel_tavily_budget,
    generate_company_intel_brief,
    get_cached_company_intel,
    simulate_ats_parsing,
    store_cached_company_intel,
)


@pytest.fixture(autouse=True)
def reset_cost_guards():
    """Clear memory caches and rate limit buckets before and after each test."""
    _COMPANY_INTEL_CACHE.clear()
    _daily_intel_tavily_usage.clear()
    _DAILY_ACTION_USAGE.clear()
    _MEM_BUCKETS.clear()
    yield
    _COMPANY_INTEL_CACHE.clear()
    _daily_intel_tavily_usage.clear()
    _DAILY_ACTION_USAGE.clear()
    _MEM_BUCKETS.clear()


# --- 1. NON-ASCII AUTHORIZATION HEADER SAFETY ---

def test_non_ascii_authorization_header_safety():
    """Malformed non-ASCII Authorization header must not crash with 500."""
    malformed_header = "Bearer \x80\xff\xfe\xca\xfe"
    valid_secret = "compass-prod-secret-2026"
    assert safe_token_compare(malformed_header, valid_secret) is False
    assert safe_token_compare(valid_secret, valid_secret) is True
    assert safe_token_compare("", valid_secret) is False
    assert safe_token_compare(None, valid_secret) is False


# --- 2. 24H COMPANY INTEL CACHE (ZERO TAVILY CALLS ON HIT) ---

@pytest.mark.asyncio
async def test_company_intel_24h_cache_zero_tavily_calls():
    """Company intel caches results for 24h; cache hit must make zero Tavily calls."""
    opp = OpportunityOut(
        id=42,
        company_name="Nebius",
        normalized_company="nebius",
        role_title="AI Engineer",
        category="ai_ml",
        location="San Francisco, CA",
        canonical_url="https://nebius.com/careers/1",
        current_status="open_confirmed",
        source="devpost",
    )

    tavily_calls = [0]

    async def fake_deep_research(*args, **kwargs):
        tavily_calls[0] += 1
        return {
            "citations": [
                {"title": "Nebius GPU Cloud", "snippet": "Scaling GPU clusters for AI workloads."},
                {"title": "Nebius Funding", "snippet": "Announced new infrastructure expansion."},
            ]
        }

    mock_summary = {
        "status": "ready",
        "summary": "Nebius scales GPU clusters for AI workloads.",
        "priorities": [{"point": "Scaling GPU clusters for AI workloads.", "source": 1}],
        "role_context": [],
        "challenges": [{"point": "Scaling GPU clusters for AI workloads.", "source": 1}],
        "talking_points": [],
        "confidence": "high",
    }

    with patch("backend.services.tavily_research.execute_deep_research", side_effect=fake_deep_research), \
         patch("backend.services.winning_features._summarize_with_model", AsyncMock(return_value=mock_summary)):
        # 1st call: Cache miss -> calls Tavily
        res1 = await generate_company_intel_brief(opp)
        assert tavily_calls[0] == 1
        assert res1["company"] == "Nebius"
        assert len(res1["technical_pain_points"]) > 0

        # 2nd call: Cache hit -> ZERO Tavily calls
        res2 = await generate_company_intel_brief(opp)
        assert tavily_calls[0] == 1  # Still 1, no new external calls!
        assert res2["company"] == "Nebius"
        assert res2 == res1


# --- 3. SEPARATE TAVILY SUB-BUDGET (30 CREDITS/DAY) ---

def test_separate_tavily_intel_sub_budget():
    """Company intel has a dedicated 30 credit/day sub-budget that fails closed and cannot starve verification."""
    from backend.services.budgets import check_run_limits, MAX_RUN_TAVILY_CREDITS

    # Intel consumes its 30 credits
    for _ in range(30):
        assert check_intel_tavily_budget(1) is True

    # 31st intel credit fails closed
    assert check_intel_tavily_budget(1) is False

    # Verification budget is completely untouched and still allows runs!
    # Verification limit check passes without error
    check_run_limits(model_calls=5, tool_calls=5, tavily_credits=MAX_RUN_TAVILY_CREDITS)


# --- 4. IDENTITY DAILY CAPS (10/DAY INTEL, 5/DAY FEASIBILITY) ---

def test_identity_daily_cap_and_admin_exempt():
    """Guests are capped at 10/day for intel and 5/day for feasibility; admin is exempt."""
    guest_id = "guest_test_abc"

    # Intel cap for guest: 10 allowed, 11th rejected with retry-after
    for _ in range(10):
        allowed, retry_after = check_identity_daily_cap(guest_id, "company_intel", cap=10)
        assert allowed is True
        assert retry_after == 0

    allowed_11, retry_after = check_identity_daily_cap(guest_id, "company_intel", cap=10)
    assert allowed_11 is False
    assert retry_after > 0

    # Admin is exempt
    for _ in range(25):
        allowed, retry_after = check_identity_daily_cap("admin_identity", "company_intel", cap=10, is_admin=True)
        assert allowed is True
        assert retry_after == 0

    # Feasibility cap for guest: 5 allowed, 6th rejected
    for _ in range(5):
        allowed, retry_after = check_identity_daily_cap(guest_id, "feasibility", cap=5)
        assert allowed is True
    allowed_6, retry_after = check_identity_daily_cap(guest_id, "feasibility", cap=5)
    assert allowed_6 is False
    assert retry_after > 0


# --- 5. ENDPOINT INTEGRATION: /company-intel & /feasibility GUARDS ---

@pytest.mark.asyncio
async def test_company_intel_endpoint_rate_limit_and_cap(client: AsyncClient, monkeypatch):
    """Test /opportunities/{id}/company-intel enforces guest daily cap (10) and returns 429 with Retry-After."""
    from backend.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "AUTH_TOKEN", "compass-test-auth-token")

    _, guest_token = generate_guest_token()
    headers = {"x-guest-token": guest_token}

    mock_opp = {
        "id": 99,
        "company_name": "TestCo",
        "normalized_company": "testco",
        "role_title": "SWE Intern",
        "category": "software_engineering",
        "location": "Remote",
        "canonical_url": "https://testco.com/careers/99",
        "current_status": "open_confirmed",
        "source": "devpost",
    }

    with patch("backend.routers.career.get_opportunity_by_id", AsyncMock(return_value=OpportunityOut(**mock_opp))), \
         patch("backend.services.winning_features.tavily_research.execute_deep_research", AsyncMock(return_value={"citations": []})):

        # 10 successful requests (or cached hits)
        for i in range(10):
            resp = await client.get("/opportunities/99/company-intel", headers=headers)
            assert resp.status_code == 200, f"Request {i+1} failed with status {resp.status_code}: {resp.text}"

        # 11th request must return 429 with stable code and Retry-After
        resp_11 = await client.get("/opportunities/99/company-intel", headers=headers)
        assert resp_11.status_code == 429
        assert "Retry-After" in resp_11.headers
        data = resp_11.json()
        assert "daily_cap_exceeded" in str(data) or "rate_limit_exceeded" in str(data)

        # Admin request with Authorization header bypasses cap
        admin_headers = {"Authorization": "Bearer compass-test-auth-token"}
        resp_admin = await client.get("/opportunities/99/company-intel", headers=admin_headers)
        assert resp_admin.status_code == 200


@pytest.mark.asyncio
async def test_feasibility_endpoint_rate_limit_and_cap(client: AsyncClient, monkeypatch):
    """Test /api/agent/feasibility enforces guest daily cap (5) and returns 429."""
    from backend.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "AUTH_TOKEN", "compass-test-auth-token")

    _, guest_token = generate_guest_token()
    headers = {"x-guest-token": guest_token}

    mock_plan = {
        "days": 5,
        "hours_per_day": 4.0,
        "status": "feasible",
        "triaged_tasks": [],
    }

    async def fake_stream(*args, **kwargs):
        yield {"type": "plan", "plan": mock_plan}

    with patch("backend.agents.feasibility.run_feasibility_review", side_effect=fake_stream), \
         patch("backend.routers.agent.get_pool", AsyncMock(return_value=MagicMock())):

        # 5 successful requests
        for i in range(5):
            resp = await client.post("/api/agent/feasibility", headers=headers, json={"days": 5, "hours_per_day": 4.0})
            assert resp.status_code == 200, f"Request {i+1} failed with status {resp.status_code}: {resp.text}"

        # 6th request must return 429
        resp_6 = await client.post("/api/agent/feasibility", headers=headers, json={"days": 5, "hours_per_day": 4.0})
        assert resp_6.status_code == 429
        assert "Retry-After" in resp_6.headers
        data = resp_6.json()
        assert "daily_cap_exceeded" in str(data) or "rate_limit_exceeded" in str(data)

        # Admin bypasses cap
        admin_headers = {"Authorization": "Bearer compass-test-auth-token"}
        resp_admin = await client.post("/api/agent/feasibility", headers=admin_headers, json={"days": 5, "hours_per_day": 4.0})
        assert resp_admin.status_code == 200


# --- 6. SIMULATE ATS PARSING HONEST ESTIMATE ---

def test_simulate_ats_parsing_labeled_estimate():
    """simulate_ats_parsing must output an honest 'estimate' label."""
    res = simulate_ats_parsing("Experience: Software Developer")
    assert res.get("is_estimate") is True
    assert res.get("label") == "estimate"
