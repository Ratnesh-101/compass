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


def _text_response(text: str):
    msg = SimpleNamespace(tool_calls=None, content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)


@pytest.mark.asyncio
async def test_route_message_answers_external_plan_directly():
    from backend.router import route_message

    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        side_effect=[_tool_response("query_tasks", '{"intent": "roadmap"}'), _text_response("Hour 0-4: scaffold")]
    )
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
