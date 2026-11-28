"""Timeline tasks follow the application: Applied -> follow-up, Closed -> done, deadline -> due date.

Uses an in-memory task store in place of the database; no network."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.services import career_task_sync as sync

USER = "sync_user_1"
OTHER = "sync_user_2"


class FakeStore:
    def __init__(self):
        self.tasks = []
        self.next_id = 1

    async def list_tasks(self, conn, user_id=None, **_):
        return [dict(t) for t in self.tasks if t["user_id"] == user_id]

    async def create_task(self, conn, domain, title, due_date=None, priority="medium", notes=None, user_id=None, **_):
        row = {"id": self.next_id, "domain": domain, "title": title, "due_date": due_date,
               "status": "open", "priority": priority, "notes": notes, "user_id": user_id}
        self.next_id += 1
        self.tasks.append(row)
        return row

    async def update_task(self, conn, task_id, owner_id=None, **kw):
        for t in self.tasks:
            if t["id"] == task_id and t["user_id"] == owner_id:
                t.update(kw)
                return t
        return None


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    monkeypatch.setattr(sync.structured, "list_tasks", s.list_tasks)
    monkeypatch.setattr(sync.structured, "create_task", s.create_task)
    monkeypatch.setattr(sync.structured, "update_task", s.update_task)

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield object()

    async def fake_pool():
        return Pool()

    import backend.memory.db as db
    monkeypatch.setattr(db, "get_pool", fake_pool)
    s.add_apply = lambda user=USER, due=date(2030, 1, 10): s.tasks.append({
        "id": s.next_id, "domain": "general", "title": "Apply: Intern at Acme", "due_date": due,
        "status": "open", "priority": "medium", "notes": "", "user_id": user}) or setattr(s, "next_id", s.next_id + 1)
    return s


OPP = SimpleNamespace(role_title="Intern", company_name="Acme")


def _app(status, deadline=None, submitted_at=None, app_id=7):
    return SimpleNamespace(id=app_id, status=status, target_deadline=deadline, submitted_at=submitted_at)


async def _run(app, status_changed=False, deadline_changed=False, user=USER):
    await sync.sync_application_tasks(user, app, OPP, status_changed=status_changed, deadline_changed=deadline_changed)


def _by(store, prefix):
    return [t for t in store.tasks if t["title"].startswith(prefix)]


@pytest.mark.asyncio
async def test_applied_creates_one_followup_and_completes_apply(store):
    store.add_apply()
    applied_at = datetime(2030, 1, 5, 9, 0, tzinfo=timezone.utc)
    app = _app("SUBMITTED", submitted_at=applied_at)
    await _run(app, status_changed=True)
    follow = _by(store, "Follow up:")
    assert len(follow) == 1
    assert follow[0]["title"] == "Follow up: Intern at Acme"
    assert follow[0]["due_date"] == date(2030, 1, 5) + timedelta(days=14)
    assert _by(store, "Apply:")[0]["status"] == "done"
    # A second save (same state, even with a deadline change) never duplicates.
    await _run(app, status_changed=True, deadline_changed=True)
    await _run(app, status_changed=True)
    assert len(_by(store, "Follow up:")) == 1
    assert len(_by(store, "Apply:")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", ["CLOSED", "REJECTED", "WITHDRAWN"])
async def test_closed_completes_both_without_deleting(store, closing):
    store.add_apply()
    await _run(_app("SUBMITTED", submitted_at=datetime.now(timezone.utc)), status_changed=True)
    await _run(_app(closing), status_changed=True)
    assert [t["status"] for t in store.tasks] == ["done", "done"]
    assert len(store.tasks) == 2


@pytest.mark.asyncio
async def test_deadline_change_updates_open_apply_due_date(store):
    store.add_apply()
    await _run(_app("READY_FOR_REVIEW", deadline=date(2030, 2, 1)), deadline_changed=True)
    assert _by(store, "Apply:")[0]["due_date"] == date(2030, 2, 1)
    assert _by(store, "Follow up:") == []


@pytest.mark.asyncio
async def test_other_users_tasks_untouched(store):
    store.add_apply(user=OTHER)
    await _run(_app("SUBMITTED", submitted_at=datetime.now(timezone.utc)), status_changed=True)
    assert _by(store, "Apply:")[0]["status"] == "open"
    assert all(t["user_id"] == USER for t in _by(store, "Follow up:"))


@pytest.mark.asyncio
async def test_no_change_means_no_task_work(store):
    store.add_apply()
    await _run(_app("SUBMITTED", submitted_at=datetime.now(timezone.utc)))
    assert _by(store, "Follow up:") == []
    assert _by(store, "Apply:")[0]["status"] == "open"


@pytest.mark.asyncio
async def test_patch_endpoint_triggers_sync(monkeypatch):
    """The PATCH handler passes the saved application to the sync with the right change flags."""
    from backend.models_career import CareerApplicationOut, CareerApplicationStatus, UpdateApplicationStatusRequest
    from backend.routers import career as router

    existing = CareerApplicationOut(id=7, user_id=USER, opportunity_id=3, status=CareerApplicationStatus.READY_FOR_REVIEW)
    saved = existing.model_copy(update={"status": CareerApplicationStatus.SUBMITTED})
    calls = []

    async def get_app(app_id, user_id):
        return existing

    async def upd(app_id, user_id, updates):
        return saved

    async def opp(_id, _user):
        return OPP

    async def log(*a, **k):
        return None

    async def fake_sync(user_id, app, o, **kw):
        calls.append((user_id, app.status, kw))

    monkeypatch.setattr(router, "get_career_application_by_id", get_app)
    monkeypatch.setattr(router, "update_career_application", upd)
    monkeypatch.setattr(router, "get_opportunity_by_id", opp)
    monkeypatch.setattr(router, "log_application_event", log)
    monkeypatch.setattr(router, "_get_or_create_user_id", lambda request: USER)
    monkeypatch.setattr(sync, "sync_application_tasks", fake_sync)

    await router.update_application_endpoint(7, UpdateApplicationStatusRequest(status="SUBMITTED"), object())
    assert calls and calls[0][0] == USER
    assert calls[0][2]["status_changed"] is True


@pytest.mark.asyncio
async def test_mark_applied_endpoint_triggers_sync(monkeypatch):
    """"Yes, applied" (mark-applied) creates the follow-up through the same sync."""
    from backend.models_career import CareerApplicationOut, CareerApplicationStatus
    from backend.routers import career as router

    existing = CareerApplicationOut(id=7, user_id=USER, opportunity_id=3, status=CareerApplicationStatus.READY_FOR_REVIEW)
    saved = existing.model_copy(update={"status": CareerApplicationStatus.SUBMITTED})
    calls = []

    async def get_app(app_id, user_id):
        return existing

    async def upd(app_id, user_id, changes):
        return saved

    async def opp(_id, _user):
        return OPP

    async def log(*a, **k):
        return None

    async def fake_sync(user_id, app, o, **kw):
        calls.append((user_id, app.status, kw))

    monkeypatch.setattr(router, "get_career_application_by_id", get_app)
    monkeypatch.setattr(router, "update_career_application", upd)
    monkeypatch.setattr(router, "get_opportunity_by_id", opp)
    monkeypatch.setattr(router, "log_application_event", log)
    monkeypatch.setattr(router, "_get_or_create_user_id", lambda request: USER)
    monkeypatch.setattr(sync, "sync_application_tasks", fake_sync)

    await router.mark_application_applied_endpoint(7, object())
    assert calls and calls[0][2]["status_changed"] is True
