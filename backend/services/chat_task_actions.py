"""
Compass — Chat Task Actions Service.

Provides deterministic intent detection and fuzzy open task matching for
chat-based task completion and rescheduling. Follows the exact pending-action
confirmation safety model as chat delete (no mutation until explicit user confirm,
owner-scoped, guest-safe).
"""

from datetime import date, datetime, timezone
import difflib
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from backend.memory.chat_pending import (
    create_chat_pending_action,
    get_all_active_tasks_for_user,
    resolve_chat_pending_action,
)
from backend.memory.db import get_pool
from backend.memory import structured, conversations
from backend.services.task_time import (
    format_clock,
    pick_timezone,
    request_timezone,
    resolve_due,
)
from backend.router_helpers import is_chat_delete_intent, ORDINAL_REPLIES

logger = logging.getLogger("compass.services.chat_task_actions")

STOP_WORDS = frozenset({"the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "at", "by", "with", "is", "it", "my", "this", "that"})
QUESTION_STARTERS = ("what ", "which ", "why ", "how ", "when ", "where ", "who ", "should i ", "can you ", "could you ", "would you ", "will you ", "is it ", "are there ")
POSITIONAL_OR_PRONOUN_WORDS = frozenset({
    "it", "this", "that", "these", "those", "them", "one", "ones",
    "first", "second", "third", "last", "next", "previous", "other", "another",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "1st", "2nd", "3rd", "4th", "5th",
    "all", "everything", "task", "tasks", "thing", "things", "the",
})

PATTERNS_COMPLETE = [
    re.compile(r"^mark\s+(?P<target>.+?)\s+as\s+(?:done|complete|completed|finished)$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+is\s+(?:done|completed|finished)$", re.IGNORECASE),
    re.compile(
        r"^(?:i\s*(?:'ve(?:\s+just)?|'m|have(?:\s+just)?|am|just)?\s*(?:finished|completed)|just\s+(?:finished|completed)|finished|completed)\s+(?:with\s+)?(?P<target>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:i\s*(?:'m|am)\s+done|i\s*(?:'ve(?:\s+just)?|have(?:\s+just)?|just)?\s*done|done)\s+(?:with\s+)?(?P<target>.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"^complete\s+(?P<target>.+)$", re.IGNORECASE),
    re.compile(r"^tick\s+off\s+(?P<target>.+)$", re.IGNORECASE),
    re.compile(r"^check\s+off\s+(?P<target>.+)$", re.IGNORECASE),
]

PATTERNS_RESCHEDULE = [
    re.compile(r"^change(?:\s+the)?\s+(?:due\s+date|deadline)\s+(?:of|for)\s+(?P<target>.+?)\s+to\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^change\s+(?P<target>.+?)(?:'s|s')\s+(?:due\s+date|deadline)\s+to\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^move\s+(?P<target>.+?)\s+to\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^push(?:\s+back)?\s+(?P<target>.+?)\s+to\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^postpone\s+(?P<target>.+?)\s+(?:to|until)\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^reschedule\s+(?P<target>.+?)\s+(?:to|for)\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^set\s+(?P<target>.+?)\s+due(?:\s+on|\s+to|\s+date\s+to|\s+for)?\s+(?P<due>.+)$", re.IGNORECASE),
    re.compile(r"^make\s+(?P<target>.+?)\s+due(?:\s+on|\s+to)?\s+(?P<due>.+)$", re.IGNORECASE),
]

_ORDINAL_INDEX = {
    "1": 0, "first": 0, "first one": 0, "the first one": 0, "1st": 0,
    "2": 1, "second": 1, "second one": 1, "the second one": 1, "2nd": 1,
    "3": 2, "third": 2, "third one": 2, "the third one": 2, "3rd": 2,
    "4": 3, "fourth": 3, "fourth one": 3, "the fourth one": 3, "4th": 3,
    "5": 4, "fifth": 4, "fifth one": 4, "the fifth one": 4, "5th": 4,
}


def _is_positional_or_pronoun_target(target: str) -> bool:
    """Reject empty targets or those consisting solely of positional/pronoun/ordinal words."""
    if not target or not target.strip():
        return True
    words = re.findall(r"\w+", target.lower())
    return not words or all(w in POSITIONAL_OR_PRONOUN_WORDS for w in words)


def _is_date_like(phrase: str) -> bool:
    """Check if phrase resembles a date, time, day, or calendar interval."""
    if not phrase or not phrase.strip():
        return False
    p = phrase.lower().strip().rstrip(".!")
    try:
        r = resolve_due(p, "UTC")
        if r and (r.due_date is not None or r.due_at is not None):
            return True
    except Exception:
        pass
    if any(term in p for term in ("end of day", "eod", "next week", "next month", "noon", "midnight")):
        return True
    date_keywords = (
        "today", "tomorrow", "tonight", "yesterday", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
        "january", "february", "march", "april", "june", "july", "august", "september",
        "october", "november", "december",
    )
    tokens = set(re.findall(r"\w+", p))
    if any(k in tokens for k in date_keywords):
        return True
    return bool(re.search(r"\b202[4-9]\b|\b203[0-9]\b|\b\d{1,2}(?:st|nd|rd|th)?\b|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", p))


def _clean_target(raw: str) -> str:
    """Strip wrapping quotes and outer filler words ('the', 'task', 'assignment', 'with')."""
    target = raw.strip()
    quotes = ('"', "'", "\u201c", "\u201d", "\u2018", "\u2019")
    if len(target) >= 2 and target[0] in quotes and target[-1] in quotes:
        target = target[1:-1].strip()

    while True:
        stripped = False
        t_lower = target.lower()
        for prefix in ("the task ", "the assignment ", "task ", "the ", "with "):
            if t_lower.startswith(prefix):
                target = target[len(prefix):].strip()
                stripped = True
                break
        if not stripped:
            break

    if len(target) >= 2 and target[0] in quotes and target[-1] in quotes:
        target = target[1:-1].strip()
        t_lower = target.lower()
    else:
        t_lower = target.lower()

    if t_lower.endswith(" task"):
        target = target[:-5].strip()

    return target


def parse_task_action_intent(message: str) -> Optional[dict]:
    """Detect complete or reschedule intents.

    Returns dict with keys: action ('complete' | 'reschedule'), target (str), new_due (str | None).
    Returns None for non-intents, questions, delete-intent collisions, positional/pronoun targets,
    number/ordinal replies, delete verbs, task-creation statements, or vague non-task talk.
    """
    if not message or not isinstance(message, str):
        return None
    raw = message.replace("\u2019", "'").replace("\u2018", "'").strip()
    if not raw or raw.endswith("?"):
        return None

    low = raw.lower()
    if any(low.startswith(q) for q in QUESTION_STARTERS):
        return None

    # Number/ordinal replies or delete verbs
    raw_words = re.findall(r"\w+", low)
    if not raw_words or all(w in POSITIONAL_OR_PRONOUN_WORDS for w in raw_words):
        return None
    if low in _ORDINAL_INDEX or low in ORDINAL_REPLIES or low.isdigit():
        return None
    if re.match(r"^(?:delete|remove|drop|clear)\b", low):
        return None

    # Do not collide with chat delete intent
    try:
        is_del, _, _ = is_chat_delete_intent(message)
        if is_del:
            return None
    except Exception:
        pass

    # Strip polite prefixes
    for lead in ("please ", "pls ", "go ahead and "):
        if low.startswith(lead):
            raw = raw[len(lead):].strip()
            low = raw.lower()
            break

    # Reject ordinary task-creation sentences (remind, add, create, schedule, new task, set a reminder)
    if re.match(r"^(?:remind|add|create|schedule|new\s+task|set\s+a\s+reminder|set\s+reminder)\b", low):
        return None

    # Strip trailing polite tags
    for tail in (" please", " for me"):
        if low.endswith(tail):
            raw = raw[:-len(tail)].strip()
            low = raw.lower()
            break

    # 1. Complete patterns
    for pat in PATTERNS_COMPLETE:
        m = pat.match(raw)
        if m:
            tgt = _clean_target(m.group("target"))
            if tgt and not _is_positional_or_pronoun_target(tgt):
                return {"action": "complete", "target": tgt, "new_due": None}

    # 2. Reschedule patterns
    for pat in PATTERNS_RESCHEDULE:
        m = pat.match(raw)
        if m:
            tgt = _clean_target(m.group("target"))
            due = m.group("due").strip().rstrip(".!")
            if tgt and not _is_positional_or_pronoun_target(tgt) and due and _is_date_like(due):
                return {"action": "reschedule", "target": tgt, "new_due": due}

    return None


async def check_chat_task_action_intent(
    message: str,
    pre_routed_skill: Optional[str],
    skill_name: Optional[str],
    pool: Any,
    owner_identity: str,
    conv_id: str,
) -> Optional[dict]:
    """Check task action intent with caller pre-route and pending-action safety guards."""
    if pre_routed_skill is not None or skill_name in ("pending_action_confirm", "pending_action_cancel"):
        return None
    chk_pool = pool
    if chk_pool is None:
        try:
            chk_pool = await get_pool()
        except Exception:
            chk_pool = None
    if chk_pool:
        try:
            async with chk_pool.acquire() as conn:
                from backend.memory.chat_pending import get_active_chat_pending_action
                if await get_active_chat_pending_action(conn, owner_identity, conv_id):
                    return None
        except Exception:
            pass
    return parse_task_action_intent(message)


def compute_match_score(target: str, title: str) -> float:
    """Calculate match score between target query and open task title."""
    t_norm, title_norm = target.lower().strip(), title.lower().strip()
    if not t_norm or not title_norm:
        return 0.0
    if t_norm == title_norm:
        return 1.0
    score = 0.85 if (t_norm in title_norm or title_norm in t_norm) else 0.0
    t_toks = {w for w in re.findall(r"\w+", t_norm) if w not in STOP_WORDS}
    title_toks = {w for w in re.findall(r"\w+", title_norm) if w not in STOP_WORDS}
    if t_toks and title_toks:
        overlap = len(t_toks & title_toks) / len(t_toks)
        jaccard = len(t_toks & title_toks) / len(t_toks | title_toks)
        score = max(score, overlap * 0.7 + jaccard * 0.3)
    seq_ratio = difflib.SequenceMatcher(None, t_norm, title_norm).ratio()
    if seq_ratio >= 0.72:
        score = max(score, seq_ratio)
    return round(score, 4)


def match_open_task(target: str, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank the caller's OPEN tasks by fuzzy title match.

    Filters to open tasks (not done/completed/cancelled, not deleted).
    Returns best candidates (max 5) with tie rule:
    If top score is unique and >= 0.6 return one, else return the tied candidates.
    """
    open_tasks = [
        t for t in tasks
        if t.get("status") not in ("done", "completed", "cancelled")
        and not t.get("deleted_at")
    ]
    if not open_tasks or not target:
        return []

    scored = []
    for t in open_tasks:
        s = compute_match_score(target, t.get("title", ""))
        if s >= 0.6:
            scored.append((s, t))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]

    # Find candidates tied with top score (within 1e-4)
    tied = [t for s, t in scored if abs(s - top_score) < 1e-4]

    if len(tied) == 1:
        return [tied[0]]
    return tied[:5]


def format_date_with_year(due: Any, tz_name: str) -> str:
    """Format resolved due date WITH the year, and clock time if present."""
    if not due or not due.due_date:
        return ""
    day = due.due_date
    label = f"{day.strftime('%a %b')} {day.day}, {day.year}"
    if due.due_at:
        valid_tz = pick_timezone(tz_name, None)
        local = due.due_at.astimezone(ZoneInfo(valid_tz))
        label = f"{label} at {format_clock(local.timetz())}"
    return label


def _select_candidate(message: str, task_ids: list, task_titles: Optional[list] = None) -> Optional[int]:
    """Pick one candidate from a numbered or named reply; None when unclear."""
    reply = (message or "").lower().strip().rstrip(".!?")
    idx = _ORDINAL_INDEX.get(reply)
    if idx is not None and idx < len(task_ids):
        return task_ids[idx]
    if reply.isdigit() and int(reply) in task_ids:
        return int(reply)
    if task_titles:
        for t in task_titles:
            t_title = str(t.get("title", "")).lower().strip()
            if t_title and (reply == t_title or reply in t_title or t_title in reply):
                return t.get("id")
    return None


def _disambiguation_prompt(count: int) -> str:
    """Clarification prompt tailored to candidate count."""
    if count == 1:
        return "Reply with 1, or 'Cancel'."
    if count == 2:
        return "Which one? Reply with 1 or 2, or 'Cancel'."
    return f"Which one? Reply with 1, 2 or {count}, or 'Cancel'."


async def handle_chat_task_action(
    args: Dict[str, Any],
    message: str,
    conv_id: str,
    owner_identity: str,
    pool: Any = None,
    persist: bool = True,
    start_time: Optional[float] = None,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    include_demo: bool = False,
    tz: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute complete/reschedule intent by finding tasks and setting pending action."""
    start = start_time or time.perf_counter()
    action = args.get("action", "complete")
    target = args.get("target", "")
    new_due = args.get("new_due")

    active_pool = pool or await get_pool()
    if not active_pool:
        resp_msg = "I can't update tasks right now because the database is unavailable."
        return {
            "conversation_id": conv_id,
            "response": resp_msg,
            "message": resp_msg,
            "skill_used": "chat_task_action",
            "success": False,
            "data": None,
            "verifiable": False,
            "routing_latency_ms": int((time.perf_counter() - start) * 1000),
        }

    effective_tz = tz or request_timezone.get() or "UTC"
    due_label = ""
    due_obj = None

    if action == "reschedule":
        if not new_due:
            resp_msg = "What date should I use?"
            return {
                "conversation_id": conv_id,
                "response": resp_msg,
                "message": resp_msg,
                "skill_used": "chat_task_action",
                "success": True,
                "data": None,
                "verifiable": False,
                "routing_latency_ms": int((time.perf_counter() - start) * 1000),
            }
        due_obj = resolve_due(new_due, effective_tz)
        if not due_obj.due_date:
            resp_msg = "What date should I use?"
            return {
                "conversation_id": conv_id,
                "response": resp_msg,
                "message": resp_msg,
                "skill_used": "chat_task_action",
                "success": True,
                "data": None,
                "verifiable": False,
                "routing_latency_ms": int((time.perf_counter() - start) * 1000),
            }
        due_label = format_date_with_year(due_obj, effective_tz)

    async with active_pool.acquire() as conn:
        all_tasks = await get_all_active_tasks_for_user(conn, owner_identity, include_demo=include_demo)
        open_tasks = [
            t for t in all_tasks
            if t.get("status") not in ("done", "completed", "cancelled")
            and not t.get("deleted_at")
        ]
        matches = match_open_task(target, open_tasks)

        if not matches:
            if open_tasks:
                titles_str = ", ".join(f"'{t['title']}'" for t in open_tasks[:8])
                resp_msg = f"I couldn't find an open task matching '{target}'. Your open tasks: {titles_str}."
            else:
                resp_msg = f"I couldn't find an open task matching '{target}'. You have no open tasks."
            ret_data = {"count": 0, "open_tasks": open_tasks[:8]}

        elif len(matches) == 1:
            target_task = matches[0]
            if action == "complete":
                pending = await create_chat_pending_action(
                    conn,
                    action="complete_task",
                    task_ids=[target_task["id"]],
                    task_titles=[{"id": target_task["id"], "title": target_task["title"]}],
                    count=1,
                    owner_identity=owner_identity,
                    conversation_id=conv_id,
                    expires_minutes=5,
                )
                resp_msg = f"Mark '{target_task['title']}' as done? Please confirm to proceed or click Cancel."
                pending["card_text"] = f"Mark '{target_task['title']}' as done?"
                ret_data = {"pending_action": pending, "task": target_task}
            else:
                due_date_iso = due_obj.due_date.isoformat() if due_obj and due_obj.due_date else None
                due_at_iso = due_obj.due_at.isoformat() if due_obj and due_obj.due_at else None
                pending = await create_chat_pending_action(
                    conn,
                    action="reschedule_task",
                    task_ids=[target_task["id"]],
                    task_titles=[{
                        "id": target_task["id"],
                        "title": target_task["title"],
                        "due_date": due_date_iso,
                        "due_at": due_at_iso,
                        "due_label": due_label,
                    }],
                    count=1,
                    owner_identity=owner_identity,
                    conversation_id=conv_id,
                    expires_minutes=5,
                )
                resp_msg = f"Move '{target_task['title']}' to {due_label}? Please confirm to proceed or click Cancel."
                pending["card_text"] = f"Move '{target_task['title']}' to {due_label}?"
                ret_data = {"pending_action": pending, "task": target_task}

        else:
            candidates = matches[:3]
            if action == "complete":
                pending = await create_chat_pending_action(
                    conn,
                    action="complete_task_disambiguation",
                    task_ids=[t["id"] for t in candidates],
                    task_titles=[{"id": t["id"], "title": t["title"]} for t in candidates],
                    count=len(candidates),
                    owner_identity=owner_identity,
                    conversation_id=conv_id,
                    expires_minutes=5,
                )
            else:
                due_date_iso = due_obj.due_date.isoformat() if due_obj and due_obj.due_date else None
                due_at_iso = due_obj.due_at.isoformat() if due_obj and due_obj.due_at else None
                pending = await create_chat_pending_action(
                    conn,
                    action="reschedule_task_disambiguation",
                    task_ids=[t["id"] for t in candidates],
                    task_titles=[{
                        "id": t["id"],
                        "title": t["title"],
                        "due_date": due_date_iso,
                        "due_at": due_at_iso,
                        "due_label": due_label,
                    } for t in candidates],
                    count=len(candidates),
                    owner_identity=owner_identity,
                    conversation_id=conv_id,
                    expires_minutes=5,
                )
            items_str = " ".join(f"{i}) '{t['title']}'" for i, t in enumerate(candidates, 1))
            resp_msg = f"Which one: {items_str}?"
            ret_data = {"pending_action": pending, "matches": candidates}

        if persist:
            try:
                real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                await conversations.add_message(conn, real_cid, role="user", content=message)
                await conversations.add_message(
                    conn, real_cid, role="assistant", content=resp_msg, skill_called="chat_task_action", verifiable=False,
                )
                conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist chat_task_action history: {e}")

    return {
        "conversation_id": conv_id,
        "response": resp_msg,
        "message": resp_msg,
        "skill_used": "chat_task_action",
        "success": True,
        "data": ret_data,
        "verifiable": False,
        "routing_latency_ms": int((time.perf_counter() - start) * 1000),
    }


async def _apply_task_mutation(
    conn: Any,
    task_id: int,
    is_complete: bool,
    meta: Dict[str, Any],
    owner_identity: str,
) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    """Apply complete or reschedule update with owner scoping and return result tuple."""
    if is_complete:
        updated = await structured.update_task(conn, task_id, owner_id=owner_identity, status="done")
        if updated:
            title = meta.get("title") or updated.get("title") or "task"
            return (f"Done: marked '{title}' as done.", {"completed_task": updated, "success": True}, True)
        return ("I couldn't update it, nothing was changed.", None, False)

    due_date_str = meta.get("due_date")
    due_at_str = meta.get("due_at")
    due_label = meta.get("due_label") or due_date_str
    due_date_val = date.fromisoformat(due_date_str) if due_date_str else None
    due_at_val = datetime.fromisoformat(due_at_str) if due_at_str else None

    updated = await structured.update_task(conn, task_id, owner_id=owner_identity, due_date=due_date_val)
    if updated and due_at_val is not None:
        await conn.execute(
            "UPDATE tasks SET due_at = $1 WHERE id = $2 AND lower(user_id) = lower($3)",
            due_at_val, task_id, owner_identity,
        )
    if updated:
        title = meta.get("title") or updated.get("title") or "task"
        return (f"Done: moved '{title}' to {due_label}.", {"rescheduled_task": updated, "success": True}, True)
    return ("I couldn't update it, nothing was changed.", None, False)


async def execute_pending_task_action(
    conn: Any,
    active_action: Dict[str, Any],
    owner_identity: str,
    message: str,
) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    """Execute complete/reschedule task action on confirm or disambiguation response."""
    act_type = active_action.get("action", "")
    task_ids = active_action.get("task_ids") or []
    task_titles = active_action.get("task_titles") or []
    if isinstance(task_titles, str):
        import json
        try:
            task_titles = json.loads(task_titles)
        except Exception:
            task_titles = []

    normalized_reply = (message or "").lower().strip().rstrip(".!?")

    if act_type in ("complete_task", "reschedule_task"):
        if normalized_reply in ORDINAL_REPLIES:
            return ("That isn't a confirmation. Reply 'Confirm' to proceed or 'Cancel'.", None, False)
        if not task_ids:
            return ("No tasks were modified.", None, False)

        claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
        if not claimed:
            return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)

        meta = task_titles[0] if task_titles else {}
        return await _apply_task_mutation(conn, task_ids[0], act_type == "complete_task", meta, owner_identity)

    elif act_type in ("complete_task_disambiguation", "reschedule_task_disambiguation"):
        selected_id = _select_candidate(message, task_ids, task_titles)
        if selected_id is None:
            return (_disambiguation_prompt(len(task_ids)), None, False)

        claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
        if not claimed:
            return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)

        target_meta = next((it for it in task_titles if it.get("id") == selected_id), {})
        return await _apply_task_mutation(conn, selected_id, "complete" in act_type, target_meta, owner_identity)

    return ("No tasks were modified.", None, False)
