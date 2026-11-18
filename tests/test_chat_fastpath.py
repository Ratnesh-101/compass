"""Tests for backend/services/chat_fastpath.py: the ROUTER_EXTRA_BODY switch and the greeting fast path.

Pure tests: fake model client and no database.
"""

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import StreamChatRequest
from backend.routers.chat import StreamChatRequestV2
from backend.services import chat_fastpath
from backend.services.chat_fastpath import (
    GREETING_REPLY,
    apply_router_extra_body,
    is_greeting_fastpath,
    parse_router_extra_body,
)
from backend.services.chat_stream import generate_chat_events


# ---------------------------------------------------------------------------
# Fakes (same shape as tests/test_chat_completeness_wsb.py)
# ---------------------------------------------------------------------------

class _Delta:
    def __init__(self, content="", reasoning=None, tool_calls=None):
        self.content = content
        self.reasoning = reasoning
        self.tool_calls = tool_calls


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


def _text_stream(text, finish="stop"):
    return _Stream([_Chunk([_Choice(_Delta(text), None)]), _Chunk([_Choice(_Delta(""), finish)])])


def _request():
    r = MagicMock()
    r.is_disconnected = AsyncMock(return_value=False)
    return r


def _parse(events):
    out = []
    for line in events:
        for part in line.splitlines():
            part = part.strip()
            if part.startswith("data: "):
                try:
                    out.append(json.loads(part[6:]))
                except json.JSONDecodeError:
                    pass
    return out


def _settings(**extra):
    return SimpleNamespace(
        NEBIUS_API_KEY="real-looking-key", NEBIUS_BASE_URL="http://example.invalid/v1",
        ROUTER_MODEL="router-model", MAX_SYNTHESIS_TOKENS=8192, MAX_CONTINUATION_ATTEMPTS=2,
        **extra,
    )


async def _drive(req, side_effect, settings):
    """Run the stream with a fake client. Returns (events, create mock, persistence mock)."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=side_effect)
    persist = MagicMock()
    patches = [
        patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=client),
        patch("backend.router.get_openai_client", return_value=client),
        patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)),
        patch("backend.services.chat_stream.record_usage", MagicMock()),
        patch("backend.services.chat_stream._schedule_stream_persistence", persist),
        patch("backend.services.chat_stream.get_settings", return_value=settings),
    ]
    for p in patches:
        p.start()
    try:
        raw = [line async for line in generate_chat_events(req, _request(), user_id="u1")]
    finally:
        for p in reversed(patches):
            p.stop()
    return _parse(raw), client.chat.completions.create, persist


def _fail_if_called(*_a, **_k):
    raise AssertionError("the model must not be called")


# ---------------------------------------------------------------------------
# ROUTER_EXTRA_BODY parsing
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_warned(monkeypatch):
    monkeypatch.setattr(chat_fastpath, "_warned_extra_body", False)


@pytest.mark.parametrize("raw", ["", "   ", None, 5])
def test_empty_or_non_string_returns_none_without_warning(raw, caplog):
    with caplog.at_level(logging.WARNING, logger="compass.services.chat_fastpath"):
        assert parse_router_extra_body(raw) is None
    assert not caplog.records


def test_invalid_json_returns_none_and_warns_once(caplog):
    with caplog.at_level(logging.WARNING, logger="compass.services.chat_fastpath"):
        assert parse_router_extra_body("{not json") is None
        assert parse_router_extra_body("{still not json") is None
    assert len([r for r in caplog.records if "ROUTER_EXTRA_BODY" in r.getMessage()]) == 1


def test_json_list_returns_none(caplog):
    with caplog.at_level(logging.WARNING, logger="compass.services.chat_fastpath"):
        assert parse_router_extra_body('[1, 2]') is None
        assert parse_router_extra_body('"text"') is None
    assert len([r for r in caplog.records if "ROUTER_EXTRA_BODY" in r.getMessage()]) == 1


def test_valid_object_returns_dict():
    raw = '{"chat_template_kwargs": {"enable_thinking": false}}'
    assert parse_router_extra_body(raw) == {"chat_template_kwargs": {"enable_thinking": False}}


def test_apply_adds_extra_body_only_for_valid_object():
    kwargs = {"model": "m"}
    assert apply_router_extra_body(kwargs, SimpleNamespace(ROUTER_EXTRA_BODY="")) == {"model": "m"}
    assert apply_router_extra_body({"model": "m"}, SimpleNamespace()) == {"model": "m"}
    assert apply_router_extra_body({"model": "m"}, SimpleNamespace(ROUTER_EXTRA_BODY="[]")) == {"model": "m"}
    got = apply_router_extra_body({"model": "m"}, SimpleNamespace(ROUTER_EXTRA_BODY='{"a": 1}'))
    assert got == {"model": "m", "extra_body": {"a": 1}}


def test_setting_defaults_to_empty_string():
    from backend.config import Settings
    assert Settings.model_fields["ROUTER_EXTRA_BODY"].default == ""


@pytest.mark.asyncio
async def test_default_chat_call_has_no_extra_body():
    events, create, _ = await _drive(
        StreamChatRequest(message="Explain recursion simply", tone="balanced"),
        [_text_stream("Recursion is a function calling itself.")],
        _settings(),
    )
    assert create.await_count == 1
    assert "extra_body" not in create.call_args.kwargs
    assert "extra_body" not in create.call_args_list[0].kwargs


@pytest.mark.asyncio
async def test_configured_extra_body_reaches_router_chat_call():
    body = '{"chat_template_kwargs": {"enable_thinking": false}}'
    events, create, _ = await _drive(
        StreamChatRequest(message="Explain recursion simply", tone="balanced"),
        [_text_stream("Recursion is a function calling itself.")],
        _settings(ROUTER_EXTRA_BODY=body),
    )
    assert create.call_args_list[0].kwargs["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


# ---------------------------------------------------------------------------
# Greeting fast path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("greeting", ["hi", "Hello!"])
async def test_pure_greeting_makes_no_model_call(greeting):
    events, create, persist = await _drive(
        StreamChatRequest(message=greeting, conversation_id="conv-greet"), _fail_if_called, _settings(),
    )
    assert create.await_count == 0
    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) == 1 and tokens[0]["value"] == GREETING_REPLY
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1 and done[0]["conversation_id"] == "conv-greet"
    assert not [e for e in events if e["type"] == "error"]
    persist.assert_called_once()
    assert persist.call_args.args[:3] == ("conv-greet", greeting, GREETING_REPLY)


@pytest.mark.asyncio
async def test_greeting_followed_by_request_reaches_the_model():
    events, create, persist = await _drive(
        StreamChatRequest(message="hi can you find me internships"),
        [_text_stream("Sure, here are some ideas.")],
        _settings(),
    )
    assert create.await_count >= 1
    tokens = "".join(e.get("value", "") for e in events if e["type"] == "token")
    assert GREETING_REPLY not in tokens


@pytest.mark.asyncio
async def test_continue_request_with_hi_does_not_take_fast_path():
    req = StreamChatRequestV2(message="hi", conversation_id="c1", continue_message_id="123")
    events, create, persist = await _drive(req, _fail_if_called, _settings())
    tokens = "".join(e.get("value", "") for e in events if e["type"] == "token")
    assert GREETING_REPLY not in tokens
    for call in persist.call_args_list:
        assert GREETING_REPLY not in call.args


@pytest.mark.asyncio
async def test_specialist_request_with_hi_does_not_take_fast_path():
    req = StreamChatRequest(message="hi", conversation_id="c2", specialist_id="research")
    with patch(
        "backend.agents.specialist.run_specialist_task",
        AsyncMock(return_value={"summary": "specialist answer"}),
    ):
        events, create, persist = await _drive(req, _fail_if_called, _settings())
    tokens = "".join(e.get("value", "") for e in events if e["type"] == "token")
    assert GREETING_REPLY not in tokens
    for call in persist.call_args_list:
        assert GREETING_REPLY not in call.args


def test_fastpath_predicate_rules():
    assert is_greeting_fastpath(StreamChatRequest(message="hi"), "hi")
    assert is_greeting_fastpath(StreamChatRequest(message="Hello!"), "Hello!")
    assert not is_greeting_fastpath(StreamChatRequest(message="hi can you find me internships"), "hi can you find me internships")
    assert not is_greeting_fastpath(StreamChatRequest(message=""), "")
    assert not is_greeting_fastpath(StreamChatRequest(message="hi", specialist_id="research"), "hi")
    assert not is_greeting_fastpath(StreamChatRequest(message="hi", specialistId="research"), "hi")
    assert not is_greeting_fastpath(StreamChatRequest(message="hi", target_message_id="5"), "hi")
    assert not is_greeting_fastpath(StreamChatRequestV2(message="hi", continue_message_id="9"), "hi")
