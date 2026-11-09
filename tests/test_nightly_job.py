"""
Compass — Nightly job auth tests.

POST /api/agent/trigger-nightly accepts the scoped NIGHTLY_JOB_TOKEN or the master AUTH_TOKEN.
The scoped token must not unlock any other route. Fully mocked: no database is touched.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from backend.config import get_settings

NIGHTLY = "nightly-scoped-test-token-0123456789"
MASTER = "compass-test-auth-token"


@pytest.fixture
def mock_consolidation(monkeypatch):
    """Mock run_consolidation and get_pool so the trigger endpoint never touches a DB."""
    fake = AsyncMock(return_value={"status": "completed"})
    monkeypatch.setattr("backend.jobs.consolidate.run_consolidation", fake)
    monkeypatch.setattr("backend.routers.agent.get_pool", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr("backend.routers.admin.get_pool", AsyncMock(return_value=MagicMock()))
    return fake


@pytest.mark.asyncio
async def test_trigger_nightly_admin_auth(client: AsyncClient, monkeypatch, mock_consolidation):
    """Scoped nightly token or master token is accepted; everything else is 401 and fails closed."""
    settings = get_settings()
    monkeypatch.setattr(settings, "AUTH_TOKEN", MASTER)
    monkeypatch.setattr(settings, "NIGHTLY_JOB_TOKEN", NIGHTLY)
    url = "/api/agent/trigger-nightly"

    # Scoped nightly token -> accepted
    resp = await client.post(url, headers={"Authorization": f"Bearer {NIGHTLY}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"
    assert mock_consolidation.await_count == 1

    # Master AUTH_TOKEN -> accepted
    resp = await client.post(url, headers={"Authorization": f"Bearer {MASTER}"})
    assert resp.status_code == 200, resp.text
    assert mock_consolidation.await_count == 2

    # Empty bearer, no header, wrong token -> 401, job never runs
    for headers in ({"Authorization": "Bearer "}, {}, {"Authorization": "Bearer wrong-token"}):
        resp = await client.post(url, headers=headers)
        assert resp.status_code == 401, headers
        assert resp.json() == {"detail": "Unauthorized"}
    assert mock_consolidation.await_count == 2

    # Nightly token is NOT accepted on other admin routes (they still use verify_token)
    nightly_headers = {"Authorization": f"Bearer {NIGHTLY}"}
    resp = await client.get("/admin/usage", headers=nightly_headers)
    assert resp.status_code == 401
    resp = await client.post("/admin/consolidate", headers=nightly_headers)
    assert resp.status_code == 401
    assert mock_consolidation.await_count == 2


@pytest.mark.asyncio
async def test_trigger_nightly_unset_token_fails_closed(
    client: AsyncClient, monkeypatch, mock_consolidation
):
    """With NIGHTLY_JOB_TOKEN unset, a random bearer (or empty one) must not authenticate."""
    settings = get_settings()
    monkeypatch.setattr(settings, "AUTH_TOKEN", MASTER)
    monkeypatch.setattr(settings, "NIGHTLY_JOB_TOKEN", "")
    url = "/api/agent/trigger-nightly"

    for bearer in ("random-bearer-value", ""):
        resp = await client.post(url, headers={"Authorization": f"Bearer {bearer}"})
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}
    mock_consolidation.assert_not_awaited()

    # Master token still works
    resp = await client.post(url, headers={"Authorization": f"Bearer {MASTER}"})
    assert resp.status_code == 200
