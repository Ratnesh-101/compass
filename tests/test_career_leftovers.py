"""Leftover career fixes: explicit clearing of optional fields; bad opportunity ids in the prepare skill."""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient

from backend.memory.career import (
    get_career_application_by_id,
    get_or_create_career_application,
    update_career_application,
)
from backend.memory.radar import upsert_opportunity
from backend.skills.handlers import career as skill_career


async def _new_app(client: AsyncClient):
    assert (await client.post("/api/guest/session")).status_code == 200
    opp_id = await upsert_opportunity("Leftovers Inc", "Intern", f"https://leftovers.test/{uuid.uuid4().hex}")
    user_id = f"leftover-{uuid.uuid4().hex[:8]}"
    return user_id, await get_or_create_career_application(user_id, opp_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, value",
    [("private_notes", "call recruiter"), ("cover_letter", "Dear team"), ("target_deadline", date(2030, 1, 2))],
)
async def test_explicit_none_clears_optional_field(client: AsyncClient, field, value):
    user_id, app = await _new_app(client)
    await update_career_application(app.id, user_id, {field: value})
    assert getattr(await get_career_application_by_id(app.id, user_id), field) == value

    await update_career_application(app.id, user_id, {field: None})

    assert getattr(await get_career_application_by_id(app.id, user_id), field) is None


@pytest.mark.asyncio
async def test_absent_key_leaves_optional_fields_unchanged(client: AsyncClient):
    user_id, app = await _new_app(client)
    await update_career_application(app.id, user_id, {"private_notes": "keep me", "cover_letter": "letter"})

    await update_career_application(app.id, user_id, {"resume_id": None})

    after = await get_career_application_by_id(app.id, user_id)
    assert after.private_notes == "keep me" and after.cover_letter == "letter"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["abc", "12x", [1], {"a": 1}])
async def test_prepare_application_skill_rejects_non_numeric_opportunity_id(bad_id):
    result = await skill_career.handle_prepare_application({"user_id": "u", "opportunity_id": bad_id})
    assert result["success"] is False
    assert "Invalid opportunity_id" in result["error"]
