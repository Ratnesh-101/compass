"""Regression tests for chat orchestration fixes (conv id, tone caps, undo scoping, persistence)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.dependencies import generate_guest_token
from backend.memory.chat_pending import undo_soft_deleted_tasks
from backend.memory.db import get_pool
from backend.models import StreamChatRequest
from backend.orchestrator import _select_candidate, handle_message
from backend.services import chat_stream


@pytest.fixture
def guest_headers():
    _, token = generate_guest_token()
    return {"x-guest-token": token}


def _chunk(content, finish=None):
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = None
    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


class _Stream:
    def __init__(self, chunks, raise_after=False):
        self._chunks = chunks
        self._raise = raise_after

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c
        if self._raise:
            raise RuntimeError("boom")

    async def aclose(self):
        pass


def _mock_client(make_stream):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=lambda **kw: make_stream())
    return client


async def _collect(req, request):
    return [ev async for ev in chat_stream.generate_chat_events(req, request, user_id="u-orch-fix")]


@pytest.mark.asyncio
async def test_stream_passes_its_conv_id_to_orchestrator_and_persists_under_it():
    seen = {}

    async def fake_handle(**kwargs):
        seen.update(kwargs)
        return {"conversation_id": kwargs.get("conversation_id"), "response": "Restored.", "skill_used": "undo"}

    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    sched = MagicMock()
    with patch("backend.services.chat_stream.orchestrator.handle_message", side_effect=fake_handle), \
         patch("backend.services.chat_stream._schedule_stream_persistence", sched):
        events = await _collect(StreamChatRequest(message="undo"), request)
    done = [json.loads(e[6:]) for e in events if e.startswith("data: ") and '"type": "done"' in e][0]
    assert seen["conversation_id"]
    assert done["conversation_id"] == seen["conversation_id"] == sched.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("tone", ["brief", "balanced"])
async def test_capped_tones_skip_length_continuation(tone):
    client = _mock_client(lambda: _Stream([_chunk("partial text", "length")]))
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    with patch("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kw: client), \
         patch("backend.services.chat_stream._schedule_stream_persistence", MagicMock()):
        await _collect(StreamChatRequest(message="tell me about dogs", tone=tone), request)
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_client_disconnect_persists_partial_text():
    client = _mock_client(lambda: _Stream([_chunk("hello "), _chunk("world")]))
    request = MagicMock()
    request.is_disconnected = AsyncMock(side_effect=[False, True, True])
    sched = MagicMock()
    with patch("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kw: client), \
         patch("backend.services.chat_stream._schedule_stream_persistence", sched):
        await _collect(StreamChatRequest(message="tell me about dogs"), request)
    assert sched.called
    assert sched.call_args.args[2] == "hello"


@pytest.mark.asyncio
async def test_inner_midstream_error_persists_partial_text():
    client = _mock_client(lambda: _Stream([_chunk("hello there")], raise_after=True))
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    sched = MagicMock()
    with patch("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kw: client), \
         patch("backend.services.chat_stream._schedule_stream_persistence", sched):
        await _collect(StreamChatRequest(message="tell me about dogs"), request)
    assert sched.called
    assert sched.call_args.args[2] == "hello there"


@pytest.mark.asyncio
async def test_api_chat_forwards_tone_and_mode(client, guest_headers):
    handle = AsyncMock(return_value={"conversation_id": "c1", "response": "ok", "skill_used": "chat"})
    with patch("backend.orchestrator.handle_message", handle):
        resp = await client.post(
            "/api/chat", json={"message": "hi there", "tone": "brief", "mode": "study"}, headers=guest_headers
        )
    assert resp.status_code == 200
    assert handle.await_args.kwargs["tone"] == "brief"
    assert handle.await_args.kwargs["conv_mode"] == "study"


def test_select_candidate_falls_back_to_task_id_when_ordinal_out_of_range():
    assert _select_candidate("3", [10, 3]) == 3
    assert _select_candidate("2", [10, 3]) == 3  # in-range ordinal still wins
    assert _select_candidate("7", [10, 3]) is None


@pytest.mark.asyncio
async def test_undo_restores_only_most_recent_delete_batch():
    user = "test_user_orchfix_batch"
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)
        old = await conn.fetchval(
            "INSERT INTO tasks (title, domain, user_id, deleted_at) VALUES ('Old gone', 'general', $1, $2) RETURNING id",
            user, now - timedelta(minutes=8),
        )
        new = await conn.fetchval(
            "INSERT INTO tasks (title, domain, user_id, deleted_at) VALUES ('New gone', 'general', $1, $2) RETURNING id",
            user, now - timedelta(minutes=1),
        )
        try:
            restored = await undo_soft_deleted_tasks(conn, user, minutes=10)
            assert [t["id"] for t in restored] == [new]
            still = await conn.fetchval("SELECT deleted_at FROM tasks WHERE id = $1", old)
            assert still is not None
        finally:
            await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)


@pytest.mark.asyncio
async def test_undo_after_add_task_does_not_restore_older_deletion():
    user = "test_user_orchfix_order"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)
        await conn.execute("DELETE FROM agent_audit_log WHERE approved_by = $1", user)
        old = await conn.fetchval(
            "INSERT INTO tasks (title, domain, user_id, deleted_at) "
            "VALUES ('Old gone', 'general', $1, now() - interval '5 minutes') RETURNING id",
            user,
        )
    try:
        with patch(
            "backend.orchestrator.route_message",
            AsyncMock(return_value=("add_task", {"title": "Fresh orchfix task", "domain": "general"}, None)),
        ):
            await handle_message(conversation_id="conv-orchfix", message="add task fresh orchfix task", user_id=user)
        res = await handle_message(conversation_id="conv-orchfix", message="undo", user_id=user)
        async with pool.acquire() as conn:
            still = await conn.fetchval("SELECT deleted_at FROM tasks WHERE id = $1", old)
        assert still is not None, res["response"]
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)
            await conn.execute("DELETE FROM agent_audit_log WHERE approved_by = $1", user)


@pytest.mark.asyncio
async def test_duplicate_title_check_ignores_trailing_whitespace():
    user = "test_user_orchfix_dup"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)
        await conn.execute("INSERT INTO tasks (title, domain, user_id) VALUES ('Dup orchfix', 'general', $1)", user)
    try:
        with patch(
            "backend.orchestrator.route_message",
            AsyncMock(return_value=("add_task", {"title": "Dup orchfix   ", "domain": "general"}, None)),
        ):
            await handle_message(conversation_id="conv-orchfix-dup", message="add task Dup orchfix", user_id=user)
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT count(*) FROM tasks WHERE user_id = $1", user)
        assert n == 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tasks WHERE user_id = $1", user)
            await conn.execute("DELETE FROM agent_audit_log WHERE approved_by = $1", user)
