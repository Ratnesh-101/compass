"""Compass — Chat Follow-up Edit Service."""

from datetime import date, datetime, time, timezone
import json
import re
from typing import Any, Dict, Optional, Tuple

from backend.memory.chat_pending import create_chat_pending_action, resolve_chat_pending_action
from backend.memory.db import get_pool
from backend.memory import structured
from backend.router_helpers import _parse_time
from backend.services.chat_task_actions import _is_date_like, _shift_due_at_date, format_date_with_year, strip_id_suffix
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
    titled = parse_titled_edit(clean)
    if titled and titled["target"]:
        return None  # a named task or several fields belongs to the task-action parser, not "the last task"
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
    if changes.get("multi"):
        return await _apply_multi_edit(conn, task_id, title, changes, owner_identity)
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
    due_label = changes.get("due_label") or (due_d.isoformat() if due_d else "")
    if changes.get("due_at"):
        dt = datetime.fromisoformat(changes["due_at"])
        due_at = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    else:
        try:
            ex = await structured.get_task(conn, task_id)
        except Exception:
            ex = None
        due_at = _shift_due_at_date(ex, due_d) if (isinstance(ex, dict) and ex.get("due_at") and due_d) else None

    updated = await structured.update_task(
        conn, task_id, owner_id=owner_identity, due_date=due_d, due_at=due_at
    )
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


# ---------------------------------------------------------------------------
# Edits that name their task ("make that gym 6:30am and put it in the Health area",
# "change the OS lab deadline to Wednesday 11am") and "cancel that. Actually yes, delete X".
# One Confirm/Cancel card lists every change; nothing is written before Confirm.
# ---------------------------------------------------------------------------
_EDIT_VERBS = frozenset({"make", "change", "set", "update", "edit", "move", "put", "reschedule", "push", "postpone", "rename", "shift"})
_RETRACT_LEADS = ("cancel that", "scratch that", "never mind", "nevermind", "forget that", "ignore that", "no,", "no.", "actually", "wait", "on second thought")
_LEAD_FILLERS = frozenset({"cancel", "that", "no", "actually", "yes", "yeah", "ok", "okay", "sure", "wait", "never", "mind", "nevermind", "scratch", "forget", "ignore", "please", "on", "second", "thought"})
_PRONOUNS = frozenset({"it", "that", "this", "its"})
_NOISE = frozenset({"instead", "please", "now", "the", "a", "an", "to", "of", "for", "my", "its", "'s", "and", "also", "then", "back", "due", "date", "deadline", "time", "at", "on", "by", "priority", "title", "name", "task", "in", "into", "under", "as", "from"})
_AREA_SUFFIX_WORDS = frozenset({"area", "domain", "category", "project"})
_RANK_WORDS = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1, "third": 2, "3rd": 2, "3": 2}


def split_retraction(raw: str) -> Tuple[str, bool]:
    """('cancel that. Actually yes, delete X') -> ('delete X', True): the last clause is the intent."""
    if not raw.lower().startswith(_RETRACT_LEADS):
        return raw, False
    parts = [p.strip() for p in re.split(r"[.;!](?:\s|$)", raw) if p.strip()]
    tokens = (parts[-1] if parts else raw).split()
    while tokens and tokens[0].lower().strip(",.:;") in _LEAD_FILLERS:
        tokens.pop(0)
    return " ".join(tokens), True


def parse_titled_delete(raw: str) -> Optional[Dict[str, Any]]:
    from backend.router_helpers import is_chat_delete_intent

    is_del, clear_all, target = is_chat_delete_intent(raw)
    return {"action": "delete", "target": target} if is_del and not clear_all and target else None


def _split_time(tokens: list) -> Tuple[str, str]:
    """(date words, clock words) from date-ish tokens such as ['Wednesday', '11am'] or ['Dec', '5', '6', 'pm']."""
    from backend.services.task_intake_parse import _TIME_TOKEN, _norm_tok

    date_parts, clock = [], ""
    i = 0
    while i < len(tokens):
        t = _norm_tok(tokens[i])
        nxt = _norm_tok(tokens[i + 1]) if i + 1 < len(tokens) else ""
        if _TIME_TOKEN.match(t):
            clock, i = t, i + 1
        elif t.replace(":", "").isdigit() and nxt in ("am", "pm"):
            clock, i = t + nxt, i + 2
        else:
            date_parts.append(tokens[i].strip(","))
            i += 1
    return " ".join(date_parts), clock


def _scan_area(tokens: list) -> Tuple[list, Optional[str]]:
    """'in/into/to/under [the] X area' or '(X)' -> (tokens without it, X)."""
    from backend.services.task_intake_parse import _take_area

    for i, t in enumerate(tokens):
        if t.lower() in ("in", "into", "to", "under"):
            j = i + 2 if i + 1 < len(tokens) and tokens[i + 1].lower() == "the" else i + 1
            if j + 1 < len(tokens) and tokens[j].isalpha() and tokens[j + 1].lower() in _AREA_SUFFIX_WORDS:
                return tokens[:i] + tokens[j + 2:], tokens[j]
    return _take_area(tokens)


def _parse_edit_segment(tokens: list) -> Optional[Dict[str, Any]]:
    from backend.services.task_intake_parse import _PRIORITY_WORDS, _date_flags, _norm_tok

    rest = tokens[1:]
    low = [_norm_tok(t) for t in rest]
    changes: Dict[str, Any] = {}
    if tokens[0].lower() == "rename" and "to" in low:
        k = low.index("to")
        title = " ".join(rest[k + 1:]).strip("\"' ")
        rest, changes = rest[:k], ({"title": title} if title else {})
    rest, area = _scan_area(rest)
    if area:
        from backend.services.task_intake_parse import _area_slug

        changes["domain"] = _area_slug(area)
    low = [_norm_tok(t) for t in rest]
    if "priority" in low:
        prio = next((_PRIORITY_WORDS[w] for w in low if w in _PRIORITY_WORDS), None)
        if prio:
            changes["priority"] = prio
            rest = [t for t, w in zip(rest, low) if w not in _PRIORITY_WORDS]
    if "title" not in changes:
        flags = _date_flags(rest)
        due = [t for t, f in zip(rest, flags) if f]
        if due:
            first = flags.index(True)
            lead = [t for t in rest[max(first - 1, 0):first] if _norm_tok(t) in ("next", "this")]
            changes["due_text"] = " ".join(lead + due)
            rest = [t for i, t in enumerate(rest) if not flags[i] and not (lead and i == first - 1)]
    words = [t for t in rest if _norm_tok(t) not in _NOISE]
    pronoun = any(_norm_tok(t) in _PRONOUNS for t in rest) or (bool(words) and all(_norm_tok(w) in _PRONOUNS for w in words))
    words = [t for t in words if _norm_tok(t) not in _PRONOUNS]
    return {"changes": changes, "target": " ".join(words).strip("\"'") or None, "pronoun": pronoun}


def parse_titled_edit(raw: str) -> Optional[Dict[str, Any]]:
    """Edit of a named (or 'that'/'it') task: {'action':'edit','target','changes','pronoun'} or None."""
    tokens = raw.split()
    if len(tokens) < 3 or tokens[0].lower() not in _EDIT_VERBS:
        return None
    segments, cur = [], [tokens[0]]
    for k, t in enumerate(tokens[1:], 1):
        nxt = tokens[k + 1].lower() if k + 1 < len(tokens) else ""
        if t.lower() in ("and", ",") and nxt in _EDIT_VERBS:
            segments.append(cur)
            cur = []
        else:
            cur.append(t)
    segments.append(cur)
    target, pronoun, changes = None, False, {}
    for seg in segments:
        if seg[0].lower() not in _EDIT_VERBS:
            return None
        parsed = _parse_edit_segment(seg)
        if not parsed:
            return None
        changes.update(parsed["changes"])
        target = target or parsed["target"]
        pronoun = pronoun or parsed["pronoun"]
    if not changes or (target is None and "domain" not in changes):
        return None
    if target and (target.lower().split()[0] in ("a", "an", "reminder", "note") or all(w in _RANK_WORDS or w in ("one", "ones") for w in target.lower().split())):
        return None  # new reminders and "the second one" replies are not title edits
    return {"action": "edit", "target": target, "changes": changes, "pronoun": pronoun or target is None}


async def _resolve_titled_task(conn: Any, target: Optional[str], pronoun: bool, owner: str, include_demo: bool) -> Tuple[Optional[Dict[str, Any]], str]:
    """(task, problem). 'that'/'it' and an unmatched title with a pronoun mean the most recently created task."""
    from backend.memory.chat_pending import get_all_active_tasks_for_user
    from backend.services.chat_task_actions import match_open_task

    tasks = [t for t in await get_all_active_tasks_for_user(conn, owner, include_demo=include_demo)
             if t.get("status") not in ("done", "completed", "cancelled")]
    words = (target or "").lower().split()
    matches = match_open_task(target, tasks) if target else []
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        names = ", ".join(f"'{strip_id_suffix(t['title'])}'" for t in matches[:3])
        return None, f"Which one: {names}? Tell me the full task name."
    if pronoun or not target:
        last = await get_last_recent_task(conn, owner, within_minutes=1440, include_demo=include_demo)
        if last:
            return last, ""
    shown = ", ".join(f"'{strip_id_suffix(t['title'])}'" for t in tasks[:5])
    return None, f"I couldn't find an open task called '{target or 'that'}'." + (f" Your open tasks: {shown}." if shown else " You have no open tasks.")


async def build_titled_card(conn: Any, args: Dict[str, Any], owner: str, conv_id: str, tz: str, include_demo: bool = False) -> Tuple[str, Dict[str, Any]]:
    """Confirm card for a delete or a multi-field edit of a named task. Returns (reply text, data)."""
    from backend.memory.chat_pending import create_chat_pending_action

    task, problem = await _resolve_titled_task(conn, args.get("target"), bool(args.get("pronoun")), owner, include_demo)
    if not task:
        return problem, {"count": 0}
    title = strip_id_suffix(task.get("title") or "task")
    if args.get("action") == "delete":
        pending = await create_chat_pending_action(
            conn, action="delete_task", task_ids=[task["id"]], task_titles=[{"id": task["id"], "title": task["title"]}],
            count=1, owner_identity=owner, conversation_id=conv_id, expires_minutes=5,
        )
        return (f"Are you sure you want to delete task '{title}' (ID: {task['id']})? Please confirm to proceed or click Cancel.",
                {"pending_action": pending, "task": task})
    req = args["changes"]
    changes: Dict[str, Any] = {"multi": True}
    parts = []
    if req.get("title"):
        changes["title"] = req["title"]
        parts.append(f"rename to '{req['title']}'")
    if req.get("due_text"):
        date_text, clock = _split_time(req["due_text"].split())
        base = task.get("due_date")
        if date_text:
            due = resolve_due(f"{date_text} {clock}".strip(), tz)
        elif clock and (base or local_today(tz)):
            t24, _ = _parse_time(clock)
            hh, mm = (int(x) for x in t24.split(":")) if t24 else (18, 0)
            day = base or local_today(tz)
            due = ResolvedDue(due_date=day, due_at=combine_local(day, time(hh, mm), tz), label="", unparsed_text=None)
        else:
            due = resolve_due(req["due_text"], tz)
        if not due.due_date:
            return f"I couldn't read the date '{req['due_text']}'. What date and time should I use?", {"count": 0}
        label = format_date_with_year(due, tz)
        changes.update(due_date=due.due_date.isoformat(), due_at=due.due_at.isoformat() if due.due_at else None, due_label=label)
        parts.append(f"due {label}")
    if req.get("priority"):
        changes["priority"] = req["priority"]
        parts.append(f"priority {req['priority']}")
    if req.get("domain"):
        changes["domain"] = req["domain"]
        parts.append(f"area {req['domain']}")
    card_text = f"Update '{title}': " + "; ".join(parts) + "?"
    pending = await create_chat_pending_action(
        conn, action="edit_last_task", task_ids=[task["id"]],
        task_titles=[{"id": task["id"], "title": title, "changes": changes, "due_label": changes.get("due_label")}],
        count=1, owner_identity=owner, conversation_id=conv_id, expires_minutes=5,
    )
    pending["card_text"] = card_text
    return f"{card_text} Please confirm to proceed or click Cancel.", {"pending_action": pending, "task": task, "changes": changes}


async def _apply_multi_edit(conn: Any, task_id: Any, title: str, changes: Dict[str, Any], owner: str) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    fields: Dict[str, Any] = {k: changes[k] for k in ("title", "priority", "domain") if changes.get(k)}
    parts = [f"{k} {v}" for k, v in fields.items()]
    if changes.get("due_date"):
        fields["due_date"] = date.fromisoformat(changes["due_date"])
        if changes.get("due_at"):
            dt = datetime.fromisoformat(changes["due_at"])
            fields["due_at"] = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        else:
            try:
                ex = await structured.get_task(conn, task_id)
            except Exception:
                ex = None
            fields["due_at"] = _shift_due_at_date(ex, fields["due_date"]) if isinstance(ex, dict) and ex.get("due_at") else None
        parts.append(f"due {changes.get('due_label') or changes['due_date']}")
    updated = await structured.update_task(conn, task_id, owner_id=owner, **fields)
    if not updated:
        return ("I couldn't update it, nothing was changed.", None, False)
    return (f"Done: updated '{title}' ({'; '.join(parts)}).", {"updated_task": updated, "success": True}, True)
