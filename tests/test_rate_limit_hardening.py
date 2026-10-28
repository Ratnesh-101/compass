"""Regression tests for rate-limit / budget hardening (shared proxy IP, XFF spoofing,
fail-closed global caps, UTC day keys, atomic first-use token bucket)."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import dependencies
from backend.config import get_settings
from backend.dependencies import Identity
from backend.memory.db import get_pool
from backend.services import budgets, rate_limiter


def make_request(headers: dict[str, str] | None = None, client_host: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "POST", "path": "/x", "headers": raw, "client": (client_host, 1234)})


async def _noop_enforce(*args, **kwargs):
    return None


# --- Item 1: in-memory pre-check must not pool identified users behind one proxy IP ---------

@pytest.mark.asyncio
@pytest.mark.parametrize("dep_name,limit", [("rate_limit", 30), ("agent_rate_limit", 10)])
async def test_identified_users_behind_shared_ip_do_not_share_window(monkeypatch, dep_name, limit):
    dependencies._rate_store.clear()
    dependencies._agent_rate_store.clear()
    monkeypatch.setattr(dependencies, "get_client_ip", lambda r: "76.76.21.21")
    monkeypatch.setattr(rate_limiter, "enforce_rate_limit", _noop_enforce)
    users = {"a": Identity(id="a", user_id="a"), "b": Identity(id="b", user_id="b")}
    monkeypatch.setattr(dependencies, "_get_current_identity", lambda r: users[r.scope["u"]])
    dep = getattr(dependencies, dep_name)

    def req(u):
        r = make_request()
        r.scope["u"] = u
        return r

    for _ in range(limit):
        await dep(req("a"))
    # user b shares the proxy IP but must not be throttled by user a's usage
    await dep(req("b"))
    # user a is still limited on their own window
    with pytest.raises(HTTPException) as exc:
        await dep(req("a"))
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_anonymous_callers_still_limited_per_ip(monkeypatch):
    dependencies._rate_store.clear()
    monkeypatch.setattr(dependencies, "get_client_ip", lambda r: "203.0.113.5")
    monkeypatch.setattr(dependencies, "_get_current_identity", lambda r: None)
    monkeypatch.setattr(rate_limiter, "enforce_rate_limit", _noop_enforce)
    for _ in range(30):
        await dependencies.rate_limit(make_request())
    with pytest.raises(HTTPException) as exc:
        await dependencies.rate_limit(make_request())
    assert exc.value.status_code == 429


# --- Item 2: mint limiter must use trusted get_client_ip, not raw rightmost XFF ----------------

@pytest.mark.asyncio
async def test_mint_rate_limit_uses_get_client_ip_not_raw_xff(monkeypatch):
    seen = []

    async def fake_consume(key, capacity, refill_rate_per_sec, fail_closed=None):
        seen.append(key)
        return True, 0

    async def ok_cap(*a, **k):
        return None

    monkeypatch.setattr(rate_limiter, "_consume_token", fake_consume)
    monkeypatch.setattr(rate_limiter, "get_client_ip", lambda r: "198.51.100.7")
    monkeypatch.setattr("backend.services.budgets.check_global_mint_cap", ok_cap)
    monkeypatch.setattr(dependencies, "_get_current_identity", lambda r: None)
    req = make_request({"x-forwarded-for": "1.2.3.4, 9.9.9.9"})
    await rate_limiter.enforce_mint_rate_limit(req)
    assert seen == ["mint:ip:198.51.100.7"]


# --- Item 3: global caps fail closed in production, open in dev/test -------------------------

class _BoomPool:
    def acquire(self):
        raise RuntimeError("db down")


@pytest.fixture
def budget_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "COMPASS_KILL_SWITCH_ACTIVE", False)
    monkeypatch.delenv("COMPASS_KILL_SWITCH_ACTIVE", raising=False)
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("fn", ["check_global_spend_cap", "check_global_mint_cap"])
async def test_global_caps_fail_closed_in_production(monkeypatch, budget_settings, fn):
    monkeypatch.setattr(budget_settings, "ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as exc:
        await getattr(budgets, fn)(pool=_BoomPool())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("fn", ["check_global_spend_cap", "check_global_mint_cap"])
async def test_global_caps_fail_open_in_test_env(monkeypatch, budget_settings, fn):
    monkeypatch.setattr(budget_settings, "ENVIRONMENT", "test")
    assert await getattr(budgets, fn)(pool=_BoomPool()) is None


@pytest.mark.asyncio
async def test_global_cap_db_error_logged_at_warning(monkeypatch, budget_settings, caplog):
    monkeypatch.setattr(budget_settings, "ENVIRONMENT", "test")
    with caplog.at_level("WARNING", logger="compass.budgets"):
        await budgets.check_global_mint_cap(pool=_BoomPool())
    assert any(r.levelname == "WARNING" for r in caplog.records)


# --- Item 4: UTC day key and retry_after ----------------------------------------------------

def test_identity_daily_cap_uses_utc_day_key(monkeypatch):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 1, 23, 0, 0, tzinfo=timezone.utc)

    import datetime as dtmod
    monkeypatch.setattr(dtmod, "datetime", FakeDT)
    rate_limiter._DAILY_ACTION_USAGE.clear()
    allowed, _ = rate_limiter.check_identity_daily_cap("u1", "act", cap=1)
    assert allowed
    assert list(rate_limiter._DAILY_ACTION_USAGE.keys()) == ["2026-03-01"]
    allowed, retry = rate_limiter.check_identity_daily_cap("u1", "act", cap=1)
    assert not allowed
    assert 3500 <= retry <= 3600


# --- Item 5: atomic first use (real DB) -------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_first_requests_respect_capacity():
    pool = await get_pool()
    if not pool:
        pytest.skip("database unavailable")
    key = f"test_atomic:{uuid.uuid4().hex}"

    async def _hold(barrier_conns):
        async with pool.acquire() as conn:
            barrier_conns.append(conn)
            await asyncio.sleep(0.5)

    # Warm the pool so all workers truly overlap instead of reusing one connection serially.
    await asyncio.gather(*[_hold([]) for _ in range(6)])
    try:
        results = await asyncio.gather(
            *[rate_limiter._consume_token(key, 2.0, 0.0001, fail_closed=True) for _ in range(6)]
        )
        assert sum(1 for ok, _ in results if ok) == 2
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM rate_limit_buckets WHERE key = $1", key)
