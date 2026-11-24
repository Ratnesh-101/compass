"""
Regression tests: ownerless conversations must never leak to callers without an identity.

Covers list_conversations, check_conversation_access and the list_past_conversations route.
All database objects are fakes; no SQL is executed.
"""

import inspect
import uuid

import pytest

from backend.memory import conversations
from backend.routers import chat

FORBIDDEN = "Forbidden"


class FakeConn:
    """Records every call. fetch/execute/fetchval raise so a swallowed call is still detectable."""

    def __init__(self, row=None):
        self.row = row
        self.calls = []

    async def fetch(self, *args, **kwargs):
        self.calls.append(("fetch", args))
        raise AssertionError("conn.fetch must not be called")

    async def execute(self, *args, **kwargs):
        self.calls.append(("execute", args))
        raise AssertionError("conn.execute must not be called")

    async def fetchval(self, *args, **kwargs):
        self.calls.append(("fetchval", args))
        raise AssertionError("conn.fetchval must not be called")

    async def fetchrow(self, *args, **kwargs):
        self.calls.append(("fetchrow", args))
        return self.row


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


def _row(user_id=None, guest_id=None):
    return {"id": uuid.uuid4(), "user_id": user_id, "guest_id": guest_id, "is_shared": False}


async def _access(row, **kwargs):
    conn = FakeConn(row=row)
    return await conversations.check_conversation_access(conn, str(uuid.uuid4()), **kwargs)


# --- (1) list_conversations without identity ---------------------------------
@pytest.mark.asyncio
async def test_list_conversations_no_identity_returns_empty_without_query():
    conn = FakeConn()
    result = await conversations.list_conversations(conn, user_id=None, guest_id=None)
    assert result == []
    assert [c for c in conn.calls if c[0] == "fetch"] == []


@pytest.mark.asyncio
async def test_list_conversations_no_identity_touches_nothing():
    conn = FakeConn()
    await conversations.list_conversations(conn, user_id="", guest_id="")
    assert conn.calls == []


# --- (2) SQL no longer has the ownerless fallback ----------------------------
def test_list_sql_has_no_ownerless_fallback():
    src = inspect.getsource(conversations.list_conversations)
    assert "c.user_id IS NULL AND (c.guest_id IS NULL" not in src


# --- (3) check_conversation_access -------------------------------------------
@pytest.mark.asyncio
async def test_ownerless_conversation_denied_without_identity():
    ok, err = await _access(_row())
    assert ok is False
    assert err and FORBIDDEN in err


@pytest.mark.asyncio
async def test_ownerless_conversation_denied_to_guest():
    ok, _ = await _access(_row(), guest_id="guest-" + uuid.uuid4().hex)
    assert ok is False


@pytest.mark.asyncio
async def test_ownerless_conversation_denied_to_user():
    ok, _ = await _access(_row(), user_id="user-" + uuid.uuid4().hex)
    assert ok is False


@pytest.mark.asyncio
async def test_ownerless_conversation_allowed_to_admin():
    ok, err = await _access(_row(), is_admin=True)
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_guest_conversation_access():
    owner = "guest-" + uuid.uuid4().hex
    row = _row(guest_id=owner)
    assert (await _access(row, guest_id=owner)) == (True, None)
    assert (await _access(row, guest_id="guest-" + uuid.uuid4().hex))[0] is False
    assert (await _access(row))[0] is False


@pytest.mark.asyncio
async def test_user_conversation_access():
    owner = "User-" + uuid.uuid4().hex
    row = _row(user_id=owner)
    assert (await _access(row, user_id=owner.lower())) == (True, None)
    assert (await _access(row, user_id=owner.upper())) == (True, None)
    assert (await _access(row, user_id="user-" + uuid.uuid4().hex))[0] is False
    assert (await _access(row, guest_id=owner))[0] is False
    assert (await _access(row))[0] is False


@pytest.mark.asyncio
async def test_invalid_conversation_id():
    conn = FakeConn(row=_row())
    result = await conversations.check_conversation_access(conn, "not-a-uuid", user_id="u")
    assert result == (False, "Invalid conversation ID")


@pytest.mark.asyncio
async def test_missing_conversation():
    result = await _access(None, user_id="u")
    assert result == (False, "Conversation not found")


# --- (4) route handler --------------------------------------------------------
@pytest.mark.asyncio
async def test_list_past_conversations_no_identity_returns_empty_and_skips_db(monkeypatch):
    conn = FakeConn()

    async def fake_get_pool():
        return FakePool(conn)

    monkeypatch.setattr(chat, "get_pool", fake_get_pool)
    monkeypatch.setattr(chat, "_get_current_identity", lambda request: None)

    result = await chat.list_past_conversations(object(), limit=30, include_archived=False)

    assert result == {"conversations": [], "total": 0}
    assert conn.calls == []
