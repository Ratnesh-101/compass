"""Validation of PUT /api/calendar/preferences input (DB-free)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.models import UpdatePreferencesBody
from backend.routers import calendar as cal

CURRENT = {
    "work_start_time": "09:00:00",
    "work_end_time": "18:00:00",
    "work_days": [1, 2, 3, 4, 5],
    "buffer_minutes": 15,
    "preferred_focus": "morning",
}


def test_empty_body_is_valid():
    body = UpdatePreferencesBody()
    assert body.model_dump() == {
        "work_start_time": None,
        "work_end_time": None,
        "work_days": None,
        "buffer_minutes": None,
    }


def test_valid_values_and_normalisation():
    body = UpdatePreferencesBody(
        work_start_time="09:30", work_end_time="17:45:10", work_days=[5, 1, 3], buffer_minutes=0
    )
    assert body.work_start_time == "09:30:00"
    assert body.work_end_time == "17:45:10"
    assert body.work_days == [1, 3, 5]
    assert body.buffer_minutes == 0
    assert UpdatePreferencesBody(buffer_minutes=120).buffer_minutes == 120


@pytest.mark.parametrize("bad", ["25:00", "09:60", "abc", "", "9:00", 900, True])
@pytest.mark.parametrize("field", ["work_start_time", "work_end_time"])
def test_invalid_times(field, bad):
    with pytest.raises(ValidationError):
        UpdatePreferencesBody(**{field: bad})


@pytest.mark.parametrize("bad", [[], [0], [8], [1, 1], ["1"], [1.5], [True], "1", 5])
def test_invalid_work_days(bad):
    with pytest.raises(ValidationError):
        UpdatePreferencesBody(work_days=bad)


@pytest.mark.parametrize("bad", [-1, 121, "x", True, 1.5])
def test_invalid_buffer(bad):
    with pytest.raises(ValidationError):
        UpdatePreferencesBody(buffer_minutes=bad)


@pytest.fixture
def saved(monkeypatch):
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield object()

    async def fake_get_pool():
        return Pool()

    update = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(cal, "get_pool", fake_get_pool)
    monkeypatch.setattr(cal.structured, "get_scheduling_preferences", AsyncMock(return_value=dict(CURRENT)))
    monkeypatch.setattr(cal.structured, "update_scheduling_preferences", update)
    return update


IDENT = SimpleNamespace(id="u1")


async def test_end_before_current_start_rejected(saved):
    with pytest.raises(HTTPException) as exc:
        await cal.update_calendar_preferences_endpoint(UpdatePreferencesBody(work_end_time="08:00"), IDENT)
    assert exc.value.status_code == 422
    assert exc.value.detail == "End time must be after start time."
    saved.assert_not_called()


async def test_start_only_saves(saved):
    result = await cal.update_calendar_preferences_endpoint(UpdatePreferencesBody(work_start_time="10:00"), IDENT)
    assert result["status"] == "ok"
    saved.assert_awaited_once()
    assert saved.await_args.kwargs == {"user_id": "u1", "work_start_time": "10:00:00"}


async def test_end_only_saves(saved):
    await cal.update_calendar_preferences_endpoint(UpdatePreferencesBody(work_end_time="20:00"), IDENT)
    saved.assert_awaited_once()
    assert saved.await_args.kwargs == {"user_id": "u1", "work_end_time": "20:00:00"}
