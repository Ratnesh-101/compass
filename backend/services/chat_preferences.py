"""
Compass — Chat Planning Preferences Service.
Deterministic intent detection and pending-action confirmation for user scheduling preferences.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.memory.chat_pending import (
    create_chat_pending_action,
    get_active_chat_pending_action,
    resolve_chat_pending_action,
)
from backend.memory import structured, conversations
from backend.memory.db import get_pool
from backend.router_helpers import (
    ORDINAL_REPLIES,
    is_pending_action_confirm,
    is_pending_action_cancel,
)

logger = logging.getLogger("compass.services.chat_preferences")

DAY_MAP = {
    "mon": 1, "monday": 1, "tue": 2, "tuesday": 2, "wed": 3, "wednesday": 3,
    "thu": 4, "thur": 4, "thurs": 4, "thursday": 4, "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6, "sun": 7, "sunday": 7,
}
SHORT_DAYS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}

CUE_RE = re.compile(
    r"\b(?:planning hours|work hours|working days|break between|study hours|schedule preferences)\b",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(
    r"(?:(?:from|hours(?:\s+to)?|to)\s+)?(\d{1,2}(?::[0-5]\d)?(?:\s*[ap]m)?)(?:\s+to\s+|\s*-\s*)(\d{1,2}(?::[0-5]\d)?(?:\s*[ap]m)?)",
    re.IGNORECASE,
)
BREAK_RE = re.compile(r"\b(\d{1,3})\s*(?:minutes?|mins?)\b", re.IGNORECASE)
DAY_RANGE_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)(?:\s+(?:to|through)\s+|\s*-\s*)(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b",
    re.IGNORECASE,
)

_ALIASES = {
    "working_days": "work_days",
    "work_days": "working_days",
    "buffer_minutes": "break_minutes",
    "break_minutes": "buffer_minutes",
}


class PreferencesIntent(dict):
    """Dictionary supporting alias lookups for work_days/working_days and break_minutes/buffer_minutes."""

    def __getitem__(self, key: str) -> Any:
        alt = _ALIASES.get(key)
        if alt and alt in self:
            return self[alt]
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        alt = _ALIASES.get(key)
        if alt and alt in self:
            return self[alt]
        return super().get(key, default)


def _parse_time(raw: str, is_end: bool = False, start_h: Optional[int] = None) -> Optional[str]:
    m = re.match(r"^(\d{1,2})(?::([0-5]\d))?(?:\s*(am|pm))?$", raw.strip().lower())
    if not m:
        return None
    h, minute, ampm = int(m.group(1)), int(m.group(2)) if m.group(2) else 0, m.group(3)
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    elif not ampm and is_end:
        if (start_h is not None and h <= start_h and h <= 11) or h < 8:
            h += 12
    return f"{h:02d}:{minute:02d}" if (h <= 23 and minute <= 59) else None


def parse_preferences_intent(message: str) -> Optional[dict]:
    """Pure parser detecting planning preferences intent."""
    if not message or not isinstance(message, str):
        return None

    # Collapse every whitespace run to a single space and cap at 600 characters
    message = " ".join(message.split())[:600]
    if not message or not CUE_RE.search(message):
        return None

    msg_low, res = message.lower(), PreferencesIntent()

    # 1. Planning / Work hours
    if any(k in msg_low for k in ("planning hours", "work hours", "study hours", "schedule preferences")):
        m_time = TIME_RANGE_RE.search(msg_low)
        if m_time:
            t1 = _parse_time(m_time.group(1), is_end=False)
            start_h = int(t1.split(":")[0]) if t1 else None
            t2 = _parse_time(m_time.group(2), is_end=True, start_h=start_h)
            if t1 and t2:
                res["work_start_time"], res["work_end_time"] = t1, t2

    # 2. Working days
    if any(k in msg_low for k in ("working days", "work days", "schedule preferences")) or (
        "planning hours" in msg_low and any(d in msg_low for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun", "weekdays", "all week"))
    ):
        if "weekdays" in msg_low:
            res["work_days"] = [1, 2, 3, 4, 5]
        elif any(w in msg_low for w in ("all week", "every day", "all days")):
            res["work_days"] = [1, 2, 3, 4, 5, 6, 7]
        else:
            m_range = DAY_RANGE_RE.search(msg_low)
            if m_range:
                d1, d2 = DAY_MAP[m_range.group(1)], DAY_MAP[m_range.group(2)]
                res["work_days"] = list(range(d1, d2 + 1)) if d1 <= d2 else list(range(d1, 8)) + list(range(1, d2 + 1))
            else:
                tokens = re.findall(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b", msg_low)
                if tokens:
                    res["work_days"] = sorted(list({DAY_MAP[t] for t in tokens}))

    # 3. Break between tasks
    if any(k in msg_low for k in ("break between", "break", "schedule preferences")):
        m_break = BREAK_RE.search(msg_low)
        if m_break and 0 <= int(m_break.group(1)) <= 120:
            res["break_minutes"] = int(m_break.group(1))

    return res if res else None


def format_pref_card_text(pref: dict) -> str:
    """Format short summary for pending action card text."""
    parts: List[str] = []
    if pref.get("work_start_time") and pref.get("work_end_time"):
        parts.append(f"{pref['work_start_time']}-{pref['work_end_time']}")
    if pref.get("work_days"):
        wd = pref["work_days"]
        if wd == [1, 2, 3, 4, 5]:
            parts.append("Mon-Fri")
        elif wd == [1, 2, 3, 4, 5, 6]:
            parts.append("Mon-Sat")
        elif wd == [1, 2, 3, 4, 5, 6, 7]:
            parts.append("All week")
        else:
            parts.append(", ".join(SHORT_DAYS[d] for d in wd if d in SHORT_DAYS))
    bm = pref.get("buffer_minutes") if pref.get("buffer_minutes") is not None else pref.get("break_minutes")
    if bm is not None:
        parts.append(f"{bm} min breaks")
    return f"Update your planning preferences: {', '.join(parts)}?"


async def execute_pending_preferences(
    conn: Any,
    active_action: Dict[str, Any],
    owner_identity: str,
    message: str,
) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    """Execute update_preferences pending action on confirm."""
    normalized = (message or "").lower().strip().rstrip(".!?")
    if normalized in ORDINAL_REPLIES:
        return ("That isn't a confirmation. Reply 'Confirm' to proceed or 'Cancel'.", None, False)

    claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
    if not claimed:
        return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)

    task_titles = active_action.get("task_titles") or []
    if isinstance(task_titles, str):
        try:
            task_titles = json.loads(task_titles)
        except Exception:
            task_titles = []
    meta = task_titles[0] if task_titles else {}

    updates: Dict[str, Any] = {}
    for k in ("work_start_time", "work_end_time", "work_days"):
        if meta.get(k):
            updates[k] = meta[k]
    bm = meta.get("buffer_minutes") if meta.get("buffer_minutes") is not None else meta.get("break_minutes")
    if bm is not None:
        updates["buffer_minutes"] = bm

    try:
        prefs = await structured.update_scheduling_preferences(conn, user_id=owner_identity, **updates)
    except Exception as e:
        logger.exception("Failed to update scheduling preferences: %s", e)
        return ("I couldn't save your planning preferences, nothing was changed.", None, False)

    if not prefs:
        return ("I couldn't save your planning preferences, nothing was changed.", None, False)

    # Read the saved values back from the database; never echo the requested ones.
    try:
        saved = await structured.get_scheduling_preferences(conn, owner_identity)
    except Exception as e:
        logger.warning("Could not read back scheduling preferences, using the update result: %s", e)
        saved = prefs
    if not isinstance(saved, dict):
        saved = prefs

    def _hhmm(v: Any) -> str:
        return str(v)[:5] if v is not None else ""

    saved_view: Dict[str, Any] = {}
    failed: List[str] = []
    for key in ("work_start_time", "work_end_time"):
        if key in updates:
            if key not in saved or _hhmm(saved[key]) == _hhmm(updates[key]):
                saved_view[key] = _hhmm(saved.get(key, updates[key]))
            elif "hours" not in failed:
                failed.append("hours")
    if "work_days" in updates:
        want = [int(d) for d in updates["work_days"]]
        if "work_days" not in saved or [int(d) for d in (saved["work_days"] or [])] == want:
            saved_view["work_days"] = [int(d) for d in saved["work_days"]] if "work_days" in saved else want
        else:
            failed.append("working days")
    if "buffer_minutes" in updates:
        if "buffer_minutes" not in saved or saved["buffer_minutes"] == updates["buffer_minutes"]:
            saved_view["buffer_minutes"] = updates["buffer_minutes"]
        else:
            failed.append("break length")

    if failed:
        what = " and ".join(failed)
        saved_text = format_pref_card_text(saved_view).replace("Update your planning preferences: ", "").rstrip("?")
        if saved_view:
            msg = f"I could not save the {what}; the rest was saved: {saved_text}."
            if failed == ["working days"] and "work_start_time" in saved_view:
                msg = "I could not save the working days; hours were saved."
            return (msg, {"preferences": saved, "success": False}, False)
        return (f"I could not save the {what}; nothing else was changed.", {"preferences": saved, "success": False}, False)
    card = format_pref_card_text(saved_view).replace("Update your planning preferences: ", "").rstrip("?")
    return (f"Done: updated your planning preferences: {card}.", {"preferences": saved, "success": True}, True)


async def handle_chat_preferences_stream(
    message: str, conv_id: str, user_id: Optional[str], guest_id: Optional[str], pool: Any,
) -> Optional[Dict[str, Any]]:
    """Handle preference pending action creation or resolution for streaming chat."""
    active_pool = pool or await get_pool()
    if not active_pool:
        return None
    owner_identity = user_id or guest_id or "default_user"

    # Confirmation / Cancellation check
    if is_pending_action_confirm(message) or is_pending_action_cancel(message):
        async with active_pool.acquire() as conn:
            active_action = await get_active_chat_pending_action(conn, owner_identity, conv_id)
            if not active_action or active_action.get("action") != "update_preferences":
                return None
            if is_pending_action_cancel(message):
                await resolve_chat_pending_action(conn, active_action["id"], "cancelled")
                resp_msg = "Cancelled: no preferences were changed."
                return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "update_preferences", "success": True, "data": None, "verifiable": False}
            try:
                resp_msg, ret_data, success = await execute_pending_preferences(conn, active_action, owner_identity, message)
            except Exception as e:
                logger.exception("Failed to execute preferences pending action: %s", e)
                resp_msg = "I couldn't save your planning preferences, nothing was changed."
                return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "update_preferences", "success": False, "data": None, "verifiable": False}
            return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "update_preferences", "success": success, "data": ret_data, "verifiable": False}

    # Intent check
    pref = parse_preferences_intent(message)
    if not pref:
        return None

    card_text = format_pref_card_text(pref)
    resp_msg = f"{card_text} Please confirm to proceed or click Cancel."

    async with active_pool.acquire() as conn:
        pending = await create_chat_pending_action(
            conn, action="update_preferences", task_ids=[], task_titles=[dict(pref)],
            count=1, owner_identity=owner_identity, conversation_id=conv_id, expires_minutes=5,
        )
        pending["card_text"] = card_text
        try:
            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
            await conversations.add_message(conn, real_cid, role="user", content=message)
            await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="update_preferences", verifiable=False)
            conv_id = real_cid
        except Exception as e:
            logger.debug(f"Could not persist preference history: {e}")

    return {
        "conversation_id": conv_id, "response": resp_msg, "message": resp_msg,
        "skill_used": "update_preferences", "success": True,
        "data": {"pending_action": pending, "preferences": dict(pref)},
        "verifiable": False, "routing_latency_ms": 0,
    }
