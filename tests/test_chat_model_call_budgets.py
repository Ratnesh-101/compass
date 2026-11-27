"""Budgets for the model calls that run before the add-task decision, and no persistence for abandoned streams."""
from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

import backend.router as router
from backend.dependencies import Identity
from backend.models import StreamChatRequest
from backend.services import chat_stream

MESSAGE = "call the bank tomorrow at 5pm"


async def test_slow_router_prepass_falls_back_to_add_task(monkeypatch):
    async def _hang(*_a, **_k):
        await asyncio.sleep(5)
        return None, None, "late"

    monkeypatch.setattr(router, "_route_message_inner", _hang)
    monkeypatch.setattr(router, "ROUTER_PREPASS_BUDGET_S", 0.05)
    skill, args, text = await asyncio.wait_for(router.route_message(MESSAGE), 2)
    assert skill == "add_task"
    assert args["due_date"].endswith("17:00")
    assert text == ""


async def test_fast_router_prepass_is_used(monkeypatch):
    inner = AsyncMock(return_value=("query_tasks", {"intent": "roadmap"}, ""))
    monkeypatch.setattr(router, "_route_message_inner", inner)
    monkeypatch.setattr(router, "ROUTER_PREPASS_BUDGET_S", 0.5)
    assert await router.route_message(MESSAGE) == ("query_tasks", {"intent": "roadmap"}, "")
    inner.assert_awaited_once()


async def test_timeout_fallback_does_not_invent_a_task_for_questions(monkeypatch):
    async def _hang(*_a, **_k):
        await asyncio.sleep(5)

    monkeypatch.setattr(router, "_route_message_inner", _hang)
    monkeypatch.setattr(router, "ROUTER_PREPASS_BUDGET_S", 0.05)
    skill, _args, _text = await router.route_message("what is the weather tomorrow at 5pm?")
    assert skill != "add_task"


async def _silent_source():
    yield 'data: {"type": "status", "stage": "thinking"}\n\n'
    await asyncio.sleep(5)
    yield 'data: {"type": "done"}\n\n'


async def test_total_budget_emits_terminal_retryable_error(monkeypatch):
    monkeypatch.setattr(chat_stream, "STREAM_TOTAL_BUDGET_S", 0.05)
    frames = [f async for f in chat_stream._with_total_budget(_silent_source())]
    assert frames[0].startswith('data: {"type": "status"')
    payload = json.loads(frames[-1][len("data: "):])
    assert payload == {
        "type": "error",
        "detail": "This is taking longer than usual. Please try again.",
        "can_retry": True,
        "terminal": True,
    }


async def test_total_budget_does_not_cut_a_stream_that_started(monkeypatch):
    monkeypatch.setattr(chat_stream, "STREAM_TOTAL_BUDGET_S", 0.05)

    async def _source():
        yield 'data: {"type": "token", "value": "hi"}\n\n'
        await asyncio.sleep(0.15)
        yield 'data: {"type": "done"}\n\n'

    frames = [f async for f in chat_stream._with_total_budget(_source())]
    assert len(frames) == 2 and '"done"' in frames[-1]


class _Stream:
    def __init__(self, items):
        self.items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self):
        pass


def _chunk(text):
    c = MagicMock()
    c.usage = None
    c.choices = [MagicMock(delta=MagicMock(content=text, tool_calls=None), finish_reason=None)]
    return c


def _fake_conn():
    conn = MagicMock()
    for name in ("fetchrow", "fetchval", "execute"):
        setattr(conn, name, AsyncMock(return_value=None))
    conn.fetch = AsyncMock(return_value=[])
    return conn


@contextlib.asynccontextmanager
async def _fake_acquire(*_a, **_k):
    yield _fake_conn()


def _fake_pool():
    pool = MagicMock()
    pool.acquire = _fake_acquire
    return pool


async def _run_stream(items):
    from backend.routers.chat import stream_chat

    request = MagicMock(spec=Request)
    request.is_disconnected = AsyncMock(return_value=False)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_Stream(items))
    add_message = AsyncMock(return_value={"id": "m1"})
    with patch("openai.AsyncOpenAI", return_value=client), \
         patch("backend.routers.chat.get_pool", return_value=None), \
         patch("backend.routers.chat._get_current_identity", return_value=Identity(id="u1", is_admin=False, user_id="u1")), \
         patch.object(chat_stream, "_resolve_pool", AsyncMock(return_value=_fake_pool())), \
         patch.object(chat_stream, "timed_acquire", _fake_acquire), \
         patch("backend.services.chat_extra_actions.get_pool", AsyncMock(return_value=_fake_pool())), \
         patch("backend.memory.db.init_pool", AsyncMock(return_value=_fake_pool())), \
         patch.object(chat_stream, "mark_message_state", AsyncMock()), \
         patch.object(chat_stream.conversations, "get_or_create_conversation", AsyncMock(return_value="c1")), \
         patch.object(chat_stream.conversations, "add_message", add_message):
        resp = await stream_chat(StreamChatRequest(message="tell me a fun fact", conversation_id="conv-1"), request)
        outcome = None
        try:
            async for _ in resp.body_iterator:
                pass
        except asyncio.CancelledError as exc:
            outcome = exc
        await asyncio.sleep(0.1)
    return add_message, outcome


async def test_cancelled_stream_does_not_persist_assistant_reply():
    add_message, outcome = await _run_stream([_chunk("partial reply"), asyncio.CancelledError()])
    assert isinstance(outcome, asyncio.CancelledError)
    add_message.assert_not_called()


async def test_completed_stream_still_persists():
    add_message, outcome = await _run_stream([_chunk("full reply")])
    assert outcome is None
    assert add_message.await_count >= 1
