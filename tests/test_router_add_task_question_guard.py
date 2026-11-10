"""The routing LLM must not turn a plain question into a task, even when it picks add_task."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.router import route_message
from backend.services.task_intent import blocks_task_creation

QUESTION = "should I be worried about the exam on friday?"
COMMAND = "add a task to buy milk tomorrow"


def _add_task_response(title: str):
    args = json.dumps({"title": title})
    call = SimpleNamespace(function=SimpleNamespace(name="add_task", arguments=args))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


def _client(response):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def test_question_is_blocked_from_task_creation():
    assert blocks_task_creation(QUESTION) is True


def test_explicit_command_is_not_blocked_from_task_creation():
    assert blocks_task_creation(COMMAND) is False


@pytest.mark.asyncio
async def test_model_add_task_on_a_question_does_not_create_a_task():
    client = _client(_add_task_response("the exam on friday"))
    with patch("backend.router.get_openai_client", return_value=client):
        skill, args, text = await route_message(QUESTION)
    assert skill != "add_task"


@pytest.mark.asyncio
async def test_explicit_command_still_routes_to_add_task():
    client = _client(_add_task_response("buy milk"))
    with patch("backend.router.get_openai_client", return_value=client):
        skill, args, text = await route_message(COMMAND)
    assert skill == "add_task"
    assert "buy milk" in args["title"].lower()
