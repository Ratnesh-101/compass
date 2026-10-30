"""Chat task intake against local Postgres: questions, pasted lists, timezones, retries."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from backend.memory import structured
from backend.memory.db import get_pool
from backend.models import StreamChatRequest
from backend.orchestrator import handle_message
from backend.services import chat_stream
from backend.services.task_time import local_today

OWNER = "test_intake_owner"
OTHER = "test_intake_other"
CONV = "test-intake-conv-0001"
IST = "Asia/Calcutta"
PASTE = (
    "Title | Domain | Due | Priority | Duration\n"
    "Record & submit hackathon demo video | Hackathon | Today, 9:00 PM | High | 4h\n"
    "Finalize Devpost submission | Hackathon | Today, 10:00 PM | High | 2h\n"
    "Computer Architecture Lab 5 submission | Coursework | Tomorrow, 11:59 PM | High | 3h\n"
    "DBMS assignment 3 | Coursework | Tomorrow | Medium | 2h\n"
    "Theory of Computation quiz prep | Coursework | Day after tomorrow | Medium | 2h\n"
)


@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    pool = await get_pool()
    if pool is None:
        pytest.skip("local Postgres is not available")
    await _wipe(pool)
    yield pool
    await _wipe(pool)


async def _wipe(pool):
    users = [OWNER, OTHER]
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM agent_audit_log WHERE approved_by = ANY($1::text[])", users)
        await conn.execute("DELETE FROM tasks WHERE user_id = ANY($1::text[])", users)
        await conn.execute("DELETE FROM chat_pending_actions WHERE owner_identity = ANY($1::text[])", users)
        await conn.execute("DELETE FROM chat_request_log WHERE owner_identity = ANY($1::text[])", users)
        await conn.execute("DELETE FROM user_profile_facts WHERE user_id = ANY($1::text[])", users)


async def _send(message, user=OWNER, **kwargs):
    return await handle_message(conversation_id=CONV, message=message, user_id=user, persist=False, **kwargs)


async def _tasks(pool, user=OWNER):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM tasks WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id", user)
    return [dict(r) for r in rows]


async def _pending(pool, user=OWNER):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM chat_pending_actions WHERE owner_identity = $1 AND status = 'pending'", user)


def _utc(local_date, hour, minute, tz):
    return datetime(local_date.year, local_date.month, local_date.day, hour, minute,
                    tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


# ---- A: questions never create tasks -------------------------------------------------------------
@pytest.mark.asyncio
async def test_capability_question_creates_nothing_and_asks_for_details(clean_state):
    res = await _send("can you add deadlines for me?")
    assert res["success"] is False or res["skill_used"] != "add_task"
    assert "Done" not in res["response"] and "Added task" not in res["response"]
    assert "task name" in res["response"] and "due" in res["response"].lower()
    assert await _tasks(clean_state) == []


@pytest.mark.asyncio
async def test_model_dispatched_add_task_for_a_question_is_refused(clean_state):
    res = await handle_message(
        conversation_id=CONV, message="can you add deadlines for me?", user_id=OWNER, persist=False,
        pre_routed_skill="add_task", pre_routed_args={"title": "Can you deadlines for me"})
    assert res["success"] is False and "Done" not in res["response"]
    assert await _tasks(clean_state) == []


@pytest.mark.asyncio
async def test_model_dispatched_add_task_with_a_bad_title_is_refused(clean_state):
    res = await handle_message(
        conversation_id=CONV, message="add a task", user_id=OWNER, persist=False,
        pre_routed_skill="add_task", pre_routed_args={"title": "   "})
    assert res["success"] is False and "name" in res["response"]
    assert await _tasks(clean_state) == []


@pytest.mark.asyncio
async def test_a_normal_command_still_creates_the_task_in_one_step(clean_state):
    res = await _send("add task buy milk tomorrow 5pm", tz=IST)
    assert res["success"] is True and res["skill_used"] == "add_task"
    assert res["response"].startswith("Done! Added task 'Buy milk'") and "17:00" in res["response"] and IST in res["response"]
    (task,) = await _tasks(clean_state)
    tomorrow = local_today(IST) + timedelta(days=1)
    assert task["title"] == "Buy milk" and task["due_date"] == tomorrow
    assert task["due_at"] == _utc(tomorrow, 17, 0, IST)


@pytest.mark.asyncio
async def test_polite_command_with_a_concrete_task_creates_it(clean_state):
    res = await _send("could you add a task to submit the report tomorrow?")
    assert res["success"] is True
    assert [t["title"] for t in await _tasks(clean_state)] == ["Submit the report"]


# ---- B: pasted lists use the preview + confirm flow -----------------------------------------------
async def _preview(tz=IST, message=PASTE, user=OWNER):
    res = await _send(message, user=user, tz=tz)
    assert res["skill_used"] == "add_tasks_preview" and res["success"] is True
    return res


@pytest.mark.asyncio
async def test_five_row_paste_previews_then_creates_exactly_five_with_fields(clean_state):
    res = await _preview()
    assert "I found 5 tasks" in res["response"] and "Nothing has been added yet" in res["response"]
    assert res["data"]["pending_action"]["action"] == "add_tasks" and len(res["data"]["pending_action"]["items"]) == 5
    assert await _tasks(clean_state) == [] and await _pending(clean_state) == 1

    done = await _send("Confirm", tz=IST)
    assert done["success"] is True and done["data"]["created_count"] == 5
    assert "Added 5 tasks" in done["response"] and "Done" not in done["response"]

    rows = await _tasks(clean_state)
    assert [t["title"] for t in rows] == [
        "Record & submit hackathon demo video", "Finalize Devpost submission",
        "Computer Architecture Lab 5 submission", "DBMS assignment 3", "Theory of Computation quiz prep"]
    assert [t["domain"] for t in rows] == ["hackathon", "hackathon", "coursework", "coursework", "coursework"]
    assert [t["priority"] for t in rows] == ["high", "high", "high", "medium", "medium"]
    assert [t["duration_minutes"] for t in rows] == [240, 120, 180, 120, 120]
    today = local_today(IST)
    assert rows[0]["due_at"] == _utc(today, 21, 0, IST) and rows[0]["due_date"] == today
    assert rows[1]["due_at"] == _utc(today, 22, 0, IST)
    assert rows[2]["due_at"] == _utc(today + timedelta(days=1), 23, 59, IST)
    assert rows[3]["due_date"] == today + timedelta(days=1) and rows[3]["due_at"] is None
    assert rows[4]["due_date"] == today + timedelta(days=2) and rows[4]["due_at"] is None
    assert await _pending(clean_state) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tz", [None, "Mars/Phobos", "../etc/passwd"])
async def test_missing_or_invalid_timezone_falls_back_to_utc(clean_state, tz):
    await _preview(tz=tz)
    await _send("Confirm", tz=tz)
    first = (await _tasks(clean_state))[0]
    assert first["due_at"] == _utc(local_today("UTC"), 21, 0, "UTC")


@pytest.mark.asyncio
async def test_invalid_request_timezone_uses_the_stored_profile_timezone(clean_state):
    async with clean_state.acquire() as conn:
        await conn.execute("INSERT INTO user_profile_facts (user_id, key, value) VALUES ($1, 'timezone', $2)", OWNER, IST)
    await _preview(tz="Mars/Phobos")
    await _send("Confirm")
    assert (await _tasks(clean_state))[0]["due_at"] == _utc(local_today(IST), 21, 0, IST)


@pytest.mark.asyncio
async def test_preview_shows_times_in_the_users_zone_and_no_due_date_items(clean_state):
    res = await _preview(message="Title | Due\nBuy milk | Tomorrow, 5pm\nCall mom |\nRead paper | whenever")
    text = res["response"]
    assert f"({IST})" in text and "no due date" in text and 'could not read "whenever"' in text
    await _send("Confirm", tz=IST)
    by_title = {t["title"]: t for t in await _tasks(clean_state)}
    assert by_title["Call mom"]["due_date"] is None and by_title["Read paper"]["due_date"] is None


@pytest.mark.asyncio
async def test_cancel_creates_nothing(clean_state):
    await _preview()
    res = await _send("Cancel")
    assert "cancelled" in res["response"].lower()
    assert await _tasks(clean_state) == [] and await _pending(clean_state) == 0
    again = await _send("Confirm")
    assert again["success"] is False and await _tasks(clean_state) == []


@pytest.mark.asyncio
async def test_confirming_twice_creates_five_not_ten(clean_state):
    await _preview()
    first = await _send("Confirm", tz=IST)
    second = await _send("Confirm", tz=IST)
    assert first["success"] is True and second["success"] is False
    assert len(await _tasks(clean_state)) == 5


@pytest.mark.asyncio
async def test_another_user_cannot_confirm_the_action(clean_state):
    await _preview()
    stolen = await _send("Confirm", user=OTHER, tz=IST)
    assert stolen["success"] is False
    assert await _tasks(clean_state, OTHER) == [] and await _tasks(clean_state) == []
    assert await _pending(clean_state) == 1
    assert (await _send("Confirm", tz=IST))["success"] is True
    assert len(await _tasks(clean_state)) == 5 and await _tasks(clean_state, OTHER) == []


@pytest.mark.asyncio
async def test_expired_preview_cannot_be_confirmed(clean_state):
    await _preview()
    async with clean_state.acquire() as conn:
        await conn.execute("UPDATE chat_pending_actions SET expires_at = now() - interval '1 minute' WHERE owner_identity = $1", OWNER)
    res = await _send("Confirm")
    assert res["success"] is False and await _tasks(clean_state) == []


@pytest.mark.asyncio
async def test_ordinal_reply_is_not_a_confirmation(clean_state):
    await _preview()
    res = await _send("1")
    assert "isn't a confirmation" in res["response"] and await _tasks(clean_state) == []
    assert await _pending(clean_state) == 1


@pytest.mark.asyncio
async def test_a_new_paste_supersedes_the_older_preview(clean_state):
    await _preview()
    await _preview(message="Title | Due\nOnly one | Tomorrow\nSecond one | Friday")
    await _send("Confirm", tz=IST)
    assert sorted(t["title"] for t in await _tasks(clean_state)) == ["Only one", "Second one"]


@pytest.mark.asyncio
async def test_twenty_five_items_are_truncated_with_a_clear_message(clean_state):
    rows = "\n".join(f"Task number {n} | General | Tomorrow | Low | 1h" for n in range(25))
    res = await _preview(message="Title | Domain | Due | Priority | Duration\n" + rows)
    assert "I found 20 tasks" in res["response"] and "at most 20" in res["response"] and "25 items" in res["response"]
    await _send("Confirm", tz=IST)
    assert len(await _tasks(clean_state)) == 20


@pytest.mark.asyncio
async def test_if_any_item_fails_none_are_created_and_the_reason_is_given(clean_state):
    await _preview()
    real_create = structured.create_task
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk full")
        return await real_create(*args, **kwargs)

    with patch("backend.services.task_intake.structured.create_task", side_effect=flaky):
        res = await _send("Confirm", tz=IST)
    assert res["success"] is False and "No tasks were created" in res["response"] and "RuntimeError" in res["response"]
    assert "Done" not in res["response"] and await _tasks(clean_state) == []
    assert await _pending(clean_state) == 1, "a failed attempt leaves the preview confirmable"
    assert (await _send("Confirm", tz=IST))["success"] is True and len(await _tasks(clean_state)) == 5


# ---- E: retries are idempotent --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_same_request_id_sent_twice_creates_one_task(clean_state):
    first = await _send("add task buy milk tomorrow 5pm", request_id="req-retry-0001")
    second = await _send("add task buy milk tomorrow 5pm", request_id="req-retry-0001")
    assert first["success"] is True and second.get("replayed") is True
    assert second["response"] == first["response"]
    assert len(await _tasks(clean_state)) == 1


@pytest.mark.asyncio
async def test_distinct_request_ids_are_independent_and_missing_ids_still_work(clean_state):
    await _send("add task alpha one tomorrow", request_id="req-distinct-1")
    await _send("add task beta two tomorrow", request_id="req-distinct-2")
    await _send("add task gamma three tomorrow")
    assert len(await _tasks(clean_state)) == 3


@pytest.mark.asyncio
async def test_request_ids_are_scoped_to_the_owner(clean_state):
    await _send("add task alpha one tomorrow", request_id="req-shared-001")
    res = await _send("add task alpha one tomorrow", user=OTHER, request_id="req-shared-001")
    assert res["success"] is True and res.get("replayed") is None
    assert len(await _tasks(clean_state)) == 1 and len(await _tasks(clean_state, OTHER)) == 1


@pytest.mark.asyncio
async def test_failed_or_non_mutating_requests_release_their_request_id(clean_state):
    first = await _send("can you add deadlines for me?", request_id="req-release-01")
    assert first.get("replayed") is None
    retry = await _send("add task buy milk tomorrow", request_id="req-release-01")
    assert retry["success"] is True and len(await _tasks(clean_state)) == 1


@pytest.mark.asyncio
async def test_confirm_retry_with_the_same_request_id_replays_the_five_tasks(clean_state):
    await _preview()
    first = await _send("Confirm", tz=IST, request_id="req-confirm-01")
    again = await _send("Confirm", tz=IST, request_id="req-confirm-01")
    assert first["success"] is True and again["success"] is True and again.get("replayed") is True
    assert len(await _tasks(clean_state)) == 5


@pytest.mark.asyncio
async def test_a_cancelled_request_still_stores_its_result_so_retry_does_not_duplicate(clean_state):
    async def slow_core(conversation_id=None, message="", user_id=None, guest_id=None, pool=None, **kwargs):
        async with clean_state.acquire() as conn:
            await structured.create_task(conn, domain="general", title="Cancelled mid-flight", user_id=user_id)
        await asyncio.sleep(0.3)  # the client disconnects while the reply is still being produced
        return {"conversation_id": CONV, "response": "Done! Added task", "skill_used": "add_task", "success": True, "data": None}

    with patch("backend.orchestrator._handle_message_core", new=slow_core):
        first = asyncio.ensure_future(_send("add task cancelled mid-flight", request_id="req-cancel-001"))
        await asyncio.sleep(0.1)
        first.cancel()
        await asyncio.sleep(0.5)
        retry = await _send("add task cancelled mid-flight", request_id="req-cancel-001")
    assert retry.get("replayed") is True
    assert len(await _tasks(clean_state)) == 1


@pytest.mark.asyncio
async def test_a_request_still_in_flight_does_not_run_twice(clean_state):
    async with clean_state.acquire() as conn:
        await conn.execute("INSERT INTO chat_request_log (owner_identity, request_id) VALUES ($1, 'req-inflight-1')", OWNER)
    res = await _send("add task buy milk tomorrow", request_id="req-inflight-1")
    assert res["success"] is False and "still being processed" in res["response"]
    assert await _tasks(clean_state) == []


# ---- D: the stream tells the client a change is saved ----------------------------------------------
async def _stream(message, request_id=None, tz=None):
    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)
    req = StreamChatRequest(message=message, conversation_id=CONV, request_id=request_id, tz=tz)
    with patch("backend.services.chat_stream._schedule_stream_persistence", MagicMock()):
        events = [e async for e in chat_stream.generate_chat_events(req, request, user_id=OWNER)]
    return [json.loads(e[6:]) for e in events if e.startswith("data: ")]


@pytest.mark.asyncio
async def test_stream_announces_the_commit_before_the_reply_text(clean_state):
    events = await _stream("add task buy milk tomorrow 5pm", request_id="req-stream-001", tz=IST)
    kinds = [e["type"] for e in events]
    assert "committed" in kinds and kinds.index("committed") < kinds.index("token") < kinds.index("done")
    assert next(e for e in events if e["type"] == "committed")["skill_used"] == "add_task"
    assert len(await _tasks(clean_state)) == 1


@pytest.mark.asyncio
async def test_stream_retry_replays_the_result_without_creating_again(clean_state):
    await _stream("add task buy milk tomorrow 5pm", request_id="req-stream-002", tz=IST)
    events = await _stream("add task buy milk tomorrow 5pm", request_id="req-stream-002", tz=IST)
    assert [e["type"] for e in events][-1] == "done" and events[-1].get("replayed") is True
    assert any(e["type"] == "committed" for e in events)
    assert len(await _tasks(clean_state)) == 1


@pytest.mark.asyncio
async def test_stream_paste_returns_a_preview_without_calling_the_model(clean_state):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=AssertionError("model must not be called"))
    with patch("backend.router.get_openai_client", return_value=client):
        events = await _stream(PASTE, request_id="req-stream-003", tz=IST)
    client.chat.completions.create.assert_not_called()
    done = events[-1]
    assert done["type"] == "done" and done["pending_action"]["action"] == "add_tasks"
    assert not any(e["type"] == "committed" for e in events)
    assert await _tasks(clean_state) == []


@pytest.mark.asyncio
async def test_stream_capability_question_creates_nothing(clean_state):
    events = await _stream("can you add deadlines for me?")
    text = "".join(e.get("value", "") for e in events if e["type"] == "token")
    assert "task name" in text and await _tasks(clean_state) == []
