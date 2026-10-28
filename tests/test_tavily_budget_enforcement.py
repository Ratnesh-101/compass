"""Tavily budget enforcement: per-run, per-identity daily and global caps.

Real Postgres (tavily_usage_log); the Tavily HTTP client is stubbed so nothing hits the network.
"""

import json
import uuid
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from backend.config import get_settings
from backend.main import app
from backend.memory.db import get_pool
from backend.services import budget_context, budgets
from backend.services import tavily as tavily_service
from backend.services import tavily_pipeline
from backend.services.budget_context import BudgetIdentity
from backend.services.budgets import BudgetExceededError


class FakeTavilyClient:
    def __init__(self):
        self.search_calls = 0
        self.extract_calls = 0
        self.fail = False

    async def search(self, **kwargs):
        if self.fail:
            raise RuntimeError("tavily down")
        self.search_calls += 1
        return {"results": [{"title": "T", "url": f"https://example.com/{self.search_calls}", "content": "c", "score": 0.9}]}

    async def extract(self, urls, extract_depth="basic"):
        if self.fail:
            raise RuntimeError("tavily down")
        self.extract_calls += 1
        return {"results": [{"url": u, "raw_content": "body"} for u in urls]}


async def _clear_log():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tavily_usage_log")


@pytest.fixture
async def stub(monkeypatch):
    client = FakeTavilyClient()
    monkeypatch.setattr(tavily_service, "_client", client)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    settings = get_settings()
    monkeypatch.setattr(settings, "COMPASS_KILL_SWITCH_ACTIVE", False)
    monkeypatch.delenv("COMPASS_KILL_SWITCH_ACTIVE", raising=False)
    monkeypatch.setattr(settings, "GLOBAL_DAILY_TAVILY_CREDIT_CAP", 100)
    await _clear_log()
    yield client
    await _clear_log()


@contextmanager
def caller(identity_id, *, guest=False, admin=False, run_counter=False):
    id_token = budget_context.bind_identity(BudgetIdentity(identity_id, is_guest=guest, is_admin=admin))
    run_token = budget_context.begin_run_counter() if run_counter else None
    try:
        yield
    finally:
        if run_token is not None:
            budget_context.end_run_counter(run_token)
        budget_context.reset_identity(id_token)


def _uid(prefix="test_budget"):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _credits_for(identity):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if identity is None:
            return await conn.fetchval("SELECT COALESCE(SUM(credits),0) FROM tavily_usage_log WHERE identity IS NULL")
        return await conn.fetchval("SELECT COALESCE(SUM(credits),0) FROM tavily_usage_log WHERE identity = $1", identity)


# --------------------------------------------------------------------------- per-run


async def test_per_run_cap_stops_the_seventh_credit(stub):
    with caller(_uid(), run_counter=True):
        for _ in range(budgets.MAX_RUN_TAVILY_CREDITS):
            await tavily_service.search("q")
        with pytest.raises(BudgetExceededError) as exc:
            await tavily_service.search("q")
    assert exc.value.budget_type == "tavily_credits"
    assert stub.search_calls == budgets.MAX_RUN_TAVILY_CREDITS


async def test_per_run_cap_counts_advanced_search_as_two_credits(stub):
    with caller(_uid(), run_counter=True):
        for _ in range(3):
            await tavily_service.search("q", search_depth="advanced")  # 3 x 2 = 6
        with pytest.raises(BudgetExceededError):
            await tavily_service.search("q")
    assert stub.search_calls == 3


async def test_failed_call_releases_run_reservation(stub):
    stub.fail = True
    with caller(_uid(), run_counter=True):
        with pytest.raises(RuntimeError):
            await tavily_service.search("q")
        assert budget_context.run_credits_used() == 0


async def test_extract_settles_run_credits_against_real_usage(stub):
    with caller(_uid(), run_counter=True):
        await tavily_service.extract(["https://a.example", "https://b.example"])  # 1 credit
        assert budget_context.run_credits_used() == 1


# --------------------------------------------------------------------------- per-identity daily


async def test_guest_stops_at_daily_guest_limit(stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "TAVILY_DAILY_GUEST_CREDITS", 8)
    guest = _uid("guest")
    with caller(guest, guest=True):
        for _ in range(8):
            await tavily_service.search("q")
        with pytest.raises(HTTPException) as exc:
            await tavily_service.search("q")
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "tavily_budget_exceeded"
    assert int(exc.value.headers["Retry-After"]) >= 1
    assert stub.search_calls == 8


async def test_user_stops_at_daily_user_limit(stub):
    user = _uid()
    with caller(user):
        for _ in range(budgets.MAX_DAILY_USER_TAVILY_CREDITS):
            await tavily_service.search("q")
        with pytest.raises(HTTPException) as exc:
            await tavily_service.search("q")
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "tavily_budget_exceeded"
    assert stub.search_calls == budgets.MAX_DAILY_USER_TAVILY_CREDITS


async def test_admin_is_not_limited_per_identity(stub):
    with caller("admin", admin=True):
        for _ in range(budgets.MAX_DAILY_USER_TAVILY_CREDITS + 5):
            await tavily_service.search("q")
    assert stub.search_calls == budgets.MAX_DAILY_USER_TAVILY_CREDITS + 5


async def test_one_identity_does_not_block_another(stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "TAVILY_DAILY_GUEST_CREDITS", 8)
    first, second = _uid("guest"), _uid("guest")
    with caller(first, guest=True):
        for _ in range(8):
            await tavily_service.search("q")
        with pytest.raises(HTTPException):
            await tavily_service.search("q")
    with caller(second, guest=True):
        await tavily_service.search("q")  # unaffected by the first guest's usage
    assert await _credits_for(second) == 1


async def test_check_daily_identity_budget_filters_by_identity(stub):
    other, me = _uid(), _uid()
    with caller(other):
        for _ in range(budgets.MAX_DAILY_USER_TAVILY_CREDITS):
            await tavily_service.search("q")
    await budgets.check_daily_identity_budget(user_id=me)  # other user's usage must not count
    with pytest.raises(HTTPException):
        await budgets.check_daily_identity_budget(user_id=other)


async def test_previous_day_and_legacy_null_rows_do_not_count(stub):
    user = _uid()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tavily_usage_log (operation, credits, identity, created_at) VALUES ('search', 50, $1, now() - interval '2 days')",
            user,
        )
        await conn.execute("INSERT INTO tavily_usage_log (operation, credits, identity) VALUES ('search', 20, NULL)")
    with caller(user):
        await tavily_service.search("q")
    assert stub.search_calls == 1


async def test_identity_query_error_fails_open_with_warning(stub, monkeypatch, caplog):
    async def boom(identity_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(budgets, "_identity_credits_today", boom)
    with caplog.at_level("WARNING", logger="compass.budgets"):
        with caller(_uid(), guest=True):
            await tavily_service.search("q")
    assert stub.search_calls == 1
    assert any("daily Tavily budget" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)


async def test_default_guest_cap_is_25_and_user_cap_is_30(stub, monkeypatch):
    from backend.config import Settings

    monkeypatch.delenv("TAVILY_DAILY_GUEST_CREDITS", raising=False)
    monkeypatch.delenv("TAVILY_DAILY_USER_CREDITS", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.TAVILY_DAILY_GUEST_CREDITS == 25
    assert defaults.TAVILY_DAILY_USER_CREDITS == 30
    assert budgets.MAX_DAILY_GUEST_TAVILY_CREDITS == 25
    with caller(_uid("guest"), guest=True):
        for _ in range(25):
            await tavily_service.search("q")
        with pytest.raises(HTTPException) as exc:
            await tavily_service.search("q")
    assert "25 credits" in exc.value.detail["message"]
    assert stub.search_calls == 25


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "2.5", ""])
def test_invalid_daily_credit_env_falls_back_to_default_with_warning(monkeypatch, caplog, bad):
    from backend.config import Settings

    monkeypatch.setenv("TAVILY_DAILY_GUEST_CREDITS", bad)
    monkeypatch.setenv("TAVILY_DAILY_USER_CREDITS", bad)
    with caplog.at_level("WARNING", logger="compass.config"):
        s = Settings(_env_file=None)
    assert s.TAVILY_DAILY_GUEST_CREDITS == 25
    assert s.TAVILY_DAILY_USER_CREDITS == 30
    assert any("TAVILY_DAILY_GUEST_CREDITS" in r.getMessage() for r in caplog.records)


def test_valid_daily_credit_env_is_honoured(monkeypatch):
    from backend.config import Settings

    monkeypatch.setenv("TAVILY_DAILY_GUEST_CREDITS", "12")
    assert Settings(_env_file=None).TAVILY_DAILY_GUEST_CREDITS == 12


async def test_live_setting_below_one_cannot_disable_cap(stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "TAVILY_DAILY_GUEST_CREDITS", 0)
    assert budgets._daily_tavily_limit(True) == 25


# --------------------------------------------------------------------------- recording / global


async def test_identity_is_recorded_in_usage_log(stub):
    user = _uid()
    with caller(user):
        await tavily_service.search("q")
        await tavily_service.extract(["https://a.example"])
    assert await _credits_for(user) == 2


async def test_no_identity_jobs_only_face_global_cap(stub, monkeypatch):
    for _ in range(budgets.MAX_DAILY_USER_TAVILY_CREDITS + 3):  # beyond any per-identity limit
        await tavily_service.search("q")
    assert await _credits_for(None) == budgets.MAX_DAILY_USER_TAVILY_CREDITS + 3
    monkeypatch.setattr(get_settings(), "GLOBAL_DAILY_TAVILY_CREDIT_CAP", 5)
    calls = stub.search_calls
    with pytest.raises(HTTPException) as exc:
        await tavily_service.search("q")
    assert exc.value.status_code == 429
    assert stub.search_calls == calls


async def test_global_cap_blocks_even_a_fresh_identity(stub, monkeypatch):
    with caller(_uid()):
        await tavily_service.search("q")
        await tavily_service.search("q")
    monkeypatch.setattr(get_settings(), "GLOBAL_DAILY_TAVILY_CREDIT_CAP", 2)
    with caller(_uid()):
        with pytest.raises(HTTPException) as exc:
            await tavily_service.search("q")
    assert exc.value.status_code == 429


async def test_kill_switch_blocks_before_spending(stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "COMPASS_KILL_SWITCH_ACTIVE", True)
    with caller(_uid()):
        with pytest.raises(HTTPException) as exc:
            await tavily_service.search("q")
    assert exc.value.status_code == 503
    assert stub.search_calls == 0


# --------------------------------------------------------------------------- callers degrade gracefully


async def test_research_pipeline_returns_capped_result_not_exception(stub, monkeypatch):
    monkeypatch.setattr(get_settings(), "TAVILY_DAILY_GUEST_CREDITS", 8)
    async def fake_decompose(query):
        return ["alpha query", "beta query"]

    monkeypatch.setattr(tavily_pipeline, "decompose_query", fake_decompose)
    monkeypatch.setattr(tavily_pipeline, "_RAW_SEARCH_CACHE", {})
    monkeypatch.setattr(tavily_pipeline, "tavily_available", lambda: True)
    guest = _uid("guest")
    with caller(guest, guest=True):
        for _ in range(8):
            await tavily_service.search("q")
        result = await tavily_pipeline.run_tavily_research("some capped research query")
    assert result["capped"] is True
    assert result["verdict"] == "NOT_FOUND"
    assert "capped" in result["summary"].lower()


async def test_search_web_skill_returns_failure_dict_when_capped(stub, monkeypatch):
    from backend.skills import handle_search_web

    monkeypatch.setattr(get_settings(), "TAVILY_DAILY_GUEST_CREDITS", 8)
    with caller(_uid("guest"), guest=True):
        for _ in range(8):
            await tavily_service.search("q")
        res = await handle_search_web({"query": "anything"}, pool=None)
    assert res["success"] is False


async def test_research_pipeline_does_not_leak_its_run_counter(stub, monkeypatch):
    async def fake_decompose(query):
        return ["only query"]

    monkeypatch.setattr(tavily_pipeline, "decompose_query", fake_decompose)
    monkeypatch.setattr(tavily_pipeline, "_RAW_SEARCH_CACHE", {})
    monkeypatch.setattr(tavily_pipeline, "tavily_available", lambda: True)
    assert budget_context.run_credits_used() is None
    await tavily_pipeline.run_tavily_research("a query")
    assert budget_context.run_credits_used() is None


# --------------------------------------------------------------------------- middleware / SSE


@pytest.fixture
async def http():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=15.0) as ac:
        yield ac


async def test_identity_and_run_counter_visible_inside_sse_stream(stub, http, monkeypatch):
    import backend.services.chat_stream as chat_stream

    user = _uid()
    seen = {}

    async def fake_events(req, request, user_id=None, guest_id=None):
        ident = budget_context.get_identity()
        seen["identity"] = ident.identity_id if ident else None
        seen["counter"] = budget_context.run_credits_used()
        yield ": ping\n\n"
        outcome = "ok"
        try:
            for _ in range(budgets.MAX_RUN_TAVILY_CREDITS + 1):
                await tavily_service.search("q")
        except BudgetExceededError:
            outcome = "run_capped"
        yield f"data: {json.dumps({'type': 'done', 'outcome': outcome})}\n\n"

    monkeypatch.setattr(chat_stream, "generate_chat_events", fake_events)
    resp = await http.post("/api/chat/stream", json={"message": "hello"}, headers={"x-user-id": user})
    assert resp.status_code == 200
    assert '"outcome": "run_capped"' in resp.text
    assert seen == {"identity": user, "counter": 0}
    assert stub.search_calls == budgets.MAX_RUN_TAVILY_CREDITS
    assert await _credits_for(user) == budgets.MAX_RUN_TAVILY_CREDITS


async def test_identity_visible_in_plain_route_and_unauthenticated_request_is_not_a_500(stub, http, monkeypatch):
    import backend.dependencies as deps

    resp = await http.post("/api/chat/stream", json={"message": "hello"})
    assert resp.status_code == 401  # no identity: route auth answers, middleware stays out of the way

    def explode(request):
        raise HTTPException(status_code=403, detail="bad headers")

    monkeypatch.setattr(deps, "_get_current_identity", explode)
    resp = await http.get("/health")  # middleware resolver raising must never break the request
    assert resp.status_code == 200
