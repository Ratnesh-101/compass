"""
Tests that specialist answers are not silently truncated at the token cap.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.specialist import _synthesize_specialist_response

CUT_NOTE = "_(The answer was cut short — ask me to continue.)_"
CONTINUE_PROMPT = (
    "Continue exactly where you stopped and finish the answer concisely. "
    "Do not repeat anything you already wrote."
)


def _resp(content, finish_reason="stop"):
    choice = SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason=finish_reason
    )
    return SimpleNamespace(choices=[choice])


def _run_with(side_effects):
    """Patch AsyncOpenAI so create() yields side_effects in order; return (coro, create_mock)."""
    create = AsyncMock(side_effect=side_effects)
    client = MagicMock()
    client.chat.completions.create = create
    settings = SimpleNamespace(
        NEBIUS_API_KEY="fake-key",
        NEBIUS_BASE_URL="http://localhost/v1",
        ROUTER_MODEL="fake-model",
    )
    return client, settings, create


async def _call(side_effects):
    client, settings, create = _run_with(side_effects)
    with patch("openai.AsyncOpenAI", return_value=client), patch(
        "backend.config.get_settings", return_value=settings
    ):
        result = await _synthesize_specialist_response(
            "coursework", "explain hazards", {"a": 1}, "FALLBACK"
        )
    return result, create


async def test_normal_finish_makes_one_call():
    result, create = await _call([_resp("Full answer.", "stop")])

    assert create.await_count == 1
    kwargs = create.await_args.kwargs
    assert kwargs["max_tokens"] == 2000
    assert "Answer every part of the user's question" in kwargs["messages"][0]["content"]
    assert "never leave a table, list or code block unfinished" in kwargs["messages"][0]["content"]
    assert result == "Full answer."


async def test_length_then_stop_continues_once():
    result, create = await _call(
        [_resp("Part one", "length"), _resp("and part two.", "stop")]
    )

    assert create.await_count == 2
    second = create.await_args_list[1].kwargs
    assert second["max_tokens"] == 800
    assert second["temperature"] == 0.5
    assert second["messages"][-2] == {"role": "assistant", "content": "Part one"}
    assert second["messages"][-1] == {"role": "user", "content": CONTINUE_PROMPT}
    assert second["messages"][0]["role"] == "system"
    assert second["messages"][1]["role"] == "user"
    assert result == "Part one and part two."
    assert CUT_NOTE not in result


async def test_length_twice_appends_cut_short_note():
    result, create = await _call(
        [_resp("Part one", "length"), _resp("part two", "length")]
    )

    assert create.await_count == 2
    assert "Part one" in result and "part two" in result
    assert result.endswith(CUT_NOTE)


async def test_continuation_failure_keeps_partial_with_note():
    result, create = await _call(
        [_resp("Part one", "length"), RuntimeError("boom")]
    )

    assert create.await_count == 2
    assert result.startswith("Part one")
    assert result.endswith(CUT_NOTE)


async def test_first_call_failure_returns_fallback():
    result, create = await _call([RuntimeError("boom")])

    assert create.await_count == 1
    assert result == "FALLBACK"


async def test_client_allows_long_answers_and_bounds_retries():
    client, settings, _ = _run_with([_resp("ok", "stop")])
    with patch("openai.AsyncOpenAI", return_value=client) as ctor, patch(
        "backend.config.get_settings", return_value=settings
    ):
        await _synthesize_specialist_response("coursework", "q", {"a": 1}, "FALLBACK")

    kwargs = ctor.call_args.kwargs
    assert kwargs["timeout"] == 45.0
    assert kwargs["max_retries"] == 1
