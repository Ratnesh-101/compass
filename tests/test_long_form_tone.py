"""Long-form requests in the default Balanced style must not be hard-capped."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import get_settings
from backend.models import StreamChatRequest
from backend.persona import build_persona_system_prompt, validate_tone
from backend.router_helpers import is_long_form_request
from backend.services.chat_stream import generate_chat_events

HACKATHON = (
    "We have a 48-hour hackathon starting Friday 6pm. Team of 3 building an AI app. "
    "Give me a concrete hour-by-hour plan, riskiest items first, and tell me exactly "
    "what to cut if we fall behind at hour 30."
)
DETAILED_MARKER = "detailed, structured deliverable"


@pytest.mark.parametrize("message", [
    HACKATHON,
    "Give me a step-by-step migration plan",
    "Compare Postgres and MongoDB in a table",
    "Write a detailed project outline",
])
def test_long_form_detected(message):
    assert is_long_form_request(message) is True


@pytest.mark.parametrize("message", [
    "What is a process and a thread?",
    "hi",
    "Explain what a database index is in two sentences.",
    "add a task to finish the lab",
])
def test_short_questions_not_long_form(message):
    assert is_long_form_request(message) is False


def test_detailed_tone_valid_and_in_prompt():
    assert validate_tone("detailed") == "detailed"
    assert DETAILED_MARKER in build_persona_system_prompt(tone="detailed")
    assert DETAILED_MARKER not in build_persona_system_prompt(tone="balanced")


class _Delta:
    content = "ok"
    tool_calls = None
    reasoning = None


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


async def _drive(message, tone):
    req = StreamChatRequest(message=message, conversation_id="c-long", tone=tone)
    dummy_req = MagicMock()
    dummy_req.is_disconnected = AsyncMock(return_value=False)
    chunks = [_Chunk([_Choice(_Delta(), None)]), _Chunk([_Choice(None, "stop")])]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_Stream(chunks))
    with patch("backend.services.chat_stream.openai.AsyncOpenAI", return_value=client), \
         patch("backend.router.get_openai_client", return_value=client), \
         patch("backend.services.chat_stream._resolve_pool", AsyncMock(return_value=None)):
        async for _ in generate_chat_events(req, dummy_req):
            pass
    client.chat.completions.create.assert_awaited()
    return client.chat.completions.create.call_args.kwargs


@pytest.mark.asyncio
async def test_balanced_long_form_gets_full_budget():
    kwargs = await _drive(HACKATHON, "balanced")
    assert kwargs["max_tokens"] == int(get_settings().MAX_SYNTHESIS_TOKENS)
    assert DETAILED_MARKER in kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_balanced_short_question_stays_capped():
    kwargs = await _drive("What is a process and a thread?", "balanced")
    assert kwargs["max_tokens"] == 250
    assert DETAILED_MARKER not in kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_brief_stays_brief_for_long_form_prompt():
    kwargs = await _drive(HACKATHON, "brief")
    assert kwargs["max_tokens"] == 90
    assert DETAILED_MARKER not in kwargs["messages"][0]["content"]
