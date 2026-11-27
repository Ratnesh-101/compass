"""The add-task preview must always produce a card: a slow or failing model falls back to the deterministic parser."""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest

from backend.services import task_intake, task_intake_llm
from backend.services.task_intake_parse import IntakeItem
from backend.services.task_time import local_today


class _Conn:
    async def execute(self, *a, **k):
        return "UPDATE 0"

    async def fetchrow(self, query, action, titles, count, owner, conv, expires):
        return {"id": 1, "action": action, "count": count, "status": "pending", "expires_at": expires}


class _Pool:
    @asynccontextmanager
    async def acquire(self):
        yield _Conn()


async def _preview(message):
    return await task_intake.handle_intake_preview(
        message=message, conv_id="c1", owner_identity="o1", user_id=None, guest_id=None,
        persist=False, active_pool=_Pool(), start_time=time.perf_counter(),
    )


def _item(result):
    assert result["success"] is True
    items = result["data"]["pending_action"]["items"]
    assert len(items) == 1
    return items[0]


@pytest.fixture(autouse=True)
def _short_budget(monkeypatch):
    monkeypatch.setattr(task_intake_llm, "LLM_EXTRACT_TIMEOUT_SECONDS", 0.05)


def test_timeout_falls_back_to_deterministic_card(monkeypatch):
    async def slow(message):
        await asyncio.sleep(2)
        return []

    monkeypatch.setattr(task_intake_llm, "llm_extract_items", slow)
    started = time.perf_counter()
    result = asyncio.run(_preview("call the bank tomorrow at 5pm"))
    assert time.perf_counter() - started < 1.5
    item = _item(result)
    assert item["title"] == "call the bank"
    assert item["due_date"] == (local_today("UTC") + timedelta(days=1)).isoformat()
    assert item["due_time"] == "17:00"
    assert "Confirm" in result["response"]


def test_raising_llm_falls_back(monkeypatch):
    async def boom(message):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(task_intake_llm, "llm_extract_items", boom)
    item = _item(asyncio.run(_preview("call the bank tomorrow at 5pm")))
    assert item["due_time"] == "17:00"
    assert item["due_date"] == (local_today("UTC") + timedelta(days=1)).isoformat()


def test_fast_llm_result_is_used(monkeypatch):
    async def fast(message):
        return [IntakeItem("Phone the bank", "general", "high", None, "tomorrow 5:00 PM", due_time="17:00")]

    monkeypatch.setattr(task_intake_llm, "llm_extract_items", fast)
    item = _item(asyncio.run(_preview("call the bank tomorrow at 5pm")))
    assert item["title"] == "Phone the bank"
    assert item["priority"] == "high"


def test_no_date_task_uses_fallback(monkeypatch):
    async def boom(message):
        raise RuntimeError("down")

    monkeypatch.setattr(task_intake_llm, "llm_extract_items", boom)
    item = _item(asyncio.run(_preview("buy milk")))
    assert item["title"] == "buy milk"
    assert item["due_date"] is None


def test_prose_extraction_timeout_returns_deterministic_items(monkeypatch):
    async def slow(client, model, message):
        await asyncio.sleep(2)
        return []

    monkeypatch.setattr(task_intake_llm, "_extract_prose_tasks_call", slow)
    items = asyncio.run(task_intake_llm.extract_prose_tasks(None, "m", "add tasks: buy milk, call mom tomorrow"))
    assert [i.title for i in items] == ["buy milk", "call mom"]
