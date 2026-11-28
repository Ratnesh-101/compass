"""Atomic Tavily budget reservation, fail-closed guests, UTC/global caps, guest share, verifier allowance, cache.

No network and no database: the DB layer is an in-memory fake pool that emulates
pg_advisory_xact_lock (held until the transaction ends) and the few SQL shapes budgets.py uses.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from backend.config import get_settings
from backend.models_career import ResumeContent, ResumeExperienceItem
from backend.services import budget_context, budgets
from backend.services import claim_verifier as cv
from backend.services import tavily as tavily_service
from backend.services.budget_context import BudgetIdentity
from backend.services.budgets import BudgetExceededError


# ------------------------------------------------------------------ fake DB

class FakeDB:
    def __init__(self):
        self.rows: list[dict] = []
        self.locks: dict[str, asyncio.Lock] = {}
        self.next_id = 1
        self.fail = False

    def pool(self):
        return FakePool(self)

    def total(self, identity=None, guest=False):
        return sum(
            r["credits"] for r in self.rows
            if (identity is None or r["identity"] == identity)
            and (not guest or r["operation"].endswith(":guest"))
        )

    def seed(self, credits, identity="seed", operation="search"):
        self.rows.append({"id": self.next_id, "operation": operation, "credits": credits, "identity": identity})
        self.next_id += 1


class FakePool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        return _Acquire(self.db)


class _Acquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        if self.db.fail:
            raise ConnectionError("db down")
        return FakeConn(self.db)

    async def __aexit__(self, *a):
        return False


class _Txn:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        for lock in self.conn.held:
            lock.release()
        self.conn.held.clear()
        return False


class FakeConn:
    def __init__(self, db):
        self.db = db
        self.held: list[asyncio.Lock] = []

    def transaction(self):
        return _Txn(self)

    async def execute(self, sql, *args):
        if "pg_advisory_xact_lock" in sql:
            lock = self.db.locks.setdefault(args[0], asyncio.Lock())
            await lock.acquire()
            self.held.append(lock)
        elif sql.startswith("DELETE"):
            self.db.rows = [r for r in self.db.rows if r["id"] != args[0]]
        elif sql.startswith("UPDATE"):
            for r in self.db.rows:
                if r["id"] == args[0]:
                    r["credits"] = args[1]

    async def fetchval(self, sql, *args):
        await asyncio.sleep(0)  # yield so unlocked code would interleave
        if sql.startswith("INSERT"):
            self.db.seed(args[1], identity=args[2], operation=args[0])
            return self.db.rows[-1]["id"]
        if "identity = $1" in sql:
            return self.db.total(identity=args[0])
        if "operation LIKE" in sql:
            return self.db.total(guest=True)
        return self.db.total()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    pool = fake.pool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(budgets, "get_pool", _get_pool)
    settings = get_settings()
    monkeypatch.setattr(settings, "COMPASS_KILL_SWITCH_ACTIVE", False)
    monkeypatch.delenv("COMPASS_KILL_SWITCH_ACTIVE", raising=False)
    monkeypatch.setattr(settings, "GLOBAL_DAILY_TAVILY_CREDIT_CAP", 100)
    monkeypatch.setattr(settings, "TAVILY_DAILY_USER_CREDITS", 3)
    monkeypatch.setattr(settings, "TAVILY_DAILY_GUEST_CREDITS", 3)
    monkeypatch.setattr(type(settings), "is_production", lambda self: False)
    return fake


@contextmanager
def caller(identity_id, *, guest=False, run_counter=False):
    tok = budget_context.bind_identity(BudgetIdentity(identity_id, is_guest=guest))
    run = budget_context.begin_run_counter() if run_counter else None
    try:
        yield
    finally:
        if run is not None:
            budget_context.end_run_counter(run)
        budget_context.reset_identity(tok)


# ------------------------------------------------------------------ reserve / settle

async def test_five_concurrent_reserves_with_limit_three_admit_exactly_three(db):
    with caller("user-1"):
        results = await asyncio.gather(
            *[budgets.reserve_tavily_credits(1) for _ in range(5)], return_exceptions=True
        )
    ok = [r for r in results if isinstance(r, budgets.TavilyReservation)]
    denied = [r for r in results if isinstance(r, HTTPException)]
    assert len(ok) == 3 and len(denied) == 2
    assert all(d.detail["code"] == "tavily_budget_exceeded" for d in denied)
    assert db.total("user-1") == 3


async def test_settle_zero_refunds_and_settle_adjusts(db):
    with caller("user-2"):
        res = await budgets.reserve_tavily_credits(2)
        assert db.total("user-2") == 2
        await budgets.settle_tavily_reservation(res, 0)
        assert db.total("user-2") == 0
        res = await budgets.reserve_tavily_credits(2)
        await budgets.settle_tavily_reservation(res, 1)
        assert db.total("user-2") == 1


async def test_failed_search_refunds_reservation_and_run_credits(db, monkeypatch):
    class Boom:
        async def search(self, **kw):
            raise RuntimeError("down")

    monkeypatch.setattr(tavily_service, "_client", Boom())
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    tavily_service.clear_search_cache()
    with caller("user-3", run_counter=True):
        with pytest.raises(RuntimeError):
            await tavily_service.search("q fail")
        assert budget_context.run_credits_used() == 0
    assert db.total("user-3") == 0


async def test_denied_reserve_does_not_call_tavily(db, monkeypatch):
    calls = []

    class Client:
        async def search(self, **kw):
            calls.append(kw)
            return {"results": []}

    monkeypatch.setattr(tavily_service, "_client", Client())
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    tavily_service.clear_search_cache()
    db.seed(3, identity="user-4")
    with caller("user-4"):
        with pytest.raises(HTTPException):
            await tavily_service.search("q denied")
    assert calls == []


# ------------------------------------------------------------------ fail closed / open

async def test_guest_db_error_denies_with_friendly_message(db):
    db.fail = True
    with caller("guest-1", guest=True):
        with pytest.raises(HTTPException) as exc:
            await budgets.reserve_tavily_credits(1)
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "tavily_budget_exceeded"


async def test_guest_identity_check_db_error_denies(db, monkeypatch):
    async def boom(identity_id):
        raise ConnectionError("db down")

    monkeypatch.setattr(budgets, "_identity_credits_today", boom)
    with pytest.raises(HTTPException) as exc:
        await budgets.check_daily_identity_budget(guest_id="guest-x", cost=1)
    assert exc.value.detail["code"] == "tavily_budget_exceeded"


async def test_user_db_error_allows_with_warning(db, caplog, monkeypatch):
    db.fail = True
    with caplog.at_level("WARNING", logger="compass.budgets"):
        with caller("user-5", run_counter=True):
            res = await budgets.reserve_tavily_credits(1)
            assert res is not None and res.row_id is None
            assert budget_context.run_credits_used() == 1

        async def boom(identity_id):
            raise ConnectionError("db down")

        monkeypatch.setattr(budgets, "_identity_credits_today", boom)
        await budgets.check_daily_identity_budget(user_id="user-5", cost=1)  # does not raise
    assert "Could not" in caplog.text


# ------------------------------------------------------------------ global cap / guest share

async def test_global_check_denies_when_used_plus_cost_exceeds_cap(db):
    db.seed(98)
    with pytest.raises(HTTPException) as exc:
        await budgets.check_global_spend_cap(db.pool(), cost=3)
    assert exc.value.status_code == 429
    await budgets.check_global_spend_cap(db.pool(), cost=2)  # 98 + 2 == cap: allowed

    with caller("user-6"):
        with pytest.raises(HTTPException):
            await budgets.reserve_tavily_credits(3)
        assert await budgets.reserve_tavily_credits(2) is not None


async def test_guests_together_cannot_exceed_their_share(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "TAVILY_DAILY_GUEST_CREDITS", 100)
    db.seed(59, identity="other-guest", operation="search:guest")
    with caller("guest-2", guest=True):
        with pytest.raises(HTTPException) as exc:
            await budgets.reserve_tavily_credits(2)
        assert exc.value.status_code == 429
        assert await budgets.reserve_tavily_credits(1) is not None  # 60 == 60% of 100
        with pytest.raises(HTTPException):
            await budgets.reserve_tavily_credits(1)
    with caller("user-7"):  # the remainder stays available to signed-in users
        monkeypatch.setattr(get_settings(), "TAVILY_DAILY_USER_CREDITS", 30)
        assert await budgets.reserve_tavily_credits(3) is not None


# ------------------------------------------------------------------ claim verifier

def _eleven_claims_content() -> ResumeContent:
    names = ["Northwind", "Bluefin", "Harbor", "Zephyr", "Quillon", "Ridgeway",
             "Tamarind", "Oakridge", "Sunbeam", "Lakeshore", "Meridian", "Foxglove"]
    return ResumeContent(
        full_name="Asha Verma",
        email="asha@example.com",
        experience=[ResumeExperienceItem(company=f"{n} Labs Pvt Ltd", role_title="Developer") for n in names[:6]],
        internships=[ResumeExperienceItem(company=f"{n} Systems Inc", role_title="Intern") for n in names[6:11]],
    )


async def test_verifier_with_many_claims_never_says_unavailable_for_skipped(monkeypatch):
    content = _eleven_claims_content()
    n_claims = len(cv.extract_claims(content))
    assert n_claims >= 8
    calls = {"n": 0}

    async def search(query, max_results=5, search_depth="basic"):
        calls["n"] += 1
        if calls["n"] > 6:
            raise BudgetExceededError("run cap", "tavily_credits", 6, 7)
        return {"results": []}

    report = await cv.verify_claims(content, search=search)
    assert report.tavily_used is True
    assert "not available" not in report.notice.lower()
    assert "the rest were not checked" in report.notice
    for c in report.checks:
        assert "not available" not in c.note.lower() and "unavailable" not in c.note.lower()
    skipped = [c for c in report.checks if c.status == "cannot_check" and "not checked online" in c.note.lower()]
    assert len(skipped) == n_claims - 6


async def test_verifier_has_own_twelve_credit_allowance_and_reuses_report(monkeypatch):
    content = _eleven_claims_content()
    cv._report_cache.clear()
    seen = {"n": 0, "limit": None}

    async def search(query, max_results=5, search_depth="basic"):
        seen["n"] += 1
        seen["limit"] = budgets._run_limit()
        return {"results": []}

    monkeypatch.setattr(cv, "default_tavily_search", search)
    monkeypatch.setattr(cv, "tavily_available", lambda: True)
    first = await cv.verify_claims(content)
    n_after_first = seen["n"]
    assert seen["limit"] == cv.VERIFIER_RUN_CREDITS == 12
    second = await cv.verify_claims(content)
    assert seen["n"] == n_after_first  # identical claim set: no new searches
    assert second is first


# ------------------------------------------------------------------ search cache

@pytest.fixture
def clock(monkeypatch):
    state = {"t": 1000.0}
    monkeypatch.setattr(tavily_service, "_cache_now", lambda: state["t"])
    tavily_service.clear_search_cache()
    yield state
    tavily_service.clear_search_cache()


@pytest.fixture
def counting_client(db, monkeypatch):
    class Client:
        def __init__(self):
            self.calls = 0

        async def search(self, **kw):
            self.calls += 1
            return {"results": [{"url": f"https://e.example/{self.calls}", "content": "c"}]}

    c = Client()
    monkeypatch.setattr(tavily_service, "_client", c)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    return c


async def test_identical_query_served_from_cache_without_second_call(counting_client, clock, db):
    a = await tavily_service.search("Riverbend  Institute", include_domains=["B.com", "a.com"])
    b = await tavily_service.search("riverbend institute", include_domains=["a.com", "b.com"])
    assert counting_client.calls == 1
    assert a == b
    assert db.total() == 1  # credits spent once
    await tavily_service.search("riverbend institute", search_depth="advanced")  # different depth: new call
    assert counting_client.calls == 2


async def test_cache_expires_after_ttl(counting_client, clock):
    await tavily_service.search("ttl query")
    clock["t"] += tavily_service.SEARCH_CACHE_TTL_S - 1
    await tavily_service.search("ttl query")
    assert counting_client.calls == 1
    clock["t"] += 2
    await tavily_service.search("ttl query")
    assert counting_client.calls == 2


def test_cache_evicts_least_recently_used_beyond_200(clock):
    keys = [tavily_service._cache_key(f"q{i}", "basic", "general", 5, None) for i in range(200)]
    for k in keys:
        tavily_service._cache_put(k, {"results": []})
    assert tavily_service._cache_get(keys[0]) is not None  # touch: becomes most recent
    tavily_service._cache_put(tavily_service._cache_key("q-new", "basic", "general", 5, None), {"results": []})
    assert len(tavily_service._search_cache) == 200
    assert tavily_service._cache_get(keys[0]) is not None
    assert tavily_service._cache_get(keys[1]) is None  # least recently used was evicted
