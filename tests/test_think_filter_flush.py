import pytest

from backend.services.streaming_filter import StreamingThinkFilter


def _run(tokens):
    f = StreamingThinkFilter()
    out = "".join(f.process(t) for t in tokens)
    return out, f.flush()


def test_trailing_partial_think_prefix_is_not_lost():
    out, tail = _run(["Use a mutex <", "th"])
    assert out + tail == "Use a mutex <th"


def test_a_lone_angle_bracket_at_the_end_is_returned():
    out, tail = _run(["x < y and y <"])
    assert out + tail == "x < y and y <"


def test_unfinished_think_block_stays_private():
    out, tail = _run(["answer<think>secret reasoning"])
    assert out + tail == "answer"


def test_complete_think_block_is_removed_and_nothing_is_left_over():
    out, tail = _run(["a<thi", "nk>hidden</think>b"])
    assert out + tail == "ab"
    assert tail == ""


def test_flush_is_idempotent():
    f = StreamingThinkFilter()
    f.process("hi <t")
    assert f.flush() == "<t"
    assert f.flush() == ""


@pytest.mark.asyncio
async def test_stream_does_not_drop_a_trailing_angle_bracket():
    from unittest.mock import AsyncMock, MagicMock, patch

    from backend.models import StreamChatRequest
    from tests.test_chat_orchestration_fixes import _chunk, _collect, _mock_client, _Stream

    client = _mock_client(lambda: _Stream([_chunk("Compare a and b: use a <"), _chunk("", "stop")]))
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    with patch("backend.services.chat_stream.openai.AsyncOpenAI", lambda **kw: client), \
         patch("backend.services.chat_stream._schedule_stream_persistence", MagicMock()):
        events = await _collect(StreamChatRequest(message="tell me about dogs", tone="exploratory"), request)
    import json

    payloads = [json.loads(e[6:]) for e in events if isinstance(e, str) and e.startswith("data: ")]
    text = "".join(p.get("value", "") for p in payloads if p.get("type") == "token")
    assert text.endswith("use a <"), text
