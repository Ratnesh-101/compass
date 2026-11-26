"""Wording tests: user-visible task lists and disambiguation prompts must not expose raw task IDs."""

import asyncio
from unittest.mock import AsyncMock, patch

from backend.services import chat_task_actions as cta
from backend.skills.handlers import tasks as task_handlers

TASKS = [
    {"id": 41, "title": "Lab report 1", "status": "open", "priority": "high", "domain": "coursework", "due_date": "2026-12-05"},
    {"id": 42, "title": "Lab report 2", "status": "open", "priority": "medium", "domain": "coursework", "due_date": None},
]


class _Acquire:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def acquire(self):
        return _Acquire()


def _run(coro):
    return asyncio.run(coro)


def _assert_no_id(text):
    assert "(ID: " not in text, text
    assert "(id: " not in text.lower(), text


def test_query_tasks_list_has_no_ids():
    with patch.object(task_handlers, "list_chat_tasks", AsyncMock(return_value=[dict(t) for t in TASKS])):
        out = _run(task_handlers.handle_query_tasks({"message": "show my tasks"}, _Pool()))
    assert "Lab report 1" in out["response"]
    _assert_no_id(out["response"])


def test_query_coursework_list_has_no_ids():
    with patch.object(task_handlers, "list_chat_tasks", AsyncMock(return_value=[dict(t) for t in TASKS])):
        out = _run(task_handlers.handle_query_coursework_tasks({}, _Pool()))
    assert "Lab report 1" in out["response"]
    _assert_no_id(out["response"])


def test_roadmap_has_no_ids():
    text = task_handlers.build_daily_roadmap([dict(t) for t in TASKS])
    _assert_no_id(text)


def _chat_action(args, tasks):
    pending = AsyncMock(side_effect=lambda conn, **kw: {"id": 1, "action": kw["action"]})
    with patch.object(cta, "get_all_active_tasks_for_user", AsyncMock(return_value=tasks)), \
         patch.object(cta, "create_chat_pending_action", pending):
        return _run(cta.handle_chat_task_action(
            args, "msg", "conv-1", "owner-1", pool=_Pool(), persist=False, tz="Asia/Calcutta",
        ))


def test_disambiguation_prompt_has_no_ids():
    out = _chat_action({"action": "complete", "target": "lab report"}, [dict(t) for t in TASKS])
    assert "Lab report 1" in out["response"] and "Lab report 2" in out["response"]
    _assert_no_id(out["response"])


def test_no_match_prompt_has_no_ids():
    out = _chat_action({"action": "complete", "target": "zzzz unrelated"}, [dict(t) for t in TASKS])
    _assert_no_id(out["response"])


def test_single_match_card_text_has_no_ids():
    out = _chat_action({"action": "complete", "target": "Lab report 1"}, [dict(t) for t in TASKS])
    _assert_no_id(out["response"])
    _assert_no_id(out["data"]["pending_action"]["card_text"])


def test_disambiguation_reply_prompts_have_no_ids():
    for n in (1, 2, 3):
        _assert_no_id(cta._disambiguation_prompt(n))
