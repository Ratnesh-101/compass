"""Continue mode accepts "last": a message that just finished streaming has no id on the client yet."""

from __future__ import annotations

import pytest

from backend.services.chat_stream_extras import LAST_MESSAGE, load_continue_target

CONV = "11111111-1111-1111-1111-111111111111"


class _Conn:
    def __init__(self, row=None, prior=None):
        self.row = row
        self.prior = prior or []
        self.fetchrow_calls = []

    async def fetchrow(self, sql, *args):
        self.fetchrow_calls.append((sql, args))
        return self.row

    async def fetch(self, sql, *args):
        return self.prior


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


def _row(mid=42, content="Partial answer that was cut"):
    return {"id": mid, "role": "assistant", "content": content, "conversation_id": CONV}


@pytest.mark.asyncio
async def test_last_resolves_to_the_newest_assistant_message_of_the_conversation():
    conn = _Conn(row=_row(), prior=[{"role": "user", "content": "Explain sorting"}])
    target = await load_continue_target(_Pool(conn), LAST_MESSAGE, "guest-abc", CONV)
    assert target is not None and target["id"] == 42 and target["content"] == "Partial answer that was cut"
    sql, args = conn.fetchrow_calls[0]
    assert "ORDER BY m.id DESC LIMIT 1" in sql and "m.role = 'assistant'" in sql
    # ownership is part of the query, for users and for guests
    assert "c.user_id = $2" in sql and "c.guest_id = $2 AND c.user_id IS NULL" in sql
    assert args == (CONV, "guest-abc")


@pytest.mark.asyncio
async def test_last_is_case_insensitive():
    conn = _Conn(row=_row())
    assert await load_continue_target(_Pool(conn), " LAST ", "u1", CONV) is not None


@pytest.mark.asyncio
async def test_last_needs_a_conversation_and_an_owner():
    conn = _Conn(row=_row())
    assert await load_continue_target(_Pool(conn), LAST_MESSAGE, "u1", None) is None
    assert await load_continue_target(_Pool(conn), LAST_MESSAGE, None, CONV) is None
    assert conn.fetchrow_calls == []  # nothing was queried


@pytest.mark.asyncio
async def test_last_returns_none_when_the_caller_owns_no_assistant_message():
    conn = _Conn(row=None)
    assert await load_continue_target(_Pool(conn), LAST_MESSAGE, "someone-else", CONV) is None


@pytest.mark.asyncio
async def test_a_numeric_id_still_works_and_other_text_is_rejected():
    conn = _Conn(row=_row(mid=7))
    target = await load_continue_target(_Pool(conn), "7", "u1")
    assert target is not None and target["id"] == 7
    assert conn.fetchrow_calls[0][1] == (7, "u1")
    assert await load_continue_target(_Pool(_Conn(row=_row())), "latest", "u1", CONV) is None
