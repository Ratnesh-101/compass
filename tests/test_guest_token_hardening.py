"""
Guest-token and owner-scope hardening.

B. A stale (expired / invalid) x-guest-token next to x-guest-id is an unauthenticated caller (401 on
   protected routes, so the frontend re-mints), not impersonation (403). A VALID token for guest A
   with x-guest-id naming guest B, and a raw x-guest-id with no token, stay 403 in production.
C. The first accepted legacy two-part token logs one warning per process.
A. A blank owner id fails closed through the real schedule-commit skill path.
"""

import hashlib
import hmac
import logging
import time
import uuid

import pytest
from httpx import AsyncClient

from backend import dependencies
from backend.config import get_settings
from backend.dependencies import _get_guest_signing_secret, generate_guest_token, verify_guest_token
from backend.memory.db import get_pool
from backend.routers.auth import create_session
from backend.skills.handlers.calendar import handle_commit_schedule

PROTECTED = "/api/calendar/preferences"
SLOT = {"scheduled_start": "2031-03-01T09:00:00Z", "scheduled_end": "2031-03-01T10:00:00Z"}


@pytest.fixture
def production(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GUEST_SIGNING_SECRET", "super-secret-production-signing-key-32b")


def _expired_token(gid: str, age_days: int = 400) -> str:
    ts = int(time.time()) - age_days * 86400
    sig = hmac.new(_get_guest_signing_secret(), f"{gid}:{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{gid}.{ts}.{sig}"


def _legacy_token(gid: str) -> str:
    sig = hmac.new(_get_guest_signing_secret(), gid.encode(), hashlib.sha256).hexdigest()
    return f"{gid}.{sig}"


@pytest.mark.asyncio
async def test_expired_token_with_guest_id_is_unauthenticated_not_403(client: AsyncClient, production):
    gid = str(uuid.uuid4())
    token = _expired_token(gid)
    assert verify_guest_token(token) is None
    res = await client.get(PROTECTED, headers={"x-guest-id": gid, "x-guest-token": token})
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_invalid_token_with_guest_id_is_unauthenticated_not_403(client: AsyncClient, production):
    gid = str(uuid.uuid4())
    res = await client.get(PROTECTED, headers={"x-guest-id": gid, "x-guest-token": f"{gid}.123.deadbeef"})
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_valid_token_for_other_guest_is_still_403(client: AsyncClient, production):
    _, token_a = generate_guest_token()
    guest_b = str(uuid.uuid4())
    res = await client.get(PROTECTED, headers={"x-guest-id": guest_b, "x-guest-token": token_a})
    assert res.status_code == 403, res.text
    assert "impersonation" in res.json()["detail"]


@pytest.mark.asyncio
async def test_raw_guest_id_without_any_token_is_still_403(client: AsyncClient, production):
    res = await client.get(PROTECTED, headers={"x-guest-id": str(uuid.uuid4())})
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_valid_token_with_matching_guest_id_is_not_blocked(client: AsyncClient, production):
    gid, token = generate_guest_token()
    res = await client.get(PROTECTED, headers={"x-guest-id": gid, "x-guest-token": token})
    assert res.status_code not in (401, 403), res.text


def test_legacy_token_logs_one_warning_per_process(production, monkeypatch, caplog):
    monkeypatch.setattr(dependencies, "_legacy_guest_token_warned", False, raising=False)
    gid = str(uuid.uuid4())
    legacy = _legacy_token(gid)
    with caplog.at_level(logging.WARNING, logger=dependencies.logger.name):
        assert verify_guest_token(legacy) == gid
        assert verify_guest_token(legacy) == gid
        _, modern = generate_guest_token()
        assert verify_guest_token(modern) is not None
    warnings = [r for r in caplog.records if "legacy" in r.getMessage().lower()]
    assert len(warnings) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["   ", "\t\n"])
async def test_blank_owner_cannot_commit_schedule_on_any_task(client: AsyncClient, blank):
    owner = f"alice_{uuid.uuid4().hex[:8]}@example.com"
    headers = {"Authorization": f"Bearer {create_session(owner)}"}
    res = await client.post("/api/tasks", json={"title": "Private task", "domain": "hackathon"}, headers=headers)
    assert res.status_code == 200, res.text
    task_id = int(res.json()["id"])

    pool = await get_pool()
    result = await handle_commit_schedule(
        {"user_id": blank, "assignments": [{"task_id": task_id, **SLOT}]}, pool
    )
    assert result["data"]["committed_count"] == 0
    assert result["data"]["rejected_task_ids"] == [task_id]
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scheduled_start FROM tasks WHERE id = $1", task_id)
    assert row["scheduled_start"] is None
