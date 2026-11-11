"""Tests for chat tone token budgets, hard-cap continuation, and truncation detection."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent import run_agent
from backend.config import get_settings
from backend.models import StreamChatRequest
from backend.services.chat_stream import generate_chat_events
from backend.services.token_budget import (
    BALANCED_STREAM_MAX_TOKENS,
    BRIEF_STREAM_MAX_TOKENS,
    HARD_CAP_FINISH_MAX_TOKENS,
    HARD_CAP_FINISH_PROMPT,
    stream_token_budget,
)


class _Delta:
    def __init__(self, content: str = ""):
        self.content = content
        self.tool_calls = None
        self.reasoning = None


class _Choice:
    def __init__(self, delta=None, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices):
        self.choices = choices
        self.usage = None


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


async def _drive_streams(message: str, tone: str, streams: list[_Stream]):
    req = StreamChatRequest(message=message, conversation_id="c-trunc", tone=tone)
    dummy_req = MagicMock()
    dummy_req.is_disconnected = AsyncMock(return_value=False)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=streams)
    events: list[dict] = []
    with patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=client), \
         patch("backend.router.get_openai_client", return_value=client), \
         patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)), \
         patch("backend.services.chat_stream.record_usage", MagicMock()):
        async for line in generate_chat_events(req, dummy_req):
            for part in line.splitlines():
                part = part.strip()
                if part.startswith("data: "):
                    payload = part[6:]
                    try:
                        events.append(json.loads(payload))
                    except json.JSONDecodeError:
                        pass
    call_kwargs_list = [call.kwargs for call in client.chat.completions.create.call_args_list]
    return events, call_kwargs_list


def _make_agent_fake_client(content: str = "Do the lab first.", finish_reason: str = "stop") -> MagicMock:
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = None
    choice.finish_reason = finish_reason

    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_balanced_cut_answer_is_finished():
    stream1 = _Stream([
        _Chunk([_Choice(_Delta("Start by mastering the basics while you think aloud about"), None)]),
        _Chunk([_Choice(_Delta(""), "length")]),
    ])
    stream2 = _Stream([
        _Chunk([_Choice(_Delta(" trade-offs."), None)]),
        _Chunk([_Choice(_Delta(""), "stop")]),
    ])
    msg = "How do I prepare for a system design interview?"
    events, call_kwargs = await _drive_streams(msg, "balanced", [stream1, stream2])

    assert len(call_kwargs) == 2
    assert call_kwargs[1]["max_tokens"] == HARD_CAP_FINISH_MAX_TOKENS
    second_call_messages = call_kwargs[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert second_call_messages[-1]["content"] == HARD_CAP_FINISH_PROMPT
    assert second_call_messages[-2]["role"] == "assistant"
    assert second_call_messages[-2]["content"] == "Start by mastering the basics while you think aloud about"

    tokens = "".join(e.get("value", "") for e in events if e.get("type") == "token")
    assert tokens.endswith("trade-offs.")

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert not done_events[0].get("is_truncated")


@pytest.mark.asyncio
async def test_brief_cut_answer_is_finished():
    stream1 = _Stream([
        _Chunk([_Choice(_Delta("Start by mastering the basics while you think aloud about"), None)]),
        _Chunk([_Choice(_Delta(""), "length")]),
    ])
    stream2 = _Stream([
        _Chunk([_Choice(_Delta(" trade-offs."), None)]),
        _Chunk([_Choice(_Delta(""), "stop")]),
    ])
    msg = "How do I prepare for a system design interview?"
    events, call_kwargs = await _drive_streams(msg, "brief", [stream1, stream2])

    assert len(call_kwargs) == 2
    assert call_kwargs[1]["max_tokens"] == HARD_CAP_FINISH_MAX_TOKENS
    second_call_messages = call_kwargs[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert second_call_messages[-1]["content"] == HARD_CAP_FINISH_PROMPT
    assert second_call_messages[-2]["role"] == "assistant"
    assert second_call_messages[-2]["content"] == "Start by mastering the basics while you think aloud about"

    tokens = "".join(e.get("value", "") for e in events if e.get("type") == "token")
    assert tokens.endswith("trade-offs.")

    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert not done_events[0].get("is_truncated")


@pytest.mark.asyncio
async def test_hard_capped_continuation_is_bounded():
    stream1 = _Stream([
        _Chunk([_Choice(_Delta("Start by mastering the basics while you think aloud about"), None)]),
        _Chunk([_Choice(_Delta(""), "length")]),
    ])
    stream2 = _Stream([
        _Chunk([_Choice(_Delta(" trade-offs and more"), None)]),
        _Chunk([_Choice(_Delta(""), "length")]),
    ])
    msg = "How do I prepare for a system design interview?"
    events, call_kwargs = await _drive_streams(msg, "balanced", [stream1, stream2])

    assert len(call_kwargs) == 2
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0].get("is_truncated") is True


def test_stream_token_budget_values():
    assert stream_token_budget("brief", 8192) == (BRIEF_STREAM_MAX_TOKENS, True)
    assert stream_token_budget("balanced", 8192) == (BALANCED_STREAM_MAX_TOKENS, True)
    assert stream_token_budget("detailed", 8192) == (8192, False)
    assert stream_token_budget(None, 8192) == (8192, False)
    assert BRIEF_STREAM_MAX_TOKENS >= 400
    assert BALANCED_STREAM_MAX_TOKENS >= 600


@pytest.mark.asyncio
async def test_agent_reasoning_step_is_not_capped_by_tone():
    client = _make_agent_fake_client(content="Do the lab first.", finish_reason="stop")
    settings = get_settings()
    steps = []
    with patch("backend.agent.record_usage", MagicMock()):
        async for step in run_agent(
            goal="what should I do first?",
            pool=None,
            client=client,
            tone="brief",
            enable_critic=False,
            settings=settings,
        ):
            steps.append(step)

    client.chat.completions.create.assert_awaited()
    first_call_kwargs = client.chat.completions.create.call_args_list[0].kwargs
    assert first_call_kwargs["max_tokens"] == int(settings.MAX_REASONING_TOKENS)

    synth_steps = [s for s in steps if s.type == "synthesize"]
    assert len(synth_steps) == 1
    assert synth_steps[0].metadata is not None
    assert synth_steps[0].metadata.get("is_truncated") is False


@pytest.mark.asyncio
async def test_agent_text_reply_cut_by_length_is_flagged():
    client = _make_agent_fake_client(content="Do the lab first.", finish_reason="length")
    settings = get_settings()
    steps = []
    with patch("backend.agent.record_usage", MagicMock()):
        async for step in run_agent(
            goal="what should I do first?",
            pool=None,
            client=client,
            tone="brief",
            enable_critic=False,
            settings=settings,
        ):
            steps.append(step)

    synth_steps = [s for s in steps if s.type == "synthesize"]
    assert len(synth_steps) == 1
    assert synth_steps[0].metadata is not None
    assert synth_steps[0].metadata.get("is_truncated") is True
