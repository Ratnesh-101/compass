"""
Compass — backend hardening regression tests.

Covers four small fixes:
  1. Google Calendar event URL quotes the calendar id.
  2. Batch lock registry evicts idle locks past a cap, never a held one.
  3. Job-analysis alias forwards the custom_desc query parameter.
  4. Exactly one GET "/" route is mounted.
"""

import asyncio
import urllib.parse

import httpx
import pytest

from backend.services import career_submission
from backend.services import calendar as calendar_service


# ---------------------------------------------------------------------------
# 1. Calendar id is percent-encoded in the events URL
# ---------------------------------------------------------------------------

class _FakeResponse:
    status_code = 201

    def json(self):
        return {"id": "evt_1", "htmlLink": "https://calendar.google.com/x"}


class _FakeAsyncClient:
    captured_urls: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.captured_urls.append(url)
        return _FakeResponse()


@pytest.mark.asyncio
async def test_calendar_event_url_quotes_calendar_id(monkeypatch):
    calendar_id = "team/room#1?x=y@group.calendar.google.com"
    _FakeAsyncClient.captured_urls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = await calendar_service.create_google_calendar_event(
        access_token="ya29.real-looking-token",
        title="Sync",
        start_iso="2026-11-12T10:00:00+00:00",
        end_iso="2026-11-12T10:30:00+00:00",
        calendar_id=calendar_id,
    )

    assert result["mode"] == "live"
    assert len(_FakeAsyncClient.captured_urls) == 1
    url = _FakeAsyncClient.captured_urls[0]
    expected = (
        "https://www.googleapis.com/calendar/v3/calendars/"
        + urllib.parse.quote(calendar_id, safe="")
        + "/events"
    )
    assert url == expected
    assert "#" not in url
    assert "?" not in url


# ---------------------------------------------------------------------------
# 2. Batch lock registry is bounded and never evicts a held lock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_locks_bounded_and_held_lock_kept():
    saved = dict(career_submission._batch_locks)
    career_submission._batch_locks.clear()
    try:
        held = career_submission.get_batch_lock("held")
        await held.acquire()
        try:
            for i in range(1500):
                career_submission.get_batch_lock(f"batch-{i}")

            # Cap is 1000 entries; at most one batch of 500 evictions plus the new entry.
            assert len(career_submission._batch_locks) <= 1001
            assert "held" in career_submission._batch_locks
            assert career_submission.get_batch_lock("held") is held
            assert held.locked()

            fresh_first = career_submission.get_batch_lock("fresh-id")
            fresh_second = career_submission.get_batch_lock("fresh-id")
            assert fresh_first is fresh_second
        finally:
            held.release()
    finally:
        career_submission._batch_locks.clear()
        career_submission._batch_locks.update(saved)


# ---------------------------------------------------------------------------
# 3. job-analysis alias forwards custom_desc
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_job_analysis_alias_forwards_custom_desc(client, monkeypatch):
    from backend.routers import career as career_router

    recorded = {}

    async def fake_analyze(opportunity_id, request, custom_desc=None):
        recorded["opportunity_id"] = opportunity_id
        recorded["custom_desc"] = custom_desc
        return {"ok": True}

    monkeypatch.setattr(career_router, "analyze_opportunity_job_endpoint", fake_analyze)

    resp = await client.get("/opportunities/1/job-analysis?custom_desc=hello")

    assert resp.status_code == 200
    assert recorded.get("opportunity_id") == 1
    assert recorded.get("custom_desc") == "hello"


# ---------------------------------------------------------------------------
# 4. Exactly one GET "/" route is mounted
# ---------------------------------------------------------------------------

def _effective_routes(app):
    """Yield (path, methods) for direct routes and routes inside included routers."""
    for r in app.routes:
        inner = getattr(r, "original_router", None)
        if inner is None:
            yield getattr(r, "path", None), getattr(r, "methods", None) or set()
            continue
        prefix = getattr(getattr(r, "include_context", None), "prefix", "") or ""
        for sub in inner.routes:
            yield prefix + getattr(sub, "path", ""), getattr(sub, "methods", None) or set()


def test_exactly_one_get_root_route():
    from backend.main import app

    get_root_routes = [
        (path, methods) for path, methods in _effective_routes(app)
        if path == "/" and "GET" in methods
    ]
    assert len(get_root_routes) == 1, get_root_routes
