"""update_scheduling_preferences must pass asyncpg-compatible parameter types.

asyncpg needs datetime.time for ``$n::time`` parameters; strings made every preference save
fail with HTTP 500. Group 1 is DB-free (a strict fake connection). Group 2 uses the real pool.
"""
import asyncio
import datetime
import uuid

import pytest

from backend.memory import structured

pytestmark = pytest.mark.asyncio


class StrictFakeConn:
    """Records calls and rejects parameter types asyncpg would reject for the UPDATE query."""

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if "::time" in query:
            # $1 user_id, $2 flag, $3 start, $4 flag, $5 end, $6 flag, $7 days,
            # $8 flag, $9 buffer, $10 flag, $11 focus
            for flag, idx, name in ((1, 2, "work_start_time"), (3, 4, "work_end_time")):
                if args[flag] and not isinstance(args[idx], datetime.time):
                    raise TypeError(f"{name}: expected datetime.time, got {type(args[idx]).__name__}")
            days = args[6]
            if args[5] and (not isinstance(days, list) or not all(type(d) is int for d in days)):
                raise ValueError(f"work_days must be a list of ints, got {days!r}")
            buf = args[8]
            if args[7] and type(buf) is not int:
                raise ValueError(f"buffer_minutes must be an int, got {buf!r}")
        return "OK"

    async def fetchrow(self, query, *args):
        self.fetchrow_calls.append((query, args))
        return {
            "user_id": args[0],
            "work_start_time": datetime.time(9, 0),
            "work_end_time": datetime.time(18, 0),
            "work_days": [1, 2, 3, 4, 5],
            "buffer_minutes": 15,
            "preferred_focus": "morning",
        }

    async def fetch(self, query, *args):
        return []


def _update_args(conn: StrictFakeConn) -> tuple:
    updates = [a for q, a in conn.executed if "::time" in q]
    assert len(updates) == 1
    return updates[0]


async def test_strict_types_full_update_converts_strings_to_time():
    conn = StrictFakeConn()
    result = await structured.update_scheduling_preferences(
        conn,
        user_id="u1",
        work_start_time="08:00:00",
        work_end_time="20:00",
        work_days=[1, 2, 3, 4, 5, 6],
        buffer_minutes=30,
    )
    args = _update_args(conn)
    assert args[0] == "u1"
    assert args[2] == datetime.time(8, 0)
    assert args[4] == datetime.time(20, 0)
    assert args[6] == [1, 2, 3, 4, 5, 6]
    assert args[8] == 30
    assert isinstance(result, dict)


async def test_strict_types_short_hour_string():
    conn = StrictFakeConn()
    await structured.update_scheduling_preferences(conn, user_id="u1", work_start_time="9:30")
    assert _update_args(conn)[2] == datetime.time(9, 30)


async def test_strict_types_time_objects_accepted():
    conn = StrictFakeConn()
    await structured.update_scheduling_preferences(
        conn, user_id="u1", work_start_time=datetime.time(7, 15), work_end_time=datetime.time(19, 45)
    )
    args = _update_args(conn)
    assert args[2] == datetime.time(7, 15)
    assert args[4] == datetime.time(19, 45)


async def test_strict_types_partial_update_buffer_only():
    conn = StrictFakeConn()
    await structured.update_scheduling_preferences(conn, user_id="u1", buffer_minutes=10)
    args = _update_args(conn)
    assert args[1] is False and args[3] is False and args[5] is False
    assert args[7] is True and args[8] == 10


@pytest.mark.parametrize(
    "kwargs",
    [
        {"work_start_time": "25:00"},
        {"work_end_time": "25:00"},
        {"buffer_minutes": True},
        {"work_days": [True]},
    ],
)
async def test_strict_types_invalid_values_raise_value_error(kwargs):
    conn = StrictFakeConn()
    with pytest.raises(ValueError):
        await structured.update_scheduling_preferences(conn, user_id="u1", **kwargs)


def _as_time_str(value) -> str:
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M:%S")
    return str(value)


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_real_db_preferences_roundtrip():
    from backend.memory.db import get_pool

    pool = await asyncio.wait_for(get_pool(), timeout=15.0)
    user_id = uuid.uuid4().hex
    try:
        async with pool.acquire() as conn:
            await structured.update_scheduling_preferences(
                conn,
                user_id=user_id,
                work_start_time="08:00:00",
                work_end_time="20:00:00",
                work_days=[1, 2, 3, 4, 5, 6],
                buffer_minutes=30,
            )
            prefs = await structured.get_scheduling_preferences(conn, user_id)
            assert _as_time_str(prefs["work_start_time"]) == "08:00:00"
            assert _as_time_str(prefs["work_end_time"]) == "20:00:00"
            assert list(prefs["work_days"]) == [1, 2, 3, 4, 5, 6]
            assert prefs["buffer_minutes"] == 30

            await structured.update_scheduling_preferences(conn, user_id=user_id, buffer_minutes=10)
            prefs = await structured.get_scheduling_preferences(conn, user_id)
            assert _as_time_str(prefs["work_start_time"]) == "08:00:00"
            assert _as_time_str(prefs["work_end_time"]) == "20:00:00"
            assert list(prefs["work_days"]) == [1, 2, 3, 4, 5, 6]
            assert prefs["buffer_minutes"] == 10
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM scheduling_preferences WHERE user_id = $1", user_id)
