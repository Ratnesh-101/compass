"""GET messages returns the conversation's active pending action (owner-scoped) so the card survives a reload."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.routers import chat


class Conn:
    pass


class Acquire:
    async def __aenter__(self):
        return Conn()

    async def __aexit__(self, *a):
        return False


class Pool:
    def acquire(self):
        return Acquire()


def _setup(monkeypatch, ident, getter, access=(True, None)):
    async def get_pool():
        return Pool()

    async def check(conn, cid, **kw):
        return access

    async def recent(conn, cid, limit=50):
        return [{"id": 1, "role": "assistant", "content": 'Reply "Confirm" to add it',
                 "created_at": datetime.now(timezone.utc)}]

    async def states(conn, ids):
        return {}

    monkeypatch.setattr(chat, "get_pool", get_pool)
    monkeypatch.setattr(chat, "_get_current_identity", lambda r: ident)
    monkeypatch.setattr(chat.conversations, "check_conversation_access", check)
    monkeypatch.setattr(chat.conversations, "get_recent_messages", recent)
    monkeypatch.setattr(chat, "fetch_message_states", states)
    monkeypatch.setattr(chat, "get_active_chat_pending_action", getter)


def _ident(user_id=None, guest_id=None):
    return SimpleNamespace(user_id=user_id, guest_id=guest_id, is_admin=False)


def _row(owner):
    return {"id": 7, "action": "add_tasks", "count": 2, "owner_identity": owner,
            "task_titles": [{"title": "a"}, {"title": "b"}], "status": "pending",
            "created_at": datetime.now(timezone.utc), "expires_at": datetime.now(timezone.utc)}


def _owner_getter(owner):
    async def getter(conn, owner_identity, conv_id):
        return _row(owner) if owner_identity == owner else None
    return getter


@pytest.mark.asyncio
async def test_owner_gets_pending_action_serialised(monkeypatch):
    _setup(monkeypatch, _ident(user_id="u1"), _owner_getter("u1"))
    res = await chat.get_messages(str(uuid.uuid4()), object(), limit=50)
    pa = res.pending_action
    assert pa["id"] == 7 and pa["kind"] == "add_tasks" and pa["action"] == "add_tasks"
    assert pa["count"] == 2 and len(pa["items"]) == 2
    assert isinstance(pa["expires_at"], str) and isinstance(pa["created_at"], str)
    assert "owner_identity" not in pa
    res.model_dump_json()


@pytest.mark.asyncio
async def test_other_owner_and_guest_get_none(monkeypatch):
    _setup(monkeypatch, _ident(user_id="u2"), _owner_getter("u1"))
    assert (await chat.get_messages(str(uuid.uuid4()), object(), limit=50)).pending_action is None
    _setup(monkeypatch, _ident(guest_id="g1"), _owner_getter("u1"))
    assert (await chat.get_messages(str(uuid.uuid4()), object(), limit=50)).pending_action is None
    _setup(monkeypatch, None, _owner_getter("u1"))
    assert (await chat.get_messages(str(uuid.uuid4()), object(), limit=50)).pending_action is None


@pytest.mark.asyncio
async def test_none_when_getter_returns_none_or_fails(monkeypatch):
    async def none_getter(conn, o, c):
        return None

    async def boom(conn, o, c):
        raise RuntimeError("db")

    _setup(monkeypatch, _ident(user_id="u1"), none_getter)
    res = await chat.get_messages(str(uuid.uuid4()), object(), limit=50)
    assert res.pending_action is None and len(res.messages) == 1
    _setup(monkeypatch, _ident(user_id="u1"), boom)
    res = await chat.get_messages(str(uuid.uuid4()), object(), limit=50)
    assert res.pending_action is None and len(res.messages) == 1
