"""Single-task preview follow-up: env flag, project/notes carried to the confirmed task, replayed request_id.

NOT RUN when written (the author had no shell). Uses in-memory fakes, no Postgres needed.
"""

import importlib
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from backend.services import chat_idempotency, task_intake
from backend.services.task_intake_parse import IntakeItem


# ---- SINGLE_TASK_PREVIEW environment flag -------------------------------------------------------------
@pytest.mark.parametrize("value,expected", [
    (None, True), ("true", True), ("1", True), ("", True), ("yes-please", True),
    ("0", False), ("false", False), ("FALSE", False), ("No", False), ("off", False), (" Off ", False),
])
def test_single_task_preview_env_flag(monkeypatch, value, expected):
    import backend.orchestrator as orch

    if value is None:
        monkeypatch.delenv("SINGLE_TASK_PREVIEW", raising=False)
    else:
        monkeypatch.setenv("SINGLE_TASK_PREVIEW", value)
    try:
        assert importlib.reload(orch).SINGLE_TASK_PREVIEW is expected
    finally:
        monkeypatch.delenv("SINGLE_TASK_PREVIEW", raising=False)
        importlib.reload(orch)


# ---- 2a: project and notes survive preview -> confirm ---------------------------------------------------
def test_intake_item_accepts_project_and_notes_but_old_items_still_work():
    item = IntakeItem(**{"title": "T", "domain": "code", "priority": "high", "duration_minutes": None,
                         "due_text": "", "project": "Compass", "notes": "see PR 12"})
    assert (item.project, item.notes) == ("Compass", "see PR 12")
    old = IntakeItem(**{"title": "T", "domain": "code", "priority": "high", "duration_minutes": None,
                        "due_text": ""})
    assert old.project is None and old.notes is None


def test_preview_items_carry_project_and_notes():
    from backend.services.task_intake_parse import ParsedIntake

    parsed = ParsedIntake((IntakeItem("Ship it", "code", "high", 60, "", "Compass", "see PR 12"),), 1, ())
    out = task_intake._preview_items(parsed, "UTC")
    assert out[0]["project"] == "Compass" and out[0]["notes"] == "see PR 12"


class _Conn:
    async def execute(self, *a, **k):
        return "INSERT 0 1"


@pytest.mark.asyncio
async def test_confirm_passes_project_and_notes_to_create_task():
    create = AsyncMock(return_value={"id": 7, "title": "Ship it"})
    project = AsyncMock(return_value={"id": 42})
    item = {"title": "Ship it", "domain": "code", "priority": "high", "duration_minutes": None,
            "due_date": None, "due_at": None, "project": "Compass", "notes": "see PR 12"}
    with patch.object(task_intake.structured, "create_task", create), \
         patch.object(task_intake.structured, "get_or_create_project", project):
        created = await task_intake._create_all(_Conn(), [item], "owner-a", "conv-1")
    project.assert_awaited_once()
    assert project.call_args.kwargs["name"] == "Compass" and project.call_args.kwargs["owner_id"] == "owner-a"
    assert create.call_args.kwargs["project_id"] == 42
    assert create.call_args.kwargs["notes"] == "see PR 12"
    assert created[0]["id"] == 7


@pytest.mark.asyncio
async def test_old_pending_rows_without_project_or_notes_still_confirm():
    create = AsyncMock(return_value={"id": 8, "title": "Old"})
    project = AsyncMock()
    old_item = {"title": "Old", "domain": "general", "priority": "medium", "duration_minutes": None,
                "due_date": None, "due_at": None, "due_label": "no due date"}
    with patch.object(task_intake.structured, "create_task", create), \
         patch.object(task_intake.structured, "get_or_create_project", project):
        await task_intake._create_all(_Conn(), [old_item], "owner-a", "conv-1")
    project.assert_not_called()
    assert create.call_args.kwargs["project_id"] is None and create.call_args.kwargs["notes"] is None


@pytest.mark.asyncio
async def test_orchestrator_single_add_sends_project_and_notes_to_the_preview():
    from types import SimpleNamespace  # noqa: F401
    from tests.test_task_title_and_single_add_preview import _Pool, _preview_reply, _send_single

    preview = AsyncMock(return_value=_preview_reply([]))
    await _send_single(
        "add task ship the release tomorrow",
        {"title": "Ship the release", "due_date": "2026-11-17", "project": "Compass", "notes": "tag v1"},
        preview, AsyncMock())
    item = preview.call_args.kwargs["items"][0]
    assert item["project"] == "Compass" and item["notes"] == "tag v1"
    assert _Pool  # imported for parity with the helper module


# ---- 2b: a repeated request_id on a preview returns the same preview -------------------------------------
class _LogConn:
    """Just enough of chat_request_log for _claim / _finish."""

    def __init__(self, rows):
        self.rows = rows

    async def fetchval(self, sql, *args):
        if sql.lstrip().startswith("INSERT INTO chat_request_log"):
            key = (args[0], args[1])
            if key in self.rows:
                return None
            self.rows[key] = {"state": "pending", "response": None}
            return args[1]
        return None  # the stale-claim takeover UPDATE: nothing is stale

    async def fetchrow(self, sql, *args):
        return self.rows.get((args[0], args[1]))

    async def execute(self, sql, *args):
        if "SET state = 'done'" in sql:
            self.rows[(args[0], args[1])].update(state="done", response=args[2])
        elif "SET state = 'committed'" in sql:
            self.rows[(args[0], args[1])].update(state="committed", response=args[2])
        elif "state = 'pending'" in sql:
            self.rows.pop((args[0], args[1]), None)


class _LogPool:
    def __init__(self):
        self.rows = {}

    @asynccontextmanager
    async def _acq(self):
        yield _LogConn(self.rows)

    def acquire(self):
        return self._acq()


def _preview_result(pending_id):
    return {
        "conversation_id": "c1", "response": "I found 1 task. Nothing has been added yet:",
        "message": "I found 1 task.", "skill_used": "add_tasks_preview", "success": True,
        "data": {"pending_action": {"id": pending_id, "items": [{"title": "Buy milk"}]}},
        "verifiable": False, "routing_latency_ms": 1,
    }


def test_preview_is_stored_for_replay_but_never_reported_as_committed():
    res = _preview_result(1)
    assert chat_idempotency.is_storable(res) is True
    assert chat_idempotency.is_replayable(res) is False
    assert chat_idempotency.committed_summary(res) is None
    assert chat_idempotency.committed_event(res) == ""
    failed = {**res, "success": False}
    assert chat_idempotency.is_storable(failed) is False


@pytest.mark.asyncio
async def test_same_request_id_on_a_preview_returns_the_same_pending_action():
    pool = _LogPool()
    calls = []

    async def core(conversation_id=None, message="", user_id=None, pool=None):
        calls.append(message)  # each real run would insert a new chat_pending_actions row
        return _preview_result(len(calls))

    kwargs = {"conversation_id": "c1", "message": "add task buy milk tomorrow", "user_id": "owner-a", "pool": pool}
    first = await chat_idempotency.run_chat_request(core, (), dict(kwargs), request_id="req-abcdef12", tz="UTC")
    second = await chat_idempotency.run_chat_request(core, (), dict(kwargs), request_id="req-abcdef12", tz="UTC")

    assert len(calls) == 1, "the second send must not run the intake again"
    assert first["data"]["pending_action"]["id"] == 1
    assert second["data"]["pending_action"]["id"] == 1
    assert second["replayed"] is True
    stored = pool.rows[("owner-a", "req-abcdef12")]
    assert stored["state"] == "done" and json.loads(stored["response"])["skill_used"] == "add_tasks_preview"


@pytest.mark.asyncio
async def test_a_different_request_id_still_makes_a_new_preview():
    pool = _LogPool()
    calls = []

    async def core(conversation_id=None, message="", user_id=None, pool=None):
        calls.append(message)
        return _preview_result(len(calls))

    kwargs = {"conversation_id": "c1", "message": "add task buy milk tomorrow", "user_id": "owner-a", "pool": pool}
    await chat_idempotency.run_chat_request(core, (), dict(kwargs), request_id="req-abcdef12", tz="UTC")
    await chat_idempotency.run_chat_request(core, (), dict(kwargs), request_id="req-zzzzzz99", tz="UTC")
    assert len(calls) == 2
