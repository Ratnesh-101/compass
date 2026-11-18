"""
Regressions for review fixes X2 (extra chat DB work, dashboard project count, extra-pass usage, shared profile bucket).

No database needed: pools, connections and streams are fakes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.chat_stream_extras import StreamState, load_candidate_profile_context, text_pass_events


# ---------------------------------------------------------------------------
# Task 1: one resume read per chat turn
# ---------------------------------------------------------------------------

class _CountingPool:
    def __init__(self):
        self.acquires = 0
        self.queries = []
        conn = MagicMock()

        async def _fetchrow(sql, *args):
            self.queries.append(sql)
            return None

        conn.fetchrow = _fetchrow
        self._conn = conn

    def acquire(self):
        self.acquires += 1
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool._conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_profile_context_reads_the_master_resume_once(monkeypatch):
    pool = _CountingPool()
    monkeypatch.setattr("backend.memory.radar.get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr("backend.memory.career.get_pool", AsyncMock(return_value=pool))

    assert await load_candidate_profile_context("guest-1") == ""

    resume_reads = [q for q in pool.queries if "FROM resumes" in q]
    assert len(resume_reads) == 1
    assert pool.acquires == 2  # one profile row + one resume read (was 3)


# ---------------------------------------------------------------------------
# Task 2: dashboard project_count is owner scoped
# ---------------------------------------------------------------------------

def _dashboard_conn():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_dashboard_project_count_is_scoped_to_the_caller(monkeypatch):
    from backend.routers import tasks as tasks_router

    pool, conn = _dashboard_conn()
    monkeypatch.setattr(tasks_router, "get_pool", AsyncMock(return_value=pool))
    ident = SimpleNamespace(id="user-a", is_admin=False)
    monkeypatch.setattr(tasks_router, "_get_current_identity", lambda request: ident)

    await tasks_router.get_dashboard(MagicMock(), ref_date=None, include_demo=False, _ident=ident)

    sql, *params = conn.fetch.await_args_list[0].args
    assert "FROM projects" in sql and "tasks" in sql and "$1" in sql
    assert params == ["user-a"]


@pytest.mark.asyncio
async def test_dashboard_project_count_admin_sees_all(monkeypatch):
    from backend.routers import tasks as tasks_router

    pool, conn = _dashboard_conn()
    monkeypatch.setattr(tasks_router, "get_pool", AsyncMock(return_value=pool))
    ident = SimpleNamespace(id="admin", is_admin=True)
    monkeypatch.setattr(tasks_router, "_get_current_identity", lambda request: ident)

    await tasks_router.get_dashboard(MagicMock(), ref_date=None, include_demo=False, _ident=ident)

    sql, *params = conn.fetch.await_args_list[0].args
    assert sql.startswith("SELECT domain, COUNT(*)") and params == []


# ---------------------------------------------------------------------------
# Task 3: extra passes record usage
# ---------------------------------------------------------------------------

class _Delta:
    def __init__(self, content=""):
        self.content = content
        self.tool_calls = None
        self.reasoning = None


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices, usage=None, with_usage_attr=True):
        self.choices = choices
        if with_usage_attr:
            self.usage = usage


class _Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self.chunks:
            yield c

    async def aclose(self):
        pass


def _request():
    r = MagicMock()
    r.is_disconnected = AsyncMock(return_value=False)
    return r


async def _run(chunks):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_Stream(chunks))
    state = StreamState()
    async for _ in text_pass_events(client, {"model": "m-1", "messages": []}, state, _request()):
        pass
    return state, client


@pytest.mark.asyncio
async def test_extra_pass_records_usage_once(monkeypatch):
    record = MagicMock()
    monkeypatch.setattr("backend.services.usage.record_usage", record)
    chunks = [
        _Chunk([_Choice(_Delta("hello"))]),
        _Chunk([_Choice(_Delta(""), "stop")]),
        _Chunk([], usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30)),
    ]
    state, client = await _run(chunks)

    assert (state.prompt_tokens, state.completion_tokens) == (120, 30)
    record.assert_called_once()
    assert record.call_args.args[:3] == ("m-1", 120, 30)
    assert client.chat.completions.create.call_args.kwargs["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_extra_pass_without_usage_does_not_fail_or_record(monkeypatch):
    record = MagicMock()
    monkeypatch.setattr("backend.services.usage.record_usage", record)
    chunks = [
        _Chunk([_Choice(_Delta("hello"))], with_usage_attr=False),
        _Chunk([_Choice(_Delta(""), "stop")], usage=MagicMock()),  # non-numeric usage is ignored
    ]
    state, _ = await _run(chunks)

    assert state.full_text == "hello"
    assert state.prompt_tokens == 0
    record.assert_not_called()


# ---------------------------------------------------------------------------
# Task 4: write handlers refuse callers without an identity
# ---------------------------------------------------------------------------

def _exploding_pool():
    pool = MagicMock()
    pool.acquire.side_effect = AssertionError("must not touch the database without a caller")
    return pool


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [{}, {"user_id": None}, {"user_id": ""}])
async def test_profile_and_parked_writes_reject_missing_user(missing):
    from backend.skills.handlers import parked, profile

    pool = _exploding_pool()
    cases = [
        (profile.handle_remember_fact, {"key": "goal", "value": "x", **missing}),
        (profile.handle_forget_fact, {"key": "goal", **missing}),
        (parked.handle_park_thought, {"text": "later", **missing}),
        (parked.handle_resolve_parked, {"thought_id": 1, **missing}),
    ]
    for handler, args in cases:
        res = await handler(args, pool)
        assert res["error"] == "user_id required", handler.__name__
        assert res["success"] is False
    pool.acquire.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [{}, {"user_id": None}, {"user_id": ""}])
async def test_career_writes_reject_missing_user(monkeypatch, missing):
    from backend.skills.handlers import career

    touched = AsyncMock()
    for name in ("get_opportunity_by_id", "get_master_resume", "get_or_create_career_application",
                 "create_tailored_resume", "get_application_batch", "claim_application_batch_for_submission"):
        monkeypatch.setattr(career, name, touched)

    cases = [
        (career.handle_tailor_resume, {"opportunity_id": 1, **missing}),
        (career.handle_prepare_application, {"opportunity_id": 1, **missing}),
        (career.handle_submit_approved_application_batch, {"batch_id": "b", **missing}),
        (career.handle_draft_cover_letter, {"opportunity_id": 1, **missing}),
    ]
    for handler, args in cases:
        res = await handler(args)
        assert res["error"] == "user_id required", handler.__name__
        assert res["success"] is False
    touched.assert_not_called()


@pytest.mark.asyncio
async def test_profile_write_with_a_caller_still_works():
    from backend.skills.handlers import profile

    conn = MagicMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    set_fact = AsyncMock(return_value={"key": "goal"})
    original = profile.set_profile_fact
    profile.set_profile_fact = set_fact
    try:
        res = await profile.handle_remember_fact({"key": "goal", "value": "ship", "user_id": "u1"}, pool)
    finally:
        profile.set_profile_fact = original
    assert res["success"] is True
    assert set_fact.await_args.kwargs["user_id"] == "u1"
