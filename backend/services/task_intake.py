"""Preview-then-confirm creation of several tasks pasted in one chat message.

Nothing is written on the first message. The parsed items are stored on a single-use, owner-scoped,
expiring chat_pending_actions row ("add_tasks") and shown as a preview. Confirming creates every
item in one transaction; if any item fails, none are created.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from backend.memory import conversations, structured
from backend.memory.chat_pending import resolve_chat_pending_action
from backend.services.task_intake_parse import MAX_ITEMS, IntakeItem, ParsedIntake, parse_task_list
from backend.services.task_time import request_timezone, resolve_due

logger = logging.getLogger("compass.services.task_intake")

ACTION = "add_tasks"
PREVIEW_EXPIRY_MINUTES = 5
NOT_A_LIST_REPLY = "I couldn't find a list of tasks in that message. Paste one task per line and I'll show you a preview."


def _duration_label(minutes: Optional[int]) -> str:
    if not minutes:
        return ""
    return f"{minutes / 60:g}h" if minutes % 30 == 0 else f"{minutes}m"


def _preview_items(parsed: ParsedIntake, tz_name: str) -> list[dict]:
    """Resolve every item's due text in the user's zone; unparsed text is reported, never guessed."""
    out = []
    for item in parsed.items:
        due = resolve_due(item.due_text, tz_name)
        out.append({
            "title": item.title,
            "domain": item.domain,
            "priority": item.priority,
            "duration_minutes": item.duration_minutes,
            "due_date": due.due_date.isoformat() if due.due_date else None,
            "due_at": due.due_at.isoformat() if due.due_at else None,
            "due_label": due.label,
            "due_unparsed": due.unparsed_text,
        })
    return out


def _line(index: int, it: dict) -> str:
    due = it["due_label"]
    if it.get("due_unparsed"):
        due = f'no due date (could not read "{it["due_unparsed"]}")'
    parts = [it["domain"], it["priority"], _duration_label(it.get("duration_minutes")), due]
    return f"{index}. {it['title']} — " + " · ".join(p for p in parts if p)


def _preview_text(items: list[dict], parsed: ParsedIntake, tz_name: str) -> str:
    n = len(items)
    noun = "task" if n == 1 else "tasks"
    lines = [f"I found {n} {noun}. Nothing has been added yet:", ""]
    lines += [_line(i, it) for i, it in enumerate(items, 1)]
    notes = []
    if parsed.truncated:
        notes.append(
            f"You pasted {parsed.total_found} items; I can add at most {MAX_ITEMS} at once, "
            f"so the rest are not included. Send them in a second message."
        )
    if parsed.skipped:
        notes.append("Skipped (no usable task name): " + "; ".join(f'"{s}"' for s in parsed.skipped))
    notes.append(f"Times are in {tz_name}. Reply \"Confirm\" to add all {n}, or \"Cancel\".")
    return "\n".join(lines + [""] + notes)


async def _store_pending(conn: Any, items: list[dict], owner: str, conv_id: str) -> Dict[str, Any]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=PREVIEW_EXPIRY_MINUTES)
    await conn.execute(
        "UPDATE chat_pending_actions SET status = 'cancelled' "
        "WHERE owner_identity = $1 AND conversation_id = $2 AND status = 'pending'",
        owner, conv_id,
    )
    row = await conn.fetchrow(
        """
        INSERT INTO chat_pending_actions (action, task_ids, task_titles, count, owner_identity,
                                          conversation_id, status, created_at, expires_at)
        VALUES ($1, '{}'::integer[], $2::jsonb, $3, $4, $5, 'pending', now(), $6)
        RETURNING id, action, count, status, expires_at
        """,
        ACTION, json.dumps(items), len(items), owner, conv_id, expires_at,
    )
    return dict(row)


async def _persist(persist: bool, pool: Any, conv_id: str, user_id: Optional[str], guest_id: Optional[str],
                   message: str, reply: str, skill: str) -> str:
    if not (persist and pool):
        return conv_id
    try:
        async with pool.acquire() as conn:
            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
            await conversations.add_message(conn, real_cid, role="user", content=message)
            await conversations.add_message(conn, real_cid, role="assistant", content=reply, skill_called=skill, verifiable=False)
            return real_cid
    except Exception as e:
        logger.debug("Could not persist intake message history: %s", e)
        return conv_id


async def handle_intake_preview(*, message: str, conv_id: str, owner_identity: str, user_id: Optional[str],
                                guest_id: Optional[str], persist: bool, active_pool: Any, start_time: float,
                                items: Optional[list] = None) -> Dict[str, Any]:
    """Orchestrator entry: parse the pasted list and store a pending preview (no task is written)."""
    from backend.memory.db import get_pool

    tz_name = request_timezone.get() or "UTC"
    parsed = (
        ParsedIntake(tuple(IntakeItem(**d) for d in items), len(items), ()) if items else parse_task_list(message)
    )
    success, data, reply = False, None, NOT_A_LIST_REPLY
    pool = active_pool or await get_pool()
    if parsed and parsed.items and pool:
        items = _preview_items(parsed, tz_name)
        async with pool.acquire() as conn:
            pending = await _store_pending(conn, items, owner_identity, conv_id)
        reply = _preview_text(items, parsed, tz_name)
        pending.update({"items": items, "timezone": tz_name})
        success, data = True, {"pending_action": pending}
    elif parsed:
        reply = "I can't prepare the preview right now because the database is unavailable. Nothing was added."
    conv_id = await _persist(persist, pool, conv_id, user_id, guest_id, message, reply, "add_tasks_preview")
    return {
        "conversation_id": conv_id, "response": reply, "message": reply, "skill_used": "add_tasks_preview",
        "success": success, "data": data, "verifiable": False,
        "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
    }


def clarification_result(conv_id: str, start_time: float, message: str) -> Dict[str, Any]:
    """Reply for a task request that is a question or has no usable title: nothing is written."""
    from backend.services.task_intent import CAPABILITY_REPLY, TITLE_CLARIFICATION, is_capability_question

    reply = CAPABILITY_REPLY if is_capability_question(message) else TITLE_CLARIFICATION
    return {
        "conversation_id": conv_id, "response": reply, "message": reply, "skill_used": "add_task",
        "success": False, "data": {"error": "needs_task_details"}, "verifiable": False,
        "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
    }


def implicit_task_result(conv_id: str, start_time: float, title: str) -> Dict[str, Any]:
    """Reply when the model inferred a task from chatter: ask first, write nothing."""
    reply = (
        f"I haven't added anything. Do you want me to add \"{title}\" as a task? "
        f"If so, tell me when it's due, for example: \"add task {title} tomorrow 5pm\"."
    )
    return {
        "conversation_id": conv_id, "response": reply, "message": reply, "skill_used": "add_task",
        "success": False, "data": {"error": "needs_confirmation"}, "verifiable": False,
        "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
    }


def _stored_items(action: Dict[str, Any]) -> list[dict]:
    raw = action.get("task_titles")
    if isinstance(raw, str):
        raw = json.loads(raw)
    return raw if isinstance(raw, list) else []


async def _create_all(conn: Any, items: list[dict], owner: str, conv_id: str) -> list[dict]:
    created = []
    for it in items:
        due_date = datetime.fromisoformat(it["due_date"]).date() if it.get("due_date") else None
        due_at = datetime.fromisoformat(it["due_at"]) if it.get("due_at") else None
        task = await structured.create_task(
            conn, domain=it["domain"], title=it["title"], due_date=due_date, due_at=due_at,
            priority=it["priority"], duration_minutes=it.get("duration_minutes"), user_id=owner,
        )
        await conn.execute(
            """
            INSERT INTO agent_audit_log (run_id, tool, args, affected_table, affected_id, new_state,
                                         approved_by, status, is_reverted)
            VALUES ($1, 'add_task', $2::jsonb, 'tasks', $3, $4::jsonb, $5, 'executed', FALSE)
            """,
            conv_id, json.dumps({"title": it["title"], "user_id": owner, "via": ACTION}),
            int(task["id"]), json.dumps(task, default=str), owner,
        )
        created.append({**task, "due_label": it.get("due_label", "no due date")})
    return created


async def confirm_add_tasks(conn: Any, action: Dict[str, Any], owner_identity: str, conv_id: str) -> tuple[str, Optional[dict], bool]:
    """Claim the pending action and create every item atomically. Returns (reply, data, success)."""
    items = _stored_items(action)
    try:
        async with conn.transaction():
            if not await resolve_chat_pending_action(conn, action["id"], "executed"):
                return "That action was already handled, so nothing new was added.", None, False
            created = await _create_all(conn, items, owner_identity, conv_id)
    except Exception as e:
        logger.error("add_tasks confirm failed; no tasks were created: %s", e, exc_info=True)
        return (
            f"No tasks were created: saving the list failed ({type(e).__name__}). "
            "Nothing was added, and you can send \"Confirm\" again to retry.",
            None, False,
        )
    lines = [f"Added {len(created)} {'task' if len(created) == 1 else 'tasks'}:", ""]
    lines += [f"{i}. {t['title']} — {t['due_label']}" for i, t in enumerate(created, 1)]
    return "\n".join(lines), {"created_tasks": created, "created_count": len(created)}, True
