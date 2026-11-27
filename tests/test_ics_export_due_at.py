"""ICS export: due_at-only tasks, all-day due_date tasks, precedence, framing, endpoint counts."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from backend.services.calendar_ics import generate_ics_feed


def _vevents(ics: str) -> list[str]:
    return re.findall(r"BEGIN:VEVENT\r\n.*?END:VEVENT", ics, flags=re.S)


def test_due_at_only_yields_one_timed_event():
    ics = generate_ics_feed([{"id": "a1", "title": "T", "due_at": "2026-12-05T10:30:00+00:00"}])
    assert len(_vevents(ics)) == 1
    assert "DTSTART:20261205T103000Z\r\n" in ics
    assert "DTEND:20261205T113000Z\r\n" in ics


def test_due_date_only_yields_all_day_event():
    ics = generate_ics_feed([{"id": "a2", "title": "T", "due_date": "2026-12-05"}])
    assert len(_vevents(ics)) == 1
    assert "DTSTART;VALUE=DATE:20261205\r\n" in ics
    assert "DTEND;VALUE=DATE:20261206\r\n" in ics


def test_scheduled_slot_wins_over_due_at():
    ics = generate_ics_feed([{
        "id": "a3",
        "title": "T",
        "scheduled_start": "2026-12-01T08:00:00+00:00",
        "scheduled_end": "2026-12-01T09:15:00+00:00",
        "due_at": "2026-12-05T10:30:00+00:00",
    }])
    assert len(_vevents(ics)) == 1
    assert "DTSTART:20261201T080000Z" in ics
    assert "DTEND:20261201T091500Z" in ics
    assert "20261205T103000Z" not in ics


def test_task_without_any_date_yields_no_vevent():
    ics = generate_ics_feed([{"id": "a4", "title": "No date"}])
    assert _vevents(ics) == []


def test_framing_and_crlf():
    ics = generate_ics_feed([{"id": "a5", "title": "T", "due_at": "2026-12-05T10:30:00+00:00"}])
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    assert "\r" not in ics.replace("\r\n", "")
    assert all(line.endswith("\r\n") for line in ics.splitlines(keepends=True))


def test_two_tasks_get_different_uids():
    ics = generate_ics_feed([
        {"id": "x1", "title": "A", "due_at": "2026-12-05T10:30:00+00:00"},
        {"id": "x2", "title": "B", "due_at": "2026-12-05T10:30:00+00:00"},
    ])
    uids = re.findall(r"^UID:(.+?)\r$", ics, flags=re.M)
    assert len(uids) == 2
    assert uids[0] != uids[1]


def test_text_is_escaped():
    ics = generate_ics_feed([{
        "id": "e1",
        "title": "Buy milk, eggs; bread\nand tea",
        "due_at": "2026-12-05T10:30:00+00:00",
    }])
    assert "Buy milk\\, eggs\\; bread\\nand tea" in ics


# ---- endpoint -------------------------------------------------------------


class _Acquire:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Acquire()


@pytest.mark.asyncio
async def test_endpoint_counts_events_and_skipped(monkeypatch):
    from backend.routers import calendar as cal

    tasks = [
        {"id": "t1", "title": "Dated", "status": "open", "due_date": "2026-12-05"},
        {"id": "t2", "title": "DueAt", "status": "open", "due_at": "2026-12-05T10:30:00+00:00"},
        {"id": "t3", "title": "Undated", "status": "open"},
        {"id": "t4", "title": "Finished", "status": "done", "due_date": "2026-12-06"},
    ]

    async def fake_get_pool():
        return _Pool()

    async def fake_list_tasks(conn, **kwargs):
        return list(tasks)

    monkeypatch.setattr(cal, "get_pool", fake_get_pool)
    monkeypatch.setattr(cal.structured, "list_tasks", fake_list_tasks)
    monkeypatch.setattr(
        cal, "_get_current_identity",
        lambda request: SimpleNamespace(id="u1", user_id="u1", is_guest=False),
    )

    resp = await cal.export_calendar_ics_endpoint(request=SimpleNamespace(), domain=None)
    body = resp.body.decode("utf-8")
    assert len(_vevents(body)) == 2
    headers = {k.lower(): v for k, v in resp.headers.items()}
    if "x-compass-event-count" in headers:
        assert headers["x-compass-event-count"] == "2"
        assert headers["x-compass-skipped-count"] == "1"
    else:
        m = re.search(r"^X-WR-CALDESC:(.*)\r$", body, flags=re.M)
        assert m is not None, "neither X-Compass-Event-Count header nor X-WR-CALDESC found"
        assert "2" in m.group(1) and "1" in m.group(1)
