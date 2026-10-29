"""auto_prepare_strongest_matches and learning_skills must persist on the opportunity profile."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.dependencies import generate_guest_token
from backend.main import app
from backend.memory.radar import get_user_opportunity_profile, upsert_user_opportunity_profile
from backend.models_radar import UserOpportunityProfileIn


def _client(user_id: str) -> AsyncClient:
    _, token = generate_guest_token(user_id)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"x-guest-token": token})


@pytest.mark.asyncio
async def test_fields_round_trip_through_storage():
    user_id = str(uuid.uuid4())
    await upsert_user_opportunity_profile(
        user_id,
        UserOpportunityProfileIn(auto_prepare_strongest_matches=True, learning_skills=["Rust", "Go"]),
    )
    saved = await get_user_opportunity_profile(user_id)
    assert saved is not None
    assert saved.auto_prepare_strongest_matches is True
    assert saved.learning_skills == ["Rust", "Go"]


@pytest.mark.asyncio
async def test_defaults_are_off_and_empty():
    user_id = str(uuid.uuid4())
    await upsert_user_opportunity_profile(user_id, UserOpportunityProfileIn(degree="B.Tech"))
    saved = await get_user_opportunity_profile(user_id)
    assert saved.auto_prepare_strongest_matches is False
    assert saved.learning_skills == []


@pytest.mark.asyncio
async def test_put_round_trips_and_omitted_fields_are_preserved():
    user_id = str(uuid.uuid4())
    async with _client(user_id) as client:
        res = await client.put(
            "/api/opportunities/profile",
            json={"degree": "B.Tech", "auto_prepare_strongest_matches": True, "learning_skills": ["Rust"]},
        )
        assert res.status_code == 200
        assert res.json()["auto_prepare_strongest_matches"] is True
        # The profile modal does not send these fields; a later save must not silently opt the user out.
        res = await client.put("/api/opportunities/profile", json={"degree": "M.Tech"})
        assert res.status_code == 200
        body = res.json()
        assert body["degree"] == "M.Tech"
        assert body["auto_prepare_strongest_matches"] is True
        assert body["learning_skills"] == ["Rust"]
        # An explicit opt-out is honoured.
        res = await client.put("/api/opportunities/profile", json={"auto_prepare_strongest_matches": False})
        assert res.json()["auto_prepare_strongest_matches"] is False


@pytest.mark.asyncio
async def test_opt_in_is_tenant_isolated():
    user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())
    async with _client(user_a) as client_a:
        await client_a.put("/api/opportunities/profile", json={"auto_prepare_strongest_matches": True})
    async with _client(user_b) as client_b:
        res = await client_b.put("/api/opportunities/profile", json={"degree": "B.Sc"})
        assert res.json()["auto_prepare_strongest_matches"] is False
    other = await get_user_opportunity_profile(user_b)
    assert other.auto_prepare_strongest_matches is False
