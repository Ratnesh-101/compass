"""General planning questions about a user-described project must not become query_tasks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.router_helpers import _fallback_route, is_external_project_request

PLAN_48H = (
    "We have a 48-hour hackathon starting Friday 6pm. Team of 3: one backend dev, one frontend dev, "
    "one ML person. We want to build an AI study planner. Give me a concrete hour-by-hour plan, "
    "riskiest items first, and tell me exactly what to cut if we fall behind at hour 30."
)
DB_CHOICE = "Should I use Postgres with pgvector or MongoDB for a hackathon project that stores embeddings?"
PITCH = "Help me write a 60-second pitch for my hackathon project, an AI study planner."
EXTERNAL = [PLAN_48H, DB_CHOICE, PITCH]
PERSONAL = [
    "What should I work on first today?",
    "Show my hackathon tasks",
    "prioritize my deadlines",
    "plan my day",
    "what is on my plate this week",
    "Add a task to finish the lab",
]


@pytest.mark.parametrize("message", EXTERNAL)
def test_external_prompts_detected(message):
    assert is_external_project_request(message) is True


@pytest.mark.parametrize("message", PERSONAL)
def test_personal_prompts_not_external(message):
    assert is_external_project_request(message) is False


@pytest.mark.parametrize("message", EXTERNAL)
@pytest.mark.parametrize("history", [None, [{"role": "user", "content": "what is my next task"}]])
def test_fallback_route_does_not_hijack_external(message, history):
    assert _fallback_route(message, history) == (None, None, "")


@pytest.mark.parametrize("message", ["What should I work on first today?", "show my hackathon tasks"])
def test_fallback_route_still_queries_tasks(message):
    skill, _args, _text = _fallback_route(message, None)
    assert skill == "query_tasks"


def _tool_response(name: str, args: str = "{}"):
    tc = SimpleNamespace(function=SimpleNamespace(name=name, arguments=args))
    msg = SimpleNamespace(tool_calls=[tc], content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


def _text_response(text: str, finish_reason: str = "stop"):
    msg = SimpleNamespace(tool_calls=None, content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)], usage=None)


def _guard_client(side_effect):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=side_effect)
    # with_options() must hand back an object sharing the same create mock.
    client.with_options.return_value = client
    return client


@pytest.mark.asyncio
async def test_route_message_answers_external_plan_directly():
    from backend.router import route_message

    client = _guard_client([_tool_response("query_tasks", '{"intent": "roadmap"}'), _text_response("Hour 0-4: scaffold")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message(PLAN_48H)
    assert result == (None, None, "Hour 0-4: scaffold")
    assert client.chat.completions.create.await_count == 2
    second_kwargs = client.chat.completions.create.await_args_list[1].kwargs
    assert "tools" not in second_kwargs
    assert "tool_choice" not in second_kwargs


@pytest.mark.asyncio
async def test_route_message_keeps_query_tasks_for_personal():
    from backend.router import route_message

    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_tool_response("query_tasks", '{"intent": "roadmap"}'))
    with patch("backend.router.get_openai_client", return_value=client):
        skill, args, text = await route_message("What should I work on first today?")
    assert skill == "query_tasks"
    assert args == {"intent": "roadmap"}
    assert text == ""
    assert client.chat.completions.create.await_count == 1


def _hijack():
    return _tool_response("query_tasks", '{"intent": "roadmap"}')


@pytest.mark.asyncio
async def test_guard_uses_skill_model_big_budget_and_long_timeout():
    from backend.router import route_message
    from backend.config import get_settings

    settings = get_settings()
    client = _guard_client([_hijack(), _text_response("plan")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message(PLAN_48H)
    assert result == (None, None, "plan")
    kwargs = client.chat.completions.create.await_args_list[1].kwargs
    assert kwargs["model"] == settings.SKILL_MODEL
    assert kwargs["max_tokens"] == 3500
    client.with_options.assert_called_with(timeout=60.0, max_retries=0)


@pytest.mark.asyncio
async def test_guard_empty_primary_falls_back_to_router_model():
    from backend.router import route_message
    from backend.config import get_settings

    settings = get_settings()
    client = _guard_client([_hijack(), _text_response("", "length"), _text_response("fallback plan")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message(PLAN_48H)
    assert result == (None, None, "fallback plan")
    calls = client.chat.completions.create.await_args_list
    assert len(calls) == 3
    assert calls[2].kwargs["model"] == settings.ROUTER_MODEL
    assert calls[2].kwargs["max_tokens"] == 3500
    assert "tools" not in calls[2].kwargs


@pytest.mark.asyncio
async def test_guard_raising_primary_falls_back_to_router_model():
    from backend.router import route_message

    client = _guard_client([_hijack(), RuntimeError("boom"), _text_response("fallback plan")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message(PLAN_48H)
    assert result == (None, None, "fallback plan")
    assert client.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_guard_both_empty_uses_fallback_route_with_at_most_three_calls():
    from backend.router import route_message

    client = _guard_client([_hijack(), _text_response(""), _text_response("")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message(PLAN_48H)
    assert result == _fallback_route(PLAN_48H, None)
    assert client.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_guard_length_truncated_reply_is_returned_without_retry():
    from backend.router import route_message

    client = _guard_client([_hijack(), _text_response("partial plan", "length")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message(PLAN_48H)
    assert result == (None, None, "partial plan")
    assert client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_main_loop_empty_length_reply_retries_with_triple_budget():
    from backend.router import route_message

    client = _guard_client([_text_response("", "length"), _text_response("hello there")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message("Explain how photosynthesis works in plants please")
    assert result == (None, None, "hello there")
    calls = client.chat.completions.create.await_args_list
    assert calls[0].kwargs["max_tokens"] == 1024
    assert calls[1].kwargs["max_tokens"] == 3072


@pytest.mark.asyncio
async def test_main_loop_empty_stop_reply_keeps_budget():
    from backend.router import route_message

    client = _guard_client([_text_response("", "stop"), _text_response("hello there")])
    with patch("backend.router.get_openai_client", return_value=client):
        result = await route_message("Explain how photosynthesis works in plants please")
    assert result == (None, None, "hello there")
    calls = client.chat.completions.create.await_args_list
    assert calls[1].kwargs["max_tokens"] == 1024
