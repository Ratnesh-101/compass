"""Multi-task intake split, named edits, delete-after-retraction and per-request replay (no database)."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from backend.services import chat_followup_edit, chat_idempotency, chat_task_actions, task_intake, task_intake_llm
from backend.services.chat_task_actions import parse_task_action_intent
from backend.services.task_intake_parse import IntakeItem, merge_missing, parse_clauses

TZ = "Asia/Kolkata"
MSG_3A = "Add DBMS assignment Tuesday 5pm, gym tomorrow 7am and ML report due Dec 5"
MSG_3B = "Add: finish OS lab Friday 3pm (coursework); call mom tomorrow 6pm; run in the Health area tomorrow 7am"
MSG_5 = (
    "remind me to submit DBMS assignment Tuesday 5pm\n"
    "buy groceries tomorrow, gym tomorrow 7am (health) and email prof Rao Friday; pay rent Dec 1"
)


def _run(coro):
    return asyncio.run(coro)


class _Pool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


def _titles(items):
    return [i.title for i in items]


def test_three_task_message_gets_all_tasks_with_own_dates():
    items, unparsed = parse_clauses(MSG_3A)
    assert unparsed == []
    assert _titles(items) == ["DBMS assignment", "gym", "ML report"]
    assert [i.due_text for i in items] == ["Tuesday 5pm", "tomorrow 7am", "Dec 5"]
    assert items[1].due_time == "07:00"  # "tomorrow 7am" belongs to gym
    assert items[0].due_time == "17:00"


def test_second_three_task_message_maps_area_and_parenthesised_domain():
    items, unparsed = parse_clauses(MSG_3B)
    assert unparsed == []
    assert _titles(items) == ["finish OS lab", "call mom", "run"]
    assert [i.domain for i in items] == ["coursework", "general", "health"]
    assert items[2].due_text == "tomorrow 7am"


def test_five_task_messy_message():
    items, unparsed = parse_clauses(MSG_5)
    assert unparsed == []
    assert _titles(items) == ["submit DBMS assignment", "buy groceries", "gym", "email prof Rao", "pay rent"]
    assert items[2].domain == "health"
    assert [i.due_text for i in items] == ["Tuesday 5pm", "tomorrow", "tomorrow 7am", "Friday", "Dec 1"]


def test_under_and_in_area_phrases_become_the_domain():
    for text in ("study notes Friday under Health", "study notes Friday in the Health area"):
        items, _ = parse_clauses(text + " and call mom tomorrow")
        assert items[0].domain == "health" and items[0].due_text == "Friday"


def test_merge_adds_clauses_the_model_missed_and_keeps_its_item():
    det, _ = parse_clauses(MSG_3A)
    model_first = IntakeItem("DBMS assignment", "coursework", "high", None, "Tuesday 5pm")
    merged = merge_missing([model_first], det)
    assert _titles(merged) == ["DBMS assignment", "gym", "ML report"]
    assert merged[0].priority == "high"


def test_merge_replaces_an_item_that_swallowed_the_other_clauses():
    det, _ = parse_clauses(MSG_3A)
    swallowed = IntakeItem("DBMS assignment gym ML report", "general", "medium", None, "")
    assert _titles(merge_missing([swallowed], det)) == ["DBMS assignment", "gym", "ML report"]


def _preview(message, items=None):
    stored = {}

    async def fake_store(conn, its, owner, conv):
        stored["items"] = its
        return {"id": 1, "action": "add_tasks", "count": len(its), "status": "pending"}

    with patch.object(task_intake, "_store_pending", fake_store):
        out = _run(task_intake.handle_intake_preview(
            message=message, conv_id="c1", owner_identity="o1", user_id=None, guest_id="g", persist=False,
            active_pool=_Pool(), start_time=0.0, items=items,
        ))
    return out, stored.get("items", [])


def test_router_single_item_is_merged_up_to_every_clause():
    first = {"title": "DBMS assignment", "domain": "coursework", "priority": "medium",
             "duration_minutes": None, "due_text": "Tuesday 5pm"}
    out, items = _preview(MSG_3A, [first])
    assert [i["title"] for i in items] == ["DBMS assignment", "gym", "ML report"]
    assert items[1]["due_at"] and items[2]["due_date"] and items[2]["due_at"] is None
    assert out["success"] and out["response"].startswith("I found 3 tasks")


def test_model_returning_only_the_first_task_still_yields_all_three():
    async def only_first(_message):
        return [IntakeItem("DBMS assignment", "coursework", "medium", None, "Tuesday 5pm")]

    with patch.object(task_intake_llm, "llm_extract_items", only_first):
        out, items = _preview(MSG_3A)
    assert [i["title"] for i in items] == ["DBMS assignment", "gym", "ML report"]
    assert out["data"]["pending_action"]["count"] == 3


def test_five_tasks_reach_the_card():
    _, items = _preview(MSG_5)
    assert len(items) == 5
    assert items[2]["domain"] == "health"


def test_unparsable_fragment_is_reported_not_dropped():
    out, items = _preview("Add gym tomorrow 7am and ???")
    assert [i["title"] for i in items] == ["gym"]
    assert 'I couldn\'t turn this into a task: "???"' in out["response"]


# ---- edits ------------------------------------------------------------------------------------------------

GYM = {"id": 7, "title": "Gym session", "domain": "general", "due_date": date(2026, 12, 7), "status": "open", "priority": "medium"}
LAB = {"id": 8, "title": "OS lab", "domain": "coursework", "due_date": date(2026, 12, 9), "status": "open", "priority": "medium"}


def _handle(message):
    created = []

    async def fake_create(conn, **kw):
        created.append(kw)
        return {"id": 99, "action": kw["action"], "status": "pending"}

    args = parse_task_action_intent(message)
    assert args is not None, message
    tasks = AsyncMock(return_value=[dict(GYM), dict(LAB)])
    with patch.object(chat_task_actions, "get_all_active_tasks_for_user", tasks), \
            patch.object(chat_task_actions, "create_chat_pending_action", fake_create), \
            patch("backend.memory.chat_pending.get_all_active_tasks_for_user", tasks), \
            patch("backend.memory.chat_pending.create_chat_pending_action", fake_create):
        out = _run(chat_task_actions.handle_chat_task_action(
            args, message, "c1", "owner", pool=_Pool(), persist=False, tz=TZ,
        ))
    return out, created


def test_make_that_gym_time_and_area_is_one_card_with_both_changes():
    out, created = _handle("make that gym 6:30am and put it in the Health area")
    assert len(created) == 1 and created[0]["action"] == "edit_last_task"
    assert created[0]["task_ids"] == [7]
    changes = created[0]["task_titles"][0]["changes"]
    assert changes["domain"] == "health"
    local = datetime.fromisoformat(changes["due_at"]).astimezone(ZoneInfo(TZ))
    assert (local.hour, local.minute, local.date()) == (6, 30, date(2026, 12, 7))  # keeps the task's own date
    assert out["data"]["pending_action"]["card_text"].count("area health") == 1 and "due" in out["response"]


def test_change_os_lab_deadline_creates_one_reschedule_card():
    out, created = _handle("change the OS lab deadline to Wednesday 11am")
    assert len(created) == 1 and created[0]["action"] == "reschedule_task" and created[0]["task_ids"] == [8]
    local = datetime.fromisoformat(created[0]["task_titles"][0]["due_at"]).astimezone(ZoneInfo(TZ))
    assert (local.weekday(), local.hour) == (2, 11)


def test_move_gym_to_monday_creates_one_reschedule_card():
    out, created = _handle("move gym to Monday")
    assert len(created) == 1 and created[0]["action"] == "reschedule_task" and created[0]["task_ids"] == [7]
    assert datetime.fromisoformat(created[0]["task_titles"][0]["due_date"]).weekday() == 0


def test_multi_field_edit_lists_priority_title_and_area():
    out, created = _handle("rename gym to Morning workout and set priority of gym to high and put it in the Health area")
    changes = created[0]["task_titles"][0]["changes"]
    assert (changes["title"], changes["priority"], changes["domain"]) == ("Morning workout", "high", "health")


def test_confirming_a_multi_edit_applies_every_field_in_one_update():
    calls = []

    async def fake_update(conn, task_id, owner_id=None, **fields):
        calls.append((task_id, fields))
        return {"id": task_id, **fields}

    changes = {"multi": True, "domain": "health", "priority": "high", "due_date": "2026-12-07",
               "due_at": "2026-12-07T01:00:00+00:00", "due_label": "Mon Dec 7, 2026 at 6:30 AM"}
    with patch.object(chat_followup_edit.structured, "update_task", fake_update), \
            patch.object(chat_followup_edit, "resolve_chat_pending_action", AsyncMock(return_value=True)):
        reply, data, ok = _run(chat_followup_edit.execute_pending_edit_last_task(
            AsyncMock(), {"id": 5, "task_ids": [7], "task_titles": [{"id": 7, "title": "Gym", "changes": changes}]},
            "owner", "confirm",
        ))
    assert ok and len(calls) == 1
    assert calls[0][0] == 7 and calls[0][1]["domain"] == "health" and calls[0][1]["priority"] == "high"
    assert calls[0][1]["due_date"] == date(2026, 12, 7) and calls[0][1]["due_at"].hour == 1


def test_retraction_takes_the_last_clause_and_creates_a_delete_card():
    message = "cancel that. Actually yes, delete the gym session"
    assert parse_task_action_intent(message) == {"action": "delete", "target": "gym session"}
    out, created = _handle(message)
    assert len(created) == 1 and created[0]["action"] == "delete_task" and created[0]["task_ids"] == [7]
    assert "delete task 'Gym session'" in out["response"]
    assert "Agent Planner" not in out["response"]


def test_plain_cancel_and_existing_followups_are_untouched():
    assert parse_task_action_intent("cancel that") is None
    assert parse_task_action_intent("make it 6pm instead") is None
    assert chat_followup_edit.parse_followup_edit("make it 6pm instead")["action"] == "edit_last_task"
    assert chat_followup_edit.parse_followup_edit("make that gym 6:30am and put it in the Health area") is None


# ---- request-id replay -----------------------------------------------------------------------------------

def _frame(kind, **extra):
    return f"data: {json.dumps({'type': kind, **extra})}\n\n"


def _guard(rid, stream):
    async def collect():
        return [f async for f in chat_idempotency.replay_guarded_turn("owner", "conv", rid, stream)]
    return collect()


def test_repeated_request_id_replays_first_response_and_saves_one_message():
    chat_idempotency._turn_done.clear()
    add_message = AsyncMock()
    runs = []

    def stream():
        async def gen():
            runs.append(1)
            yield ": ping\n\n"
            await add_message(role="user", content="move gym to Monday")
            yield _frame("token", value="Move 'gym' to Monday?")
            yield _frame("done", data={"pending_action": {"action": "reschedule_task"}})
        return gen()

    async def both():
        return await _guard("req-12345678", stream), await _guard("req-12345678", stream)

    first, second = _run(both())
    assert len(runs) == 1 and add_message.await_count == 1
    original = [f for f in first if not f.startswith(":")]
    assert second[:-1] == original[:-1]
    assert '"replayed": true' in second[-1] and "reschedule_task" in second[-1]  # same card, marked as a replay


def test_repeat_waits_for_the_first_request_still_in_flight():
    chat_idempotency._turn_done.clear()
    runs = []

    def stream():
        async def gen():
            runs.append(1)
            await asyncio.sleep(0.1)
            yield _frame("token", value="card")
            yield _frame("done", data={"pending_action": {"action": "reschedule_task"}})
        return gen()

    async def both():
        return await asyncio.gather(_guard("req-abcdefgh", stream), _guard("req-abcdefgh", stream))

    first, second = _run(both())
    assert len(runs) == 1 and first[:-1] == second[:-1] and "reschedule_task" in second[-1]


def test_in_flight_repeat_gets_a_retry_error_after_the_wait_bound():
    chat_idempotency._turn_done.clear()

    def stream():
        async def gen():
            await asyncio.sleep(0.3)
            yield _frame("done")
        return gen()

    async def both():
        with patch.object(chat_idempotency, "TURN_WAIT_SECONDS", 0.05):
            return await asyncio.gather(_guard("req-slowslow", stream), _guard("req-slowslow", stream))

    first, second = _run(both())
    assert '"done"' in first[-1]
    assert json.loads(second[-1][6:])["can_retry"] is True


def test_failed_first_attempt_is_not_cached_and_other_ids_run_separately():
    chat_idempotency._turn_done.clear()
    runs = []

    def failing():
        async def gen():
            runs.append("fail")
            yield _frame("error", detail="boom", can_retry=True)
        return gen()

    def ok():
        async def gen():
            runs.append("ok")
            yield _frame("done")
        return gen()

    async def seq():
        await _guard("req-failfail", failing)
        await _guard("req-failfail", ok)
        await _guard("req-failfail", ok)
        await _guard("req-other123", ok)

    _run(seq())
    assert runs == ["fail", "ok", "ok"]
