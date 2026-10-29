"""
Regression tests for the Timeline / Schedule honesty fixes.

Each test fails against the pre-fix code: Google sync that reports success while creating nothing,
slot timestamps masquerading as deadlines, proposals in the past, partial commits, silent empty
timelines on backend errors, demo/finished tasks leaking into sync and .ics export, date-only
deadlines on the wrong day, and prerequisites that block forever. Google is always mocked.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.memory.db import get_pool
from backend.routers.auth import create_session
from backend.services import calendar as cal
from backend.services.calendar import (
    READONLY_WRITE_ERROR,
    create_google_calendar_event,
    generate_ics_feed,
    get_calendar_freebusy,
    link_calendar_event,
    sync_all_tasks_to_google_calendar,
)
from backend.services.scheduler import (
    TimeWindow,
    allocate_task_slots,
    ceil_to_quarter_hour,
    earliest_schedulable_start,
)
from backend.services.task_service import build_frontend_task
from backend.skills import SKILL_REGISTRY

REAL_TOKEN = "ya29.live-token-for-tests"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def fake_google(monkeypatch, status_code: int = 200, payload: dict | None = None):
    """Replace httpx.AsyncClient with a recorder; returns the list of recorded POSTs."""
    calls: list[dict] = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None, **kwargs):
            calls.append({"url": url, "headers": headers, "json": json})
            body = payload if payload is not None else {"id": f"evt_{len(calls)}", "htmlLink": "https://calendar.google.com/x"}
            return _FakeResponse(status_code, body)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return calls


def mock_pool_with_rows(rows):
    pool = MagicMock()
    conn = AsyncMock()
    conn.fetch.return_value = rows
    pool.acquire.return_value.__aenter__.return_value = conn
    return pool, conn


def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}


def _user(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _make_task(client, user_id: str, title: str, **extra) -> int:
    res = await client.post("/api/tasks", json={"title": title, "domain": "hackathon", **extra}, headers=_auth(user_id))
    assert res.status_code == 200, res.text
    return int(res.json()["id"])


def _future_slot(days: int = 3, hour: int = 10):
    start = (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=1)


# ---------------------------------------------------------------------------
# 1. Google sync must not claim events it never created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refused_event_create_returns_error_without_fake_id(monkeypatch):
    fake_google(monkeypatch, status_code=403)
    res = await create_google_calendar_event(REAL_TOKEN, "Ship it", "2031-03-01T10:00:00+00:00", "2031-03-01T11:00:00+00:00")
    assert res["id"] is None
    assert res["mode"] == "error"
    assert res["error"] == READONLY_WRITE_ERROR
    assert "read-only" in res["error"]


@pytest.mark.asyncio
async def test_network_failure_event_create_returns_error(monkeypatch):
    class _Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise httpx.ConnectError("down")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(httpx, "AsyncClient", _Boom)
    res = await create_google_calendar_event(REAL_TOKEN, "Ship it", "2031-03-01T10:00:00+00:00", "2031-03-01T11:00:00+00:00")
    assert res["id"] is None and res["mode"] == "error"


@pytest.mark.asyncio
async def test_failed_create_is_not_recorded_in_calendar_event_links(monkeypatch):
    fake_google(monkeypatch, status_code=403)
    pool, conn = mock_pool_with_rows([])
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        res = await link_calendar_event(
            task_id=7, start_dt="2031-03-01T10:00:00Z", end_dt="2031-03-01T11:00:00Z",
            title="Plan", pool=pool, user_id="u@example.com",
        )
    assert res["status"] == "failed"
    assert res["live_created"] is False
    assert res["google_event_id"] is None
    assert res["error"] == READONLY_WRITE_ERROR
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_live_create_is_recorded_and_flagged_live(monkeypatch):
    fake_google(monkeypatch, status_code=200, payload={"id": "evt_real", "htmlLink": "https://calendar.google.com/e"})
    pool, conn = mock_pool_with_rows([])
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        res = await link_calendar_event(
            task_id=7, start_dt="2031-03-01T10:00:00Z", end_dt="2031-03-01T11:00:00Z",
            title="Plan", pool=pool, user_id="u@example.com",
        )
    assert res["status"] == "synced" and res["live_created"] is True
    assert res["google_event_id"] == "evt_real"
    assert conn.execute.called


@pytest.mark.asyncio
async def test_sync_all_reports_errors_and_never_says_synced_when_google_refuses(monkeypatch):
    fake_google(monkeypatch, status_code=403)
    slot_start, slot_end = _future_slot()
    rows = [
        {"id": i, "title": f"T{i}", "domain": "code", "priority": "high", "notes": None,
         "duration_minutes": 60, "due_date": None, "scheduled_start": slot_start + timedelta(hours=i), "scheduled_end": slot_end + timedelta(hours=i)}
        for i in (1, 2)
    ]
    pool, _ = mock_pool_with_rows(rows)
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        result = await sync_all_tasks_to_google_calendar(pool, user_id="u@example.com")
    assert result["live_created"] == 0
    assert result["error_count"] == 2
    assert result["success"] is False
    assert result["calendar_error"] == READONLY_WRITE_ERROR
    assert "Synced" not in result["message"]
    assert all(e["live_created"] is False and e["google_event_id"] is None for e in result["events"])


@pytest.mark.asyncio
async def test_sync_all_counts_only_real_creations(monkeypatch):
    fake_google(monkeypatch, status_code=200)
    slot_start, slot_end = _future_slot()
    rows = [{"id": 1, "title": "A", "domain": "code", "priority": "high", "notes": None, "duration_minutes": 60,
             "due_date": None, "scheduled_start": slot_start, "scheduled_end": slot_end}]
    pool, _ = mock_pool_with_rows(rows)
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        result = await sync_all_tasks_to_google_calendar(pool, user_id="u@example.com")
    assert result["live_created"] == 1 and result["error_count"] == 0 and result["success"] is True
    assert result["message"].startswith("Synced 1 task ")


@pytest.mark.asyncio
async def test_simulated_mode_is_labelled_simulated_and_not_recorded():
    pool, conn = mock_pool_with_rows([])
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value="mock_ya29_demo")):
        res = await link_calendar_event(
            task_id=3, start_dt="2031-03-01T10:00:00Z", end_dt="2031-03-01T11:00:00Z",
            title="Demo", pool=pool, user_id="u@example.com",
        )
    assert res["status"] == "simulated" and res["live_created"] is False and res["mode"] == "simulated"
    conn.execute.assert_not_called()
    assert "Simulated" in cal.summarize_calendar_outcome(0, 0, 1, 0, None)


@pytest.mark.asyncio
async def test_simulation_is_refused_in_production():
    from backend.config import get_settings

    settings = get_settings()
    original = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"
    try:
        res = await create_google_calendar_event("mock_ya29_demo", "x", "2031-03-01T10:00:00Z", "2031-03-01T11:00:00Z")
    finally:
        settings.ENVIRONMENT = original
    assert res["id"] is None and res["mode"] == "error"


# ---------------------------------------------------------------------------
# 2. The real deadline is not replaced by the scheduled slot
# ---------------------------------------------------------------------------

def test_frontend_task_due_date_is_the_real_deadline_not_the_slot_end():
    row = {
        "id": 1, "title": "Report", "domain": "coursework", "priority": "medium", "status": "open",
        "due_date": date(2031, 6, 30),
        "scheduled_start": datetime(2031, 6, 2, 9, 0, tzinfo=timezone.utc),
        "scheduled_end": datetime(2031, 6, 2, 10, 0, tzinfo=timezone.utc),
        "created_at": datetime(2031, 1, 1, tzinfo=timezone.utc),
    }
    out = build_frontend_task(row)
    assert out.due_date == "2031-06-30"
    assert out.scheduled_end.startswith("2031-06-02T10:00")


def test_frontend_task_without_deadline_has_no_due_date_even_when_scheduled():
    row = {
        "id": 2, "title": "Focus block", "domain": "code", "priority": "low", "status": "open", "due_date": None,
        "scheduled_start": datetime(2031, 6, 2, 9, 0, tzinfo=timezone.utc),
        "scheduled_end": datetime(2031, 6, 2, 10, 0, tzinfo=timezone.utc),
        "created_at": datetime(2031, 1, 1, tzinfo=timezone.utc),
    }
    assert build_frontend_task(row).due_date is None


@pytest.mark.asyncio
async def test_put_task_accepts_iso_timestamp_due_date_and_rejects_garbage(client):
    user = _user("due")
    task_id = await _make_task(client, user, "Timestamp due", due_date="2031-05-01")
    ok = await client.put(f"/api/tasks/{task_id}", json={"due_date": "2031-07-04T10:00:00+00:00"}, headers=_auth(user))
    assert ok.status_code == 200, ok.text
    assert ok.json()["due_date"] == "2031-07-04"
    bad = await client.put(f"/api/tasks/{task_id}", json={"due_date": "not-a-date"}, headers=_auth(user))
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_scheduled_task_keeps_real_due_date_through_the_api(client):
    user = _user("slot")
    task_id = await _make_task(client, user, "Keeps deadline", due_date="2031-12-20")
    start, end = _future_slot()
    commit = await client.post(
        "/api/schedule/commit",
        json={"assignments": [{"task_id": task_id, "scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}]},
        headers=_auth(user),
    )
    assert commit.status_code == 200, commit.text
    listing = await client.get("/api/tasks", headers=_auth(user))
    row = next(t for t in listing.json() if t["id"] == str(task_id))
    assert row["due_date"] == "2031-12-20"
    assert row["scheduled_start"] is not None


# ---------------------------------------------------------------------------
# 3. No slots in the past; commits validate everything first
# ---------------------------------------------------------------------------

def test_ceil_to_quarter_hour_rounds_up():
    assert ceil_to_quarter_hour(datetime(2031, 1, 1, 10, 0, 0, tzinfo=timezone.utc)) == datetime(2031, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert ceil_to_quarter_hour(datetime(2031, 1, 1, 10, 1, 0, tzinfo=timezone.utc)) == datetime(2031, 1, 1, 10, 15, tzinfo=timezone.utc)
    assert ceil_to_quarter_hour(datetime(2031, 1, 1, 10, 46, 5, tzinfo=timezone.utc)) == datetime(2031, 1, 1, 11, 0, tzinfo=timezone.utc)


def test_earliest_schedulable_start_clamps_past_and_keeps_future():
    now = datetime(2031, 1, 5, 10, 7, tzinfo=timezone.utc)
    assert earliest_schedulable_start(datetime(2031, 1, 5, 0, 0, tzinfo=timezone.utc), now) == datetime(2031, 1, 5, 10, 15, tzinfo=timezone.utc)
    future = datetime(2031, 1, 9, 0, 0, tzinfo=timezone.utc)
    assert earliest_schedulable_start(future, now) == future


def test_allocator_never_places_before_not_before():
    day = datetime(2031, 1, 5, tzinfo=timezone.utc)
    window = TimeWindow(start=day.replace(hour=9), end=day.replace(hour=18))
    result = allocate_task_slots(
        [{"id": 1, "title": "A", "duration_minutes": 60}], [window],
        not_before=day.replace(hour=14, minute=15),
    )
    assert result["scheduled"][0]["scheduled_start"].startswith("2031-01-05T14:15")


@pytest.mark.asyncio
async def test_propose_schedule_for_a_past_date_starts_no_earlier_than_now():
    handler = SKILL_REGISTRY["propose_schedule"]
    before = datetime.now(timezone.utc)
    result = await handler({"target_date": "2020-01-06"}, pool=None)
    horizon_start = datetime.fromisoformat(result["data"]["horizon"]["start"])
    assert horizon_start >= before.replace(microsecond=0)
    assert horizon_start.minute % 15 == 0


@pytest.mark.asyncio
async def test_commit_rejects_all_when_any_assignment_is_invalid_and_applies_nothing(client):
    user = _user("commit")
    good_id = await _make_task(client, user, "Valid one")
    other_id = await _make_task(client, user, "Invalid one")
    start, end = _future_slot(days=5)
    res = await client.post(
        "/api/schedule/commit",
        json={"assignments": [
            {"task_id": good_id, "scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()},
            {"task_id": other_id, "scheduled_start": "2020-01-01T09:00:00Z", "scheduled_end": "2020-01-01T10:00:00Z"},
        ]},
        headers=_auth(user),
    )
    assert res.status_code == 422, res.text
    errors = res.json()["errors"]
    assert [e["task_id"] for e in errors] == [other_id]
    assert "past" in errors[0]["error"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT scheduled_start FROM tasks WHERE id = $1", good_id)
    assert row["scheduled_start"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end,fragment",
    [
        ("2031-03-01T10:00:00Z", "2031-03-01T09:00:00Z", "after"),
        ("not-a-time", "2031-03-01T09:00:00Z", "ISO"),
        ("2031-03-01T10:00:00Z", None, "required"),
    ],
)
async def test_commit_reports_each_kind_of_invalid_assignment(client, start, end, fragment):
    user = _user("badslot")
    task_id = await _make_task(client, user, "Bad slot")
    item = {"task_id": task_id, "scheduled_start": start}
    if end is not None:
        item["scheduled_end"] = end
    res = await client.post("/api/schedule/commit", json={"assignments": [item]}, headers=_auth(user))
    assert res.status_code == 422, res.text
    assert fragment in res.json()["errors"][0]["error"]


@pytest.mark.asyncio
async def test_commit_result_carries_honest_calendar_fields(client):
    user = _user("honest")
    task_id = await _make_task(client, user, "Calendar fields")
    start, end = _future_slot(days=6)
    res = await client.post(
        "/api/schedule/commit",
        json={"assignments": [{"task_id": task_id, "scheduled_start": start.isoformat(), "scheduled_end": end.isoformat()}]},
        headers=_auth(user),
    )
    data = res.json()["data"]
    assert data["committed_count"] == 1
    assert data["live_created"] == 0
    assert "error_count" in data and "calendar_error" in data
    assert "synced to Google Calendar" not in res.json()["response"]


# ---------------------------------------------------------------------------
# 4. A backend failure must not look like an empty timeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tasks_list_returns_503_when_the_database_query_fails(client, monkeypatch):
    user = _user("fail")
    from backend.routers import tasks as tasks_router

    monkeypatch.setattr(tasks_router.structured, "list_tasks", AsyncMock(side_effect=RuntimeError("db down")))
    res = await client.get("/api/tasks", headers=_auth(user))
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_tasks_list_still_returns_empty_list_without_identity(client):
    res = await client.get("/api/tasks")
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# 5. Demo and finished tasks are not synced or exported
# ---------------------------------------------------------------------------

async def _seed_user_tasks(client):
    user = _user("seed")
    real = f"Real {uuid.uuid4().hex[:6]}"
    done = f"Done {uuid.uuid4().hex[:6]}"
    demo = f"Demo {uuid.uuid4().hex[:6]}"
    real_id = await _make_task(client, user, real, due_date="2031-08-15")
    done_id = await _make_task(client, user, done, due_date="2031-08-16")
    demo_id = await _make_task(client, user, demo, due_date="2031-08-17")
    patched = await client.patch(f"/api/tasks/{done_id}", json={"status": "done"}, headers=_auth(user))
    assert patched.status_code == 200, patched.text
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tasks SET trusted_event_url = $1 WHERE id = $2", "compass://demo-persona/judge/1", demo_id)
    return user, real, done, demo, real_id


@pytest.mark.asyncio
async def test_sync_selects_only_open_real_tasks(client, monkeypatch):
    user, real, done, demo, _ = await _seed_user_tasks(client)
    calls = fake_google(monkeypatch, status_code=200)
    pool = await get_pool()
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        result = await sync_all_tasks_to_google_calendar(pool, user_id=user)
    summaries = [c["json"]["summary"] for c in calls]
    assert summaries == [f"[Compass] {real}"]
    assert result["live_created"] == 1


@pytest.mark.asyncio
async def test_ics_export_excludes_demo_and_finished_tasks_and_does_not_fall_back(client):
    user, real, done, demo, _ = await _seed_user_tasks(client)
    res = await client.get("/api/calendar/export.ics", headers=_auth(user))
    assert res.status_code == 200
    assert real in res.text
    assert done not in res.text
    assert demo not in res.text


# ---------------------------------------------------------------------------
# 6/7. Date-only deadlines are all-day; ICS text is escaped and folded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_due_date_only_task_becomes_an_all_day_google_event(monkeypatch):
    calls = fake_google(monkeypatch, status_code=200)
    rows = [{"id": 5, "title": "Submit", "domain": "coursework", "priority": "high", "notes": None,
             "duration_minutes": 60, "due_date": date(2031, 3, 10), "scheduled_start": None, "scheduled_end": None}]
    pool, _ = mock_pool_with_rows(rows)
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        await sync_all_tasks_to_google_calendar(pool, user_id="u@example.com")
    body = calls[0]["json"]
    assert body["start"] == {"date": "2031-03-10"}
    assert body["end"] == {"date": "2031-03-11"}


def test_ics_due_date_only_task_is_an_all_day_event():
    ics = generate_ics_feed([{"id": 9, "title": "Hand in", "domain": "coursework", "due_date": date(2031, 3, 10)}])
    assert "DTSTART;VALUE=DATE:20310310" in ics
    assert "DTEND;VALUE=DATE:20310311" in ics
    assert "DTSTART:20310310T000000Z" not in ics


def test_ics_escapes_special_characters_and_folds_long_lines():
    ics = generate_ics_feed([{
        "id": 1, "title": "A, B; C \\ D\nE", "domain": "code",
        "scheduled_start": "2031-03-01T10:00:00Z", "scheduled_end": "2031-03-01T11:00:00Z",
        "notes": "x" * 200 + ", y; z",
    }])
    assert "SUMMARY:[CODE] A\\, B\\; C \\\\ D\\nE" in ics
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line
    unfolded = ics.replace("\r\n ", "")
    assert "\\, y\\; z" in unfolded


# ---------------------------------------------------------------------------
# 10. Free/busy uses the refresh path and reports failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_freebusy_uses_the_refreshing_token_helper(monkeypatch):
    calls = fake_google(monkeypatch, status_code=200, payload={"calendars": {"primary": {"busy": []}}})
    pool, _ = mock_pool_with_rows([])
    helper = AsyncMock(return_value="ya29.refreshed")
    with patch.object(cal, "get_valid_access_token_for_user", helper):
        await get_calendar_freebusy(
            "2031-03-01T00:00:00Z", "2031-03-02T00:00:00Z", pool=pool, user_id="u@example.com", include_simulated=False
        )
    helper.assert_awaited()
    assert calls[0]["headers"]["Authorization"] == "Bearer ya29.refreshed"


@pytest.mark.asyncio
async def test_freebusy_401_is_reported_in_calendar_errors(monkeypatch):
    fake_google(monkeypatch, status_code=401)
    pool, _ = mock_pool_with_rows([])
    errors: list[str] = []
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        busy = await get_calendar_freebusy(
            "2031-03-01T00:00:00Z", "2031-03-02T00:00:00Z", pool=pool, user_id="u@example.com",
            include_simulated=False, calendar_errors=errors,
        )
    assert busy == []
    assert errors and "Reconnect" in errors[0]


@pytest.mark.asyncio
async def test_availability_handler_surfaces_calendar_error(monkeypatch):
    fake_google(monkeypatch, status_code=403)
    pool, _ = mock_pool_with_rows([])
    handler = SKILL_REGISTRY["get_calendar_availability"]
    with patch.object(cal, "get_valid_access_token_for_user", AsyncMock(return_value=REAL_TOKEN)):
        result = await handler({"start_date": "2031-03-01", "end_date": "2031-03-02", "user_id": "u@example.com"}, pool)
    assert result["data"]["calendar_error"]


# ---------------------------------------------------------------------------
# 11. Completed / out-of-scope prerequisites do not block scheduling
# ---------------------------------------------------------------------------

def _one_window():
    day = datetime(2031, 1, 6, tzinfo=timezone.utc)
    return [TimeWindow(start=day.replace(hour=9), end=day.replace(hour=18))]


def test_prerequisite_outside_the_candidate_set_does_not_block():
    tasks = [{"id": 2, "title": "Child", "duration_minutes": 60}]
    result = allocate_task_slots(tasks, _one_window(), dependencies={2: [1]})
    assert [s["task_id"] for s in result["scheduled"]] == [2]
    assert result["unassigned"] == []


def test_done_prerequisite_in_the_candidate_set_is_ignored():
    tasks = [
        {"id": 1, "title": "Parent", "status": "done", "priority": "low", "duration_minutes": 60},
        {"id": 2, "title": "Child", "priority": "urgent", "duration_minutes": 60},
    ]
    result = allocate_task_slots(tasks, _one_window(), dependencies={2: [1]})
    # the finished parent no longer holds the urgent child back
    assert result["scheduled"][0]["task_id"] == 2


def test_open_prerequisite_in_the_set_still_orders_dependents():
    tasks = [
        {"id": 2, "title": "Child", "priority": "urgent", "duration_minutes": 60},
        {"id": 1, "title": "Parent", "priority": "low", "duration_minutes": 60},
    ]
    result = allocate_task_slots(tasks, _one_window(), dependencies={2: [1]})
    order = [s["task_id"] for s in result["scheduled"]]
    assert order == [1, 2]
