"""
Regression tests for the opportunity verifier, the verify endpoint and JobSpy persistence.

Each test fails against the pre-fix code, where lookalike domains counted as official, any
"Apply now" page on any domain became OPEN_CONFIRMED, redirects were followed unchecked, the verify
endpoint was anonymous and JobSpy listings were stored as verified.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.models_radar import OpportunityStatus
from backend.routers.auth import create_session
from backend.services.radar_verifier import is_official_domain, verify_opportunity_status

APPLY_PAGE = "<html><body><h1>Software Intern</h1><a>Apply now</a></body></html>"


FETCH = "backend.services.radar_verifier.safe_http_get_with_url"


def _page(status_code=200, text=APPLY_PAGE, final_url="https://example.com/final"):
    """Result tuple of safe_http_get_with_url: (status, text, headers, final_url)."""
    return (status_code, text, {}, final_url)


def _echo_page(status_code=200, text=APPLY_PAGE):
    """Fetch stub that lands on the URL it was asked for (no redirect)."""
    async def fetch(url, *args, **kwargs):
        return (status_code, text, {}, url)
    return fetch


# ---------------------------------------------------------------------------
# Domain matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io.evil.com/acme/jobs/123",
        "https://evil.com/boards.greenhouse.io/acme/jobs/123",
        "https://iisc.ac.in.evil.com/internships",
        "https://evil.edu.attacker.com/apply",
        "https://notgreenhouse.io/acme/jobs/123",
        "https://lever.co.phish.net/acme/abcdef12",
    ],
)
def test_lookalike_domains_are_not_official(url):
    assert not is_official_domain(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/123",
        "https://jobs.lever.co/acme/abcdef12-3456",
        "https://www.csa.iisc.ac.in/",
        "https://cs.stanford.edu/internships",
        "https://summerofcode.withgoogle.com/",
        "https://boards.greenhouse.io:443/acme/jobs/123",
    ],
)
def test_real_official_domains_still_match(url):
    assert is_official_domain(url)


# ---------------------------------------------------------------------------
# Verification decisions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_button_on_an_unrecognized_domain_is_not_open_confirmed():
    with patch("backend.services.radar_verifier.tavily_available", return_value=False), \
         patch(FETCH, side_effect=_echo_page()):
        status, evidence, _ = await verify_opportunity_status(
            "https://random-blog.example.com/posts/1", OpportunityStatus.DISCOVERED
        )
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert "not on a recognized official domain" in evidence


@pytest.mark.asyncio
async def test_apply_button_on_an_official_specific_posting_is_open_confirmed():
    with patch("backend.services.radar_verifier.tavily_available", return_value=False), \
         patch(FETCH, side_effect=_echo_page()):
        status, _, _ = await verify_opportunity_status(
            "https://boards.greenhouse.io/acme/jobs/12345", OpportunityStatus.DISCOVERED
        )
    assert status == OpportunityStatus.OPEN_CONFIRMED


@pytest.mark.asyncio
async def test_redirect_to_a_generic_page_is_judged_on_the_landing_page():
    landed = _page(200, APPLY_PAGE, final_url="https://boards.greenhouse.io/acme")
    with patch("backend.services.radar_verifier.tavily_available", return_value=False), \
         patch(FETCH, new_callable=AsyncMock, return_value=landed):
        status, _, _ = await verify_opportunity_status(
            "https://boards.greenhouse.io/acme/jobs/12345", OpportunityStatus.DISCOVERED
        )
    assert status == OpportunityStatus.NEEDS_VERIFICATION


@pytest.mark.asyncio
async def test_redirect_to_an_internal_address_is_blocked():
    mock_get = AsyncMock(side_effect=ValueError(
        "SSRF redirect blocked: Redirect destination rejected: Access to non-global IP address '169.254.169.254' is forbidden."
    ))
    with patch("backend.services.radar_verifier.tavily_available", return_value=False), \
         patch(FETCH, mock_get):
        status, evidence, _ = await verify_opportunity_status(
            "https://boards.greenhouse.io/acme/jobs/12345", OpportunityStatus.NEEDS_VERIFICATION
        )
    assert mock_get.await_count == 1
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert "stopped" in evidence.lower()


@pytest.mark.asyncio
async def test_internal_application_url_is_never_fetched():
    mock_get = AsyncMock(return_value=_page())
    with patch("backend.services.radar_verifier.tavily_available", return_value=False), \
         patch(FETCH, mock_get):
        status, evidence, _ = await verify_opportunity_status(
            "http://169.254.169.254/latest/meta-data", OpportunityStatus.NEEDS_VERIFICATION
        )
    assert mock_get.await_count == 0
    assert status == OpportunityStatus.NEEDS_VERIFICATION
    assert "not fetched" in evidence


@pytest.mark.asyncio
async def test_connection_failure_still_retains_status():
    with patch("backend.services.radar_verifier.tavily_available", return_value=False), \
         patch(FETCH, new_callable=AsyncMock, side_effect=httpx.ConnectTimeout("timed out")):
        status, _, _ = await verify_opportunity_status(
            "https://boards.greenhouse.io/acme/jobs/12345", OpportunityStatus.NEEDS_VERIFICATION
        )
    assert status == OpportunityStatus.NEEDS_VERIFICATION


# ---------------------------------------------------------------------------
# Verify endpoint
# ---------------------------------------------------------------------------

def _opportunity(last_verified_at):
    return SimpleNamespace(
        id=7,
        current_status=OpportunityStatus.NEEDS_VERIFICATION,
        official_application_url="https://boards.greenhouse.io/acme/jobs/12345",
        canonical_url="https://boards.greenhouse.io/acme/jobs/12345",
        last_verified_at=last_verified_at,
    )


@pytest.mark.asyncio
async def test_verify_endpoint_rejects_anonymous_callers(client):
    res = await client.post("/api/opportunities/7/verify")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_verify_endpoint_serves_recent_results_without_spending_credits(client):
    verifier = AsyncMock()
    with patch("backend.routers.radar.get_opportunity_by_id", AsyncMock(return_value=_opportunity(datetime.now(timezone.utc)))), \
         patch("backend.routers.radar.verify_opportunity_status", verifier):
        res = await client.post(
            "/api/opportunities/7/verify",
            headers={"Authorization": f"Bearer {create_session('radar@example.com')}"},
        )
    assert res.status_code == 200
    assert res.json()["cached"] is True
    verifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_endpoint_rechecks_stale_opportunities(client):
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    verifier = AsyncMock(return_value=(OpportunityStatus.NEEDS_VERIFICATION, "ok", now))
    with patch("backend.routers.radar.get_opportunity_by_id", AsyncMock(return_value=_opportunity(stale))), \
         patch("backend.routers.radar.verify_opportunity_status", verifier):
        res = await client.post(
            "/api/opportunities/7/verify",
            headers={"Authorization": f"Bearer {create_session('radar@example.com')}"},
        )
    assert res.status_code == 200
    assert "cached" not in res.json()
    verifier.assert_awaited_once()


# ---------------------------------------------------------------------------
# JobSpy persistence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jobspy_listings_are_not_persisted_as_verified():
    from backend.services.radar_sync import run_radar_sync

    listing = {
        "company_name": "Acme", "role_title": "Backend Intern",
        "canonical_url": "https://www.indeed.com/viewjob?jk=abc123",
        "official_application_url": "https://www.indeed.com/viewjob?jk=abc123",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "opportunity_type": "internship", "category": "software",
        "source_name": "JobSpy (indeed)", "source_type": "aggregator",
        "source_url": "https://www.indeed.com/viewjob?jk=abc123",
        "employer_identity_verified": False, "official_source_confirmed": False,
        "application_url_checked": False, "source_authority": "tier_2",
    }
    upsert = AsyncMock(return_value=1)
    add_source = AsyncMock()
    with patch("backend.services.radar_sync.discover_jobspy_opportunities",
               AsyncMock(return_value={"status": "success", "opportunities": [listing]})), \
         patch("backend.services.radar_sync.upsert_opportunity", upsert), \
         patch("backend.services.radar_sync.add_opportunity_source", add_source), \
         patch("backend.services.radar_sync.upsert_opportunity_requirements", AsyncMock()):
        await run_radar_sync("jobspy")

    kwargs = upsert.await_args.kwargs
    assert kwargs["official_source_confirmed"] is False
    assert kwargs["employer_identity_verified"] is False
    assert kwargs["application_url_checked"] is False
    assert add_source.await_args.kwargs["verification_result"] == "discovered"
    assert add_source.await_args.kwargs["source_authority"] == "tier_2"
