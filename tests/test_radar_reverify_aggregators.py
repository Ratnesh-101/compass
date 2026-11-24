"""Aggregator hosts (glassdoor/linkedin/indeed) cannot be verified by fetch; they must be downgraded, not fetched."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from backend.models_radar import OpportunityStatus
from backend.services import radar_reverify
from backend.services.radar_reverify import is_unverifiable_aggregator


@pytest.mark.parametrize(
    "url",
    [
        "https://www.glassdoor.com/job-listing/x",
        "https://glassdoor.com/y",
        "https://uk.linkedin.com/jobs/view/1",
        "https://in.indeed.com/viewjob?jk=1",
    ],
)
def test_aggregator_urls_detected(url):
    assert is_unverifiable_aggregator(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://notglassdoor.com/x",
        "https://evil.com/?u=https://glassdoor.com",
        "",
        "not a url",
    ],
)
def test_non_aggregator_urls_not_detected(url):
    assert is_unverifiable_aggregator(url) is False


def _rows():
    return [
        {
            "id": 1,
            "application_url": "https://www.glassdoor.com/x",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": None,
        },
        {
            "id": 2,
            "application_url": "https://boards.greenhouse.io/a/jobs/2",
            "current_status": "OPEN_CONFIRMED",
            "last_verified_at": None,
        },
    ]


def _setup(monkeypatch):
    async def fake_select(limit=100):
        return _rows()

    status_mock = AsyncMock()
    verification_mock = AsyncMock()
    monkeypatch.setattr(radar_reverify, "select_stale_open_opportunities", fake_select)
    monkeypatch.setattr(radar_reverify.radar_memory, "update_opportunity_status", status_mock)
    monkeypatch.setattr(radar_reverify.radar_memory, "update_opportunity_verification", verification_mock)

    calls = []

    async def verify(url, status=None):
        calls.append(url)
        return ("OPEN_CONFIRMED", "ok", datetime.now(timezone.utc))

    return calls, verify, status_mock


@pytest.mark.asyncio
async def test_reverify_downgrades_aggregator_without_fetching(monkeypatch):
    calls, verify, status_mock = _setup(monkeypatch)

    result = await radar_reverify.reverify_stale_opportunities(verify=verify)

    assert calls == ["https://boards.greenhouse.io/a/jobs/2"]
    assert status_mock.await_count == 1
    args = status_mock.await_args.args
    assert args[0] == 1
    assert args[1] == OpportunityStatus.NEEDS_VERIFICATION
    assert result["downgraded"] == 1
    assert result["still_open"] == 1
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_reverify_dry_run_does_not_write(monkeypatch):
    calls, verify, status_mock = _setup(monkeypatch)

    result = await radar_reverify.reverify_stale_opportunities(dry_run=True, verify=verify)

    assert "https://www.glassdoor.com/x" not in calls
    status_mock.assert_not_called()
    assert result["downgraded"] == 1
    assert result["still_open"] == 1
    assert result["errors"] == 0
