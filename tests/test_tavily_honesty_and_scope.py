"""Tavily handlers: owner scoping, honest 'could not check' verdicts, error hygiene, clamps, sanitising."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.services import tavily as tavily_service
from backend.services import tavily_pipeline
from backend.services.budgets import BudgetExceededError
from backend.services.web_answer import sanitize_md_text
from backend.skills.handlers import web as web_handlers

FAKE_SECRET = "tvly-SECRET-0123456789"
BUDGET_MSG = "Could not check online right now (daily online-check limit reached; try again after 05:30 IST)."
UNAVAILABLE_MSG = "Online checking is not available right now."


def _pool():
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = AsyncMock()
    return pool


def _all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _all_strings(k)
            yield from _all_strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _all_strings(v)


def _no_secret(res):
    blob = json.dumps(res, default=str)
    assert FAKE_SECRET not in blob
    assert "SECRET" not in blob


# ------------------------------------------------------------------ (1) owner scoping


async def test_verify_deadline_other_owner_cannot_read_task(monkeypatch):
    task = {"id": 7, "title": "Private plan", "due_date": "2026-09-17", "user_id": "owner-B", "notes": "secret notes"}
    monkeypatch.setattr("backend.memory.structured.get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    search = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(tavily_service, "search", search)

    res = await web_handlers.handle_verify_deadline({"task_id": 7, "user_id": "owner-A"}, pool=_pool())

    assert res["success"] is False
    assert res["data"] == {}
    assert res["response"] == "Task not found"
    blob = json.dumps(res, default=str)
    assert "Private plan" not in blob and "secret notes" not in blob and "owner-B" not in blob
    search.assert_not_called()


async def test_verify_deadline_missing_caller_gets_not_found(monkeypatch):
    task = {"id": 7, "title": "Private plan", "user_id": "owner-B"}
    monkeypatch.setattr("backend.memory.structured.get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    res = await web_handlers.handle_verify_deadline({"task_id": 7}, pool=_pool())
    assert res["success"] is False and res["data"] == {}
    assert "Private plan" not in json.dumps(res, default=str)


async def test_verify_deadline_owner_can_read_own_task(monkeypatch):
    task = {"id": 7, "title": "Mine", "due_date": "2026-09-17", "user_id": "owner-A"}
    monkeypatch.setattr("backend.memory.structured.get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "search", AsyncMock(return_value={"results": []}))
    res = await web_handlers.handle_verify_deadline({"task_id": 7, "user_id": "owner-A"}, pool=_pool())
    assert res["success"] is True
    assert res["data"]["task"]["id"] == 7


async def test_verify_deadline_unavailable_checked_before_db_and_leaks_nothing(monkeypatch):
    get_task = AsyncMock(return_value={"id": 7, "title": "Private plan", "user_id": "owner-B"})
    monkeypatch.setattr("backend.memory.structured.get_task", get_task)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: False)
    pool = _pool()
    res = await web_handlers.handle_verify_deadline({"task_id": 7, "user_id": "owner-A"}, pool=pool)
    get_task.assert_not_called()
    pool.acquire.assert_not_called()
    assert res["success"] is False
    assert "task" not in res["data"]
    assert res["response"] == UNAVAILABLE_MSG
    assert "Private plan" not in json.dumps(res, default=str)


# ------------------------------------------------------------------ (2) honesty


async def test_pipeline_unconfigured_is_could_not_check(monkeypatch):
    monkeypatch.setattr(tavily_pipeline, "tavily_available", lambda: False)
    res = await tavily_pipeline._run_tavily_research("some claim")
    assert res["verdict"] == "COULD_NOT_CHECK"
    assert res["reason"] == "unavailable"
    assert res["summary"] == UNAVAILABLE_MSG


async def test_pipeline_budget_capped_is_could_not_check(monkeypatch):
    monkeypatch.setattr(tavily_pipeline, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_pipeline, "_RAW_SEARCH_CACHE", {})
    monkeypatch.setattr(tavily_pipeline, "decompose_query", AsyncMock(return_value=["q1"]))

    async def capped(sub_queries, include_domains=None, max_credits=4, capped_out=None, errors_out=None):
        capped_out.append("daily cap")
        return [], 0

    monkeypatch.setattr(tavily_pipeline, "execute_subqueries", capped)
    res = await tavily_pipeline._run_tavily_research("some claim")
    assert res["verdict"] == "COULD_NOT_CHECK"
    assert res["reason"] == "budget"
    assert res["summary"] == BUDGET_MSG


async def test_pipeline_search_errors_are_could_not_check(monkeypatch):
    monkeypatch.setattr(tavily_pipeline, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_pipeline, "_RAW_SEARCH_CACHE", {})
    monkeypatch.setattr(tavily_pipeline, "decompose_query", AsyncMock(return_value=["q1"]))
    monkeypatch.setattr(tavily_pipeline, "tavily_search", AsyncMock(side_effect=RuntimeError(f"boom {FAKE_SECRET}")))
    res = await tavily_pipeline._run_tavily_research("some claim")
    assert res["verdict"] == "COULD_NOT_CHECK"
    assert res["reason"] == "error"
    _no_secret(res)


async def test_pipeline_ran_and_found_nothing_is_still_not_found(monkeypatch):
    monkeypatch.setattr(tavily_pipeline, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_pipeline, "_RAW_SEARCH_CACHE", {})
    monkeypatch.setattr(tavily_pipeline, "decompose_query", AsyncMock(return_value=["q1"]))
    monkeypatch.setattr(tavily_pipeline, "tavily_search", AsyncMock(return_value={"results": []}))
    res = await tavily_pipeline._run_tavily_research("some claim")
    assert res["verdict"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "verdict,reason,expected",
    [
        ("COULD_NOT_CHECK", "budget", BUDGET_MSG),
        ("COULD_NOT_CHECK", "unavailable", UNAVAILABLE_MSG),
        ("COULD_NOT_CHECK", "error", UNAVAILABLE_MSG),
    ],
)
async def test_verify_with_tavily_renders_friendly_message(monkeypatch, verdict, reason, expected):
    pipeline_res = {"verdict": verdict, "reason": reason, "summary": "x", "evidence_ledger": [], "sources": []}
    monkeypatch.setattr(tavily_pipeline, "run_tavily_research", AsyncMock(return_value=pipeline_res))
    res = await web_handlers.handle_verify_with_tavily({"claim": "Hackathon closes on 5 May 2026"}, pool=None)
    assert res["response"] == expected
    assert res["data"]["verdict"] == "COULD_NOT_CHECK"
    assert "NOT_FOUND" not in json.dumps(res, default=str)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (BudgetExceededError("daily cap", "daily", 1, 1), BUDGET_MSG),
        (HTTPException(status_code=429, detail="cap"), BUDGET_MSG),
        (RuntimeError("Tavily is disabled or unconfigured"), UNAVAILABLE_MSG),
        (ValueError("anything"), UNAVAILABLE_MSG),
    ],
)
async def test_search_web_failure_never_not_found(monkeypatch, exc, expected):
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "search", AsyncMock(side_effect=exc))
    res = await web_handlers.handle_search_web({"query": "python docs"}, pool=None)
    assert res["success"] is False
    assert res["response"] == expected
    assert "NOT_FOUND" not in json.dumps(res, default=str)


# ------------------------------------------------------------------ (3) error hygiene


async def test_exception_text_never_reaches_user_strings(monkeypatch):
    boom = RuntimeError(f"upstream 401 key={FAKE_SECRET}")
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "search", AsyncMock(side_effect=boom))
    monkeypatch.setattr(tavily_service, "extract", AsyncMock(side_effect=boom))
    monkeypatch.setattr("backend.memory.structured.get_task", AsyncMock(return_value={"id": 1, "title": "t", "user_id": "u1"}))
    monkeypatch.setattr(tavily_pipeline, "run_tavily_research", AsyncMock(side_effect=boom))
    import backend.services.tavily_research as research

    monkeypatch.setattr(research, "execute_deep_research", AsyncMock(side_effect=boom))
    monkeypatch.setattr("backend.services.security.is_safe_url", lambda u: (True, ""))

    results = [
        await web_handlers.handle_search_web({"query": "python docs"}, pool=None),
        await web_handlers.handle_ingest_url({"url": "https://example.com/a", "user_id": "u1"}, pool=_pool()),
        await web_handlers.handle_verify_deadline({"task_id": 1, "user_id": "u1"}, pool=_pool()),
        await web_handlers.handle_verify_with_tavily({"claim": "Hackathon closes on 5 May 2026"}, pool=None),
        await web_handlers.handle_deep_research({"topic": "python"}, pool=None),
    ]
    for res in results:
        assert res["success"] is False
        _no_secret(res)
        assert all("RuntimeError" not in s and "upstream" not in s for s in _all_strings(res))


async def test_deep_research_wraps_provider_failure_without_upstream_text(monkeypatch):
    import backend.services.tavily_research as research

    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "search", AsyncMock(side_effect=RuntimeError(FAKE_SECRET)))
    monkeypatch.setattr(research, "get_cached_search", lambda *a, **k: None)
    with pytest.raises(RuntimeError) as exc:
        await research.execute_deep_research(topic="python tutorials", max_subqueries=1)
    assert FAKE_SECRET not in str(exc.value)


# ------------------------------------------------------------------ (4) clamps


class _RecordingClient:
    def __init__(self):
        self.kwargs = None

    async def search(self, **kwargs):
        self.kwargs = kwargs
        return {"results": []}


async def _search_with(monkeypatch, **kwargs):
    client = _RecordingClient()
    monkeypatch.setattr(tavily_service, "_client", client)
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "enforce_tavily_budget", AsyncMock())
    monkeypatch.setattr(tavily_service, "record_tavily_credits", AsyncMock())
    await tavily_service.search("q", **kwargs)
    return client.kwargs


async def test_search_clamps_max_results_and_depth(monkeypatch):
    kw = await _search_with(monkeypatch, max_results=500, search_depth="ultra")
    assert kw["max_results"] == 10
    assert kw["search_depth"] == "basic"
    kw = await _search_with(monkeypatch, max_results=-3, search_depth="advanced")
    assert kw["max_results"] == 1
    assert kw["search_depth"] == "advanced"


async def test_search_web_ignores_model_supplied_advanced_depth(monkeypatch):
    seen = {}

    async def fake_search(query, **kwargs):
        seen.update(kwargs)
        return {"results": []}

    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(tavily_service, "search", fake_search)
    await web_handlers.handle_search_web({"query": "python docs", "depth": "advanced", "search_depth": "advanced"}, pool=None)
    assert seen["search_depth"] == "basic"


# ------------------------------------------------------------------ (5) sanitising


def test_sanitize_md_text_neutralises_markup_and_caps_length():
    out = sanitize_md_text("Evil](http://evil) <script>alert(1)</script>\n`x` | y", 120)
    for ch in "[]<>`|\n":
        assert ch not in out
    assert "](" not in out
    assert len(sanitize_md_text("a" * 1000, 120)) == 120


async def test_search_web_title_and_snippet_are_sanitised(monkeypatch):
    evil_title = "Hackathon](http://evil) <script>alert(1)</script>" + "T" * 400
    evil_line = "Submission deadline is 5 May 2026 [click](http://evil) `x` <b>bold</b> | " + "z" * 600
    monkeypatch.setattr(tavily_service, "tavily_available", lambda: True)
    monkeypatch.setattr(
        tavily_service,
        "search",
        AsyncMock(return_value={"results": [{"title": evil_title, "url": "https://example.com/rules", "content": evil_line, "score": 0.9}]}),
    )
    res = await web_handlers.handle_search_web({"query": "hackathon deadline"}, pool=None)
    text = res["response"]
    assert "](http://evil)" not in text
    assert "<script" not in text and "<b>" not in text
    assert "`x`" not in text
    assert all(len(c["title"]) <= 120 for c in res["data"]["citations"])
    assert "](http://evil)" not in json.dumps(res["data"]["citations"])
