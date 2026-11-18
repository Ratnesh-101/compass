"""
Owner-scope regressions from the security review (findings 2, 3, 4, 5).

No database needed: stores, pools and the calendar service are faked.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services import calendar as cal
from backend.services import tavily as tavily_service
from backend.skills import SKILL_REGISTRY


def _fake_pool():
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


# ---------------------------------------------------------------------------
# Finding 2: web memory writes carry the owner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_url_stores_chunks_with_the_callers_user_id(monkeypatch):
    pool, _ = _fake_pool()
    store = AsyncMock(return_value={"id": 1})
    monkeypatch.setattr("backend.memory.vector.store_chunk", store)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(
        tavily_service, "extract",
        AsyncMock(return_value={"results": [{"url": "https://example.com/a", "raw_content": "some page text"}]}),
    )

    res = await SKILL_REGISTRY["ingest_url"](
        {"url": "https://example.com/a", "domain": "general", "user_id": "owner-a"}, pool
    )

    assert res["success"] is True
    assert store.await_count >= 1
    assert all(c.kwargs["user_id"] == "owner-a" for c in store.await_args_list)


@pytest.mark.asyncio
async def test_ingest_url_without_user_id_stores_nothing(monkeypatch):
    pool, _ = _fake_pool()
    store = AsyncMock()
    extract = AsyncMock()
    monkeypatch.setattr("backend.memory.vector.store_chunk", store)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "extract", extract)

    res = await SKILL_REGISTRY["ingest_url"]({"url": "https://example.com/a", "domain": "general"}, pool)

    assert res["success"] is False
    assert "user_id required" in res["error"]
    store.assert_not_called()
    extract.assert_not_called()


@pytest.mark.asyncio
async def test_save_verified_finding_passes_owner_and_requires_one(monkeypatch):
    pool, _ = _fake_pool()
    store = AsyncMock(return_value={"id": 1})
    monkeypatch.setattr("backend.memory.vector.store_chunk", store)
    handler = SKILL_REGISTRY["save_verified_finding"]

    ok = await handler({"finding": "A fact", "user_id": "owner-a"}, pool)
    assert ok["success"] is True
    assert store.await_args.kwargs["user_id"] == "owner-a"

    store.reset_mock()
    missing = await handler({"finding": "A fact"}, pool)
    assert missing["success"] is False
    store.assert_not_called()


# ---------------------------------------------------------------------------
# Finding 3: get_calendar_freebusy needs an owner or all_tenants=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_freebusy_without_owner_or_all_tenants_reads_no_tasks(monkeypatch):
    monkeypatch.setattr(cal, "_fetch_google_busy", AsyncMock(return_value=([], None, False)))
    pool, conn = _fake_pool()

    busy = await cal.get_calendar_freebusy(
        "2031-03-01T00:00:00Z", "2031-03-02T00:00:00Z", pool=pool, user_id="u", include_simulated=False
    )

    assert busy == []
    conn.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_freebusy_reads_tasks_for_an_owner_and_for_all_tenants(monkeypatch):
    monkeypatch.setattr(cal, "_fetch_google_busy", AsyncMock(return_value=([], None, False)))
    pool, conn = _fake_pool()

    await cal.get_calendar_freebusy(
        "2031-03-01T00:00:00Z", "2031-03-02T00:00:00Z", pool=pool, user_id="u",
        include_simulated=False, task_user_id="owner-a",
    )
    assert conn.fetch.await_args.args[3] == "owner-a"

    conn.fetch.reset_mock()
    await cal.get_calendar_freebusy(
        "2031-03-01T00:00:00Z", "2031-03-02T00:00:00Z", pool=pool, user_id="admin",
        include_simulated=False, all_tenants=True,
    )
    assert conn.fetch.await_args.args[3] is None


# ---------------------------------------------------------------------------
# Findings 3 + 4: calendar handlers reject a missing caller and keep admin unscoped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["get_calendar_availability", "propose_schedule", "detect_schedule_conflicts"])
async def test_calendar_handlers_reject_a_missing_caller(monkeypatch, tool):
    spy = AsyncMock(return_value=[])
    monkeypatch.setattr(cal, "get_calendar_freebusy", spy)
    pool, _ = _fake_pool()

    for args in ({}, {"user_id": ""}, {"user_id": None}):
        res = await SKILL_REGISTRY[tool](dict(args), pool)
        assert res["success"] is False
        assert "user_id required" in res["response"]
    spy.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id, expected_owner, expected_all",
    [("admin", None, True), ("owner-a@example.com", "owner-a@example.com", False)],
)
@pytest.mark.parametrize("tool", ["get_calendar_availability", "propose_schedule", "detect_schedule_conflicts"])
async def test_calendar_handlers_scope_freebusy_and_tasks(monkeypatch, tool, user_id, expected_owner, expected_all):
    freebusy = AsyncMock(return_value=[])
    list_tasks = AsyncMock(return_value=[])
    monkeypatch.setattr(cal, "get_calendar_freebusy", freebusy)
    monkeypatch.setattr("backend.memory.structured.list_tasks", list_tasks)
    monkeypatch.setattr("backend.memory.structured.get_all_dependencies_map", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "backend.memory.structured.get_scheduling_preferences",
        AsyncMock(return_value={"work_start_time": "09:00:00", "work_end_time": "18:00:00",
                                "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}),
    )
    pool, _ = _fake_pool()

    await SKILL_REGISTRY[tool]({"user_id": user_id}, pool)

    assert freebusy.await_args.kwargs["task_user_id"] == expected_owner
    assert freebusy.await_args.kwargs["all_tenants"] is expected_all
    if tool != "get_calendar_availability":
        assert list_tasks.await_args.kwargs["user_id"] == expected_owner
        assert list_tasks.await_args.kwargs["all_tenants"] is expected_all
