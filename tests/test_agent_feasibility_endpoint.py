import pytest
import httpx
import uuid
from backend.main import app
from backend.dependencies import generate_guest_token


@pytest.mark.asyncio
async def test_feasibility_endpoint_allows_guest_token(monkeypatch):
    """Verify /api/agent/feasibility accepts valid guest token without server AUTH_TOKEN."""
    async def mock_review(pool, days, hours_per_day, domain, user_id, include_demo=False):
        yield {"type": "step", "content": "Analyzing workload"}
        yield {"type": "done", "content": "Feasible"}

    monkeypatch.setattr("backend.agents.feasibility.run_feasibility_review", mock_review)

    guest_id = str(uuid.uuid4())
    _, token = generate_guest_token(guest_id)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/agent/feasibility",
            headers={"x-guest-token": token, "Content-Type": "application/json"},
            json={"days": 5, "hours_per_day": 4.0},
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        assert "text/event-stream" in res.headers["content-type"]
        assert "Analyzing workload" in res.text


@pytest.mark.asyncio
async def test_feasibility_endpoint_rejects_missing_identity():
    """Verify /api/agent/feasibility rejects requests with no identity with 401."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/agent/feasibility",
            headers={"Content-Type": "application/json"},
            json={"days": 5, "hours_per_day": 4.0},
        )
        assert res.status_code == 401
