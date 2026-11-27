"""Compass — Chat Follow-up Edit Service."""

from datetime import date, datetime, time, timezone
import json
import re
from typing import Any, Dict, Optional, Tuple

from backend.memory.chat_pending import create_chat_pending_action, resolve_chat_pending_action
from backend.memory.db import get_pool
from backend.memory import structured
from backend.router_helpers import _parse_time
from backend.services.chat_task_actions import _is_date_like, format_date_with_year, strip_id_suffix
from backend.services.task_time import combine_local, local_today, request_timezone, resolve_due, ResolvedDue

PRIORITY_MAP = {
    "urgent": "urgent", "critical": "urgent", "p0": "urgent", "asap": "urgent",
    "high": "high", "p1": "high", "important": "high",
    "medium": "medium", "normal": "medium", "p2": "medium", "moderate": "medium",
    "low": "low", "p3": "low", "minor": "low",
}

PATTERNS = [
    re.compile(r"^rename\s+(?:it|that|this)\s+to\s+(?P<title>.+)$", re.IGNORECASE),
    re.compile(r"^(?:change|update)\s+(?:its|that's)\s+(?:due\s+date|deadline)\s+to\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:change|update)\s+(?:its|that's)\s+(?:due\s+date|deadline)\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:change|update)\s+(?:its|that's)\s+to\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:change|update)\s+(?:its|that's)\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^push\s+(?:it|that|this)\s+back\s+(?:to\s+)?(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:make|set)\s+(?:it|that|this)\s+due\s+(?:at|on|to)\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:make|set)\s+(?:it|that|this)\s+due\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:change|update|set)\s+the\s+(?:due\s+date|deadline)\s+(?:of|for)\s+(?:it|that|this)\s+(?:to|for)\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:make|change|move|push|set|postpone|reschedule|update)\s+(?:it|that|this)\s+(?:to|at|for|until|on)\s+(?P<val>.+)$", re.IGNORECASE),
    re.compile(r"^(?:make|set)\s+(?:it|that|this)\s+(?P<val>.+)$", re.IGNORECASE),
]


def parse_priority(val: str) -> Optional[str]:
    tokens = re.findall(r"\b\w+\b", val.lower())
    return next((PRIORITY_MAP[tok] for tok in tokens if tok in PRIORITY_MAP), None)


def extract_date_and_time(val: str) -> Tuple[Optional[str], Optional[str]]:
    val_clean = val.strip()
    t24, _ = _parse_time(val_clean)
    due_time, due_date = None, None
    if t24:
        m = re.search(r"\b(?:\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))\b", val_clean, re.IGNORECASE)
        if m:
            due_time = m.group(0).strip()
            rem = re.sub(r"\b(?:at|by|on|due|for)\b", " ", val_clean[:m.start()] + " " + val_clean[m.end():], flags=re.IGNORECASE)
            rem = re.sub(r"\s+", " ", rem).strip()
            if rem and _is_date_like(rem):
                due_date = rem
        else:
            due_time = val_clean
    elif _is_date_like(val_clean):
        due_date = val_clean
    return due_date, due_time


def parse_followup_edit(message: str) -> Optional[Dict[str, Any]]:
    """Pure parser: detect follow-up edits whose subject is a pronoun for the last task."""
    if not message or not isinstance(message, str):
        return None
    raw = " ".join(message.replace("’", "'").replace("‘", "'").split())[:300]
    if not raw or raw.endswith("?"):
        return None
    for lead in ("please ", "pls ", "can you ", "could you ", "would you "):
        if raw.lower().startswith(lead):
            raw = raw[len(lead):].strip()
            break
    clean = raw
    for tail in (" instead", " please", " for me"):
        if clean.lower().endswith(tail):
            clean = clean[: -len(tail)].strip()
    for pat in PATTERNS:
        m = pat.match(clean)
        if not m:
            continue
        gd = m.groupdict()
        if "title" in gd:
            t = gd["title"].strip().strip("\"'")
            return {"action": "edit_last_task", "title": t} if t else None
        val = gd.get("val", "").strip()
        prio = parse_priority(val)
        if prio:
            return {"action": "edit_last_task", "priority": prio}
        d, t = extract_date_and_time(val)
        if d or t:
            res: Dict[str, Any] = {"action": "edit_last_task", "due_text": val}
            if d:
                res["due_date"] = d
            if t:
                res["due_time"] = t
            return res
        return None
    return None


async def get_last_recent_task(
    conn: Any, owner_identity: str, within_minutes: int = 60, include_demo: bool = False,
) -> Optional[Dict[str, Any]]:
    tasks = await structured.list_tasks(conn, user_id=owner_identity, include_demo=include_demo)
    open_tasks = [t for t in tasks if t.get("status") not in ("done", "completed", "cancelled") and not t.get("deleted_at")]
    now = datetime.now(timezone.utc)
    recent = []
    for t in open_tasks:
        cat = t.get("created_at")
        if cat is not None:
            if cat.tzinfo is None:
                cat = cat.replace(tzinfo=timezone.utc)
            if (now - cat).total_seconds() <= (within_minutes * 60):
                recent.append(t)
    if not recent:
        return None
    recent.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return recent[0]


async def handle_followup_edit(
    args: Dict[str, Any], message: str, conv_id: str, owner_identity: str, pool: Any,
    tz: Optional[str] = None, include_demo: bool = False,
) -> Dict[str, Any]:
    effective_tz = tz or request_timezone.get() or "UTC"
    async with pool.acquire() as conn:
        task = await get_last_recent_task(conn, owner_identity, within_minutes=60, include_demo=include_demo)
        if not task:
            resp_msg = "I don't see a task you just added; tell me which task to change."
            return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg,
                    "skill_used": "edit_last_task", "success": False, "data": None, "verifiable": False}
        clean_title = strip_id_suffix(task.get("title") or "task")
        changes: Dict[str, Any] = {}
        if "title" in args:
            changes["title"] = args["title"]
            card_text = f"Rename '{clean_title}' to '{args['title']}'?"
            due_label = args["title"]
        elif "priority" in args:
            changes["priority"] = args["priority"]
            card_text = f"Change priority of '{clean_title}' to {args['priority']}?"
            due_label = args["priority"]
        else:
            due_text, due_d, due_t = args.get("due_text") or "", args.get("due_date"), args.get("due_time")
            if due_t and not due_d:
                orig_d = task.get("due_date") or local_today(effective_tz)
                t24, _ = _parse_time(due_t)
                hh, mm = (int(x) for x in t24.split(":")) if t24 else (18, 0)
                due_obj = ResolvedDue(due_date=orig_d, due_at=combine_local(orig_d, time(hh, mm), effective_tz), label="", unparsed_text=None)
            else:
                due_obj = resolve_due(due_text, effective_tz)
                if not due_obj.due_date:
                    due_obj = resolve_due(f"{due_d or ''} {due_t or ''}".strip(), effective_tz)
            due_label = format_date_with_year(due_obj, effective_tz)
            changes["due_date"] = due_obj.due_date.isoformat() if due_obj.due_date else None
            changes["due_at"] = due_obj.due_at.isoformat() if due_obj.due_at else None
            changes["due_label"] = due_label
            card_text = f"Change due date of '{clean_title}' to {due_label}?"

        pending = await create_chat_pending_action(
            conn, action="edit_last_task", task_ids=[task["id"]],
            task_titles=[{"id": task["id"], "title": clean_title, "changes": changes,
                          "due_date": changes.get("due_date"), "due_at": changes.get("due_at"),
                          "due_label": due_label, "priority": changes.get("priority"), "new_title": changes.get("title")}],
            count=1, owner_identity=owner_identity, conversation_id=conv_id, expires_minutes=5,
        )
        pending["card_text"] = card_text
        resp_msg = f"{card_text} Please confirm to proceed or click Cancel."
        return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg,
                "skill_used": "edit_last_task", "success": True, "data": {"pending_action": pending, "task": task}, "verifiable": False}


async def execute_pending_edit_last_task(
    conn: Any, active_action: Dict[str, Any], owner_identity: str, message: str,
) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    reply = (message or "").lower().strip().rstrip(".!?")
    if reply in ("cancel", "no", "abort"):
        await resolve_chat_pending_action(conn, active_action["id"], "cancelled")
        return ("Action cancelled.", None, False)
    task_ids = active_action.get("task_ids") or []
    if isinstance(task_ids, str):
        try:
            task_ids = json.loads(task_ids)
        except Exception:
            task_ids = []
    task_titles = active_action.get("task_titles") or []
    if isinstance(task_titles, str):
        try:
            task_titles = json.loads(task_titles)
        except Exception:
            task_titles = []
    if not task_ids:
        return ("No tasks were modified.", None, False)
    claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
    if not claimed:
        return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)
    meta = task_titles[0] if task_titles else {}
    task_id = task_ids[0]
    title = strip_id_suffix(meta.get("title") or "task")
    changes = meta.get("changes") or {}
    if "title" in changes:
        new_title = changes["title"]
        updated = await structured.update_task(conn, task_id, owner_id=owner_identity, title=new_title)
        if updated:
            return (f"Done: renamed '{title}' to '{new_title}'.", {"updated_task": updated, "success": True}, True)
        return ("I couldn't update it, nothing was changed.", None, False)
    if "priority" in changes:
        new_prio = changes["priority"]
        updated = await structured.update_task(conn, task_id, owner_id=owner_identity, priority=new_prio)
        if updated:
            return (f"Done: updated priority of '{title}' to {new_prio}.", {"updated_task": updated, "success": True}, True)
        return ("I couldn't update it, nothing was changed.", None, False)
    due_d = date.fromisoformat(changes["due_date"]) if changes.get("due_date") else None
    due_at = datetime.fromisoformat(changes["due_at"]) if changes.get("due_at") else None
    due_label = changes.get("due_label") or (due_d.isoformat() if due_d else "")
    updated = await structured.update_task(conn, task_id, owner_id=owner_identity, due_date=due_d)
    if updated and due_at is not None:
        await conn.execute("UPDATE tasks SET due_at = $1 WHERE id = $2 AND lower(user_id) = lower($3)", due_at, task_id, owner_identity)
    if updated:
        return (f"Done: moved '{title}' to {due_label}.", {"rescheduled_task": updated, "success": True}, True)
    return ("I couldn't update it, nothing was changed.", None, False)


async def handle_chat_followup_edit_stream(
    message: str, conv_id: str, user_id: Optional[str] = None, guest_id: Optional[str] = None,
    pool: Any = None, tz: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    args = parse_followup_edit(message)
    if args is None:
        return None
    active_pool = pool or await get_pool()
    if not active_pool:
        resp = "I can't update tasks right now because the database is unavailable."
        return {"conversation_id": conv_id, "response": resp, "message": resp, "skill_used": "edit_last_task", "success": False, "data": None, "verifiable": False}
    return await handle_followup_edit(
        args=args, message=message, conv_id=conv_id, owner_identity=user_id or guest_id or "default_user",
        pool=active_pool, tz=tz,
    )
