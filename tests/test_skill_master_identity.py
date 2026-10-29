"""
Compass — agent skills must seed master-resume identity the same way the REST path does.

Signed-in users get name/email seeded; guests have no name and must never get an invented one.
"""

import uuid

import pytest

from backend.memory.career import get_master_resume
from backend.memory.radar import upsert_opportunity
from backend.skills.handlers import career as skill_career


async def _opportunity_id() -> int:
    return await upsert_opportunity(
        "Identity Corp", "Backend Intern", f"https://identity.test/careers/{uuid.uuid4().hex}"
    )


async def _master_after_cover_letter(user_id: str):
    opp_id = await _opportunity_id()
    await skill_career.handle_draft_cover_letter({"user_id": user_id, "opportunity_id": str(opp_id)})
    master = await get_master_resume(user_id)
    assert master is not None, "skill path should auto-create a master resume"
    return master.content


@pytest.mark.asyncio
async def test_skill_seeds_email_for_signed_in_email_user():
    email = f"skill-{uuid.uuid4().hex[:8]}@example.com"
    content = await _master_after_cover_letter(email)
    assert content.email == email
    assert content.full_name == ""


@pytest.mark.asyncio
async def test_skill_seeds_name_for_signed_in_name_user():
    name = f"skilluser{uuid.uuid4().hex[:8]}"
    content = await _master_after_cover_letter(name)
    assert content.full_name == name
    assert content.email == ""


@pytest.mark.asyncio
async def test_skill_never_invents_identity_for_guest():
    content = await _master_after_cover_letter(str(uuid.uuid4()))
    assert content.full_name == ""
    assert content.email == ""


@pytest.mark.asyncio
async def test_skill_never_invents_identity_for_prefixed_guest():
    content = await _master_after_cover_letter(f"guest_{uuid.uuid4().hex}")
    assert content.full_name == ""
    assert content.email == ""
