"""Fixes from the chat-streaming code review (findings 1, 2, 3, 5, 9).

NOT RUN when written (the author had no shell). No database needed: fakes only.
"""

import asyncio
from datetime import date

import pytest

from backend.services import chat_idempotency, task_intake
from backend.services.chat_stream_extras import (
    StreamState,
    _append_to_message,
    continuation_events,
    orchestrate_with_early_commit,
)
from backend.services.task_context import enrich_title, find_context
from backend.services.task_dates import reconcile_due_date

MONDAY = date(2026, 11, 16)


class _Request:
    async def is_disconnected(self):
        return False


async def _collect(agen):
    return [x async for x in agen]


# ---- finding 1: a failed continuation is reported as truncated ----
def test_truncated_covers_failed_continuation():
    assert StreamState(finish="length").truncated
    assert StreamState(finish=None, continuation_failed=True).truncated
    assert not StreamState(finish="stop").truncated


class _FailingCompletions:
    async def create(self, **kwargs):
        raise TimeoutError("upstream timed out")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingClient:
    chat = _FailingChat()


@pytest.mark.asyncio
async def test_failed_continuation_leaves_the_state_truncated():
    state = StreamState(full_text="the answer was cut o", emitted_text="the answer was cut o", finish="length")
    await _collect(continuation_events(_FailingClient(), {"model": "m"}, [], state, _Request(), 2))
    assert state.continuation_failed is True
    assert state.truncated is True  # cut off AND the follow-up failed: never reported as complete


# ---- finding 2: the confirm path signals the early commit ----
class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def transaction(self):
        return _Tx()


@pytest.mark.asyncio
async def test_confirm_add_tasks_sends_committed_before_the_orchestrator_returns(monkeypatch):
    async def fake_resolve(conn, action_id, status):
        return True

    async def fake_create_all(conn, items, owner, conv_id, tz_name=None):
        return [{"id": 7, "title": "Write tests", "due_label": "no due date"}]

    monkeypatch.setattr(task_intake, "resolve_chat_pending_action", fake_resolve)
    monkeypatch.setattr(task_intake, "_create_all", fake_create_all)
    monkeypatch.setattr(task_intake, "_stored_items", lambda action: [])
    release = asyncio.Event()

    async def fake_handle(**kwargs):
        await task_intake.confirm_add_tasks(_Conn(), {"id": 1}, "owner-1", "conv-1")
        await release.wait()  # e.g. the post-save write waiting on a drained pool
        return {"success": True, "skill_used": "pending_action_confirm", "response": "late", "data": {}}

    agen = orchestrate_with_early_commit(fake_handle, trace_id="rid-confirm", message="confirm")
    kind, evt = await asyncio.wait_for(agen.__anext__(), 2)
    assert kind == "committed"
    assert '"type": "committed"' in evt and '"skill_used": "pending_action_confirm"' in evt
    assert '"count": 1' in evt
    release.set()
    rest = await _collect(agen)
    assert [k for k, _ in rest] == ["result"]


def test_committed_summary_for_a_confirm_result():
    result = {"success": True, "skill_used": "pending_action_confirm", "data": {"created_count": 3}}
    assert chat_idempotency.committed_summary(result) == {"skill_used": "pending_action_confirm", "count": 3}


# ---- finding 3: the date reconciler ----
@pytest.mark.parametrize("msg", [
    "add task submit report friday next week",
    "add task submit report next week friday",
    "add task submit report monday of next week",
    "add task submit report the friday after next",
    "add task clean the desk this weekend",
])
def test_reconcile_keeps_the_models_date_for_compound_phrases(msg):
    model = date(2026, 11, 27)
    assert reconcile_due_date(msg, model, MONDAY) == model


def test_reconcile_does_not_invent_a_date_for_a_weekday_in_the_title():
    assert reconcile_due_date("prepare Friday newsletter", None, MONDAY) is None
    assert reconcile_due_date("add task prepare Friday newsletter", None, MONDAY) is None


def test_reconcile_fills_a_missing_date_when_there_is_a_due_cue():
    assert reconcile_due_date("add task submit report by friday", None, MONDAY) == date(2026, 11, 20)
    assert reconcile_due_date("add task submit report on friday", None, MONDAY) == date(2026, 11, 20)
    assert reconcile_due_date("add task buy milk tomorrow", None, MONDAY) == date(2026, 11, 17)
    assert reconcile_due_date("add task buy milk in 3 days", None, MONDAY) == date(2026, 11, 19)


# ---- finding 5: unrelated "for ... assignment" text is not a course context ----
def test_context_is_not_taken_from_unrelated_clauses():
    assert find_context("call mom for dinner after the assignment") is None
    assert enrich_title("Call mom", "call mom for dinner after the assignment") == "Call mom"


# ---- finding 9: compare-and-set append ----
class _CasConn:
    def __init__(self, status):
        self.status = status
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return self.status


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


@pytest.mark.asyncio
async def test_append_is_skipped_when_the_message_changed_meanwhile():
    conn = _CasConn("UPDATE 0")
    applied = await _append_to_message(_Pool(conn), 5, " more", False, None, "original")
    assert applied is False
    assert "AND content = $3" in conn.calls[0][0]
    assert len(conn.calls) == 1  # no state update after a lost race


@pytest.mark.asyncio
async def test_append_applies_when_the_message_is_unchanged():
    conn = _CasConn("UPDATE 1")
    assert await _append_to_message(_Pool(conn), 5, " more", False, None, "original") is True
