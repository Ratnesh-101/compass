"""Compass — Chat Extra Actions Service.

Provides deterministic intent detection and pending-action confirmation for:
1. Adding listings to the user's watchlist (with open listings search, disambiguation, and confirm).
2. Deleting current conversation safely behind confirm (no mutation before confirm, unpersisted final response).
3. Exporting calendar download instructions and URL.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.memory.chat_pending import (
    create_chat_pending_action,
    get_active_chat_pending_action,
    resolve_chat_pending_action,
)
from backend.memory import conversations
from backend.memory.db import get_pool
from backend.memory.radar import (
    get_all_opportunities,
    get_opportunity_by_id,
    upsert_user_saved_opportunity,
)
from backend.router_helpers import (
    ORDINAL_REPLIES,
    is_pending_action_confirm,
    is_pending_action_cancel,
)

logger = logging.getLogger("compass.services.chat_extra_actions")

_WATCHLIST_VERBS = frozenset({"add", "save", "put", "move"})
_WATCHLIST_TAILS = (" to my watchlist", " to watchlist")
RE_WATCHLIST_PREFIX = re.compile(r"^watchlist\s+(?P<target>[a-zA-Z0-9].*)$", re.IGNORECASE)
RE_DELETE_CHAT = re.compile(r"^(?:delete|clear|remove)\s+(?:this|current|the)\s+(?:chat|conversation)$", re.IGNORECASE)
RE_EXPORT_CALENDAR = re.compile(r"^(?:export|download)\s+(?:my\s+|the\s+)?(?:calendar|schedule)(?:\.ics)?$", re.IGNORECASE)

POSITIONAL_WORDS = frozenset({
    "it", "this", "that", "these", "those", "them", "one", "ones",
    "first", "second", "third", "last", "next", "previous", "other", "another",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "1st", "2nd", "3rd", "4th", "5th",
    "all", "everything", "listing", "listings", "the", "a", "an", "my",
})

_ORDINAL_INDEX = {
    "1": 0, "first": 0, "first one": 0, "the first one": 0, "1st": 0,
    "2": 1, "second": 1, "second one": 1, "the second one": 1, "2nd": 1,
    "3": 2, "third": 2, "third one": 2, "the third one": 2, "3rd": 2,
    "4": 3, "fourth": 3, "fourth one": 3, "the fourth one": 3, "4th": 3,
    "5": 4, "fifth": 4, "fifth one": 4, "the fifth one": 4, "5th": 4,
}


def _clean_target(target: str) -> str:
    """Strip leading articles and surrounding whitespace."""
    return re.sub(r"^(?:the|a|an)\s+", "", target.strip(), flags=re.IGNORECASE).strip()


def _is_positional_target(target: str) -> bool:
    """Return True if target is ambiguous, empty, or consists solely of positional/pronoun words."""
    if not target or not target.strip():
        return True
    cleaned = _clean_target(target)
    words = re.findall(r"\w+", cleaned.lower())
    if not words or all(w in POSITIONAL_WORDS for w in words):
        return True
    return cleaned.lower() in ("first one", "second one", "third one", "last one", "the first one")


def parse_extra_action_intent(message: str) -> Optional[Dict[str, Any]]:
    """Deterministically parse watchlist, delete chat, or export calendar intents."""
    if not message or not isinstance(message, str):
        return None
    normalized = " ".join(message.strip().split())[:400].rstrip(".!?")
    if not normalized:
        return None
    if RE_DELETE_CHAT.match(normalized):
        return {"action": "delete_chat"}
    if RE_EXPORT_CALENDAR.match(normalized):
        return {"action": "export_calendar"}
    verb, _, rest = normalized.partition(" ")
    add_target = None
    if verb.lower() in _WATCHLIST_VERBS:
        for tail in _WATCHLIST_TAILS:
            if rest.lower().endswith(tail):
                add_target = rest[: -len(tail)]
                break
    if add_target:
        target = _clean_target(add_target)
        if not _is_positional_target(target):
            return {"action": "watchlist", "target": target}
    m_prefix = RE_WATCHLIST_PREFIX.match(normalized)
    if m_prefix:
        target = _clean_target(m_prefix.group("target"))
        if not _is_positional_target(target):
            return {"action": "watchlist", "target": target}
    return None


def is_extra_action_intent(message: str) -> bool:
    """Return True if message matches an extra action deterministic intent."""
    return parse_extra_action_intent(message) is not None


def _opp_field(opp: Any, field: str, default: Any = "") -> Any:
    return opp.get(field, default) if isinstance(opp, dict) else getattr(opp, field, default)


def match_opportunities(target: str, items: List[Any]) -> List[Dict[str, Any]]:
    """Match company/role text against open opportunity listings."""
    if not items or not target:
        return []
    target_clean = _clean_target(target).lower()
    target_words = set(w for w in target_clean.split() if w not in ("intern", "internship", "at", "in", "the", "for", "to", "of"))
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for item in items:
        opp_id = _opp_field(item, "id")
        company = str(_opp_field(item, "company_name", "")).strip()
        role = str(_opp_field(item, "role_title", "")).strip()
        comp_l, role_l = company.lower(), role.lower()
        combined, role_comp = f"{comp_l} {role_l}", f"{role_l} {comp_l}"
        if target_clean in (combined, role_comp, comp_l, role_l):
            score = 1.0
        elif target_clean in combined or target_clean in role_comp:
            score = 0.95
        elif target_words and target_words.issubset(set(combined.split())):
            score = 0.9
        else:
            r1 = difflib.SequenceMatcher(None, target_clean, combined).ratio()
            r2 = difflib.SequenceMatcher(None, target_clean, role_comp).ratio()
            r3 = difflib.SequenceMatcher(None, target_clean, comp_l).ratio()
            r4 = difflib.SequenceMatcher(None, target_clean, role_l).ratio()
            score = max(r1, r2, r3, r4)
            overlap = len(set(target_clean.split()) & set(combined.split()))
            if overlap >= 2:
                score = max(score, 0.65 + 0.1 * overlap)
        if score >= 0.55:
            scored.append((score, {"id": opp_id, "company_name": company, "role_title": role}))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    tied = [item for s, item in scored if abs(s - top_score) < 0.05]
    return [tied[0]] if len(tied) == 1 else tied[:5]


def _disambiguation_prompt(count: int) -> str:
    if count == 1:
        return "Reply with 1, or 'Cancel'."
    if count == 2:
        return "Which one? Reply with 1 or 2, or 'Cancel'."
    return f"Which one? Reply with 1, 2 or {count}, or 'Cancel'."


def _select_opportunity_candidate(message: str, task_ids: list, task_titles: Optional[list] = None) -> Optional[int]:
    reply = (message or "").lower().strip().rstrip(".!?")
    idx = _ORDINAL_INDEX.get(reply)
    if idx is not None and idx < len(task_ids):
        return task_ids[idx]
    if reply.isdigit() and int(reply) in task_ids:
        return int(reply)
    if task_titles:
        for t in task_titles:
            c_name = str(t.get("company_name", "")).lower().strip()
            r_title = str(t.get("role_title", "")).lower().strip()
            if (c_name and reply in c_name) or (r_title and reply in r_title):
                return t.get("id")
    return None


async def execute_pending_extra_action(
    conn: Any,
    active_action: Dict[str, Any],
    owner_identity: str,
    message: str,
    conv_id: Optional[str] = None,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
) -> Tuple[str, Optional[Dict[str, Any]], bool]:
    """Execute confirmed pending action for watchlist or delete_chat."""
    act_type = active_action.get("action", "")
    task_ids = active_action.get("task_ids") or []
    task_titles = active_action.get("task_titles") or []
    if isinstance(task_titles, str):
        try:
            task_titles = json.loads(task_titles)
        except Exception:
            task_titles = []
    normalized_reply = (message or "").lower().strip().rstrip(".!?")

    if act_type == "add_to_watchlist":
        if normalized_reply in ORDINAL_REPLIES:
            return ("That isn't a confirmation. Reply 'Confirm' to proceed or 'Cancel'.", None, False)
        if not task_ids:
            return ("No listing was specified to add.", None, False)
        claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
        if not claimed:
            return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)
        opp_id = task_ids[0]
        meta = task_titles[0] if task_titles else {}
        role = meta.get("role_title") or "opportunity"
        company = meta.get("company_name") or ""
        display_name = f"{role} @ {company}" if company else role
        try:
            opp = await get_opportunity_by_id(opp_id)
            if not opp:
                return ("I couldn't add this listing to your watchlist: listing not found.", None, False)
            await upsert_user_saved_opportunity(owner_identity, opp_id, is_saved=True)
            return (f"Done: added '{display_name}' to your watchlist.", {"opportunity_id": opp_id, "saved": True, "display_name": display_name}, True)
        except Exception as e:
            logger.exception("Failed to save opportunity to watchlist: %s", e)
            return ("I couldn't add this listing to your watchlist, nothing was changed.", None, False)

    elif act_type == "add_to_watchlist_disambiguation":
        selected_id = _select_opportunity_candidate(message, task_ids, task_titles)
        if selected_id is None:
            return (_disambiguation_prompt(len(task_ids)), None, False)
        claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
        if not claimed:
            return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)
        selected_meta = next((t for t in task_titles if t.get("id") == selected_id), {})
        role = selected_meta.get("role_title") or "opportunity"
        company = selected_meta.get("company_name") or ""
        display_name = f"{role} @ {company}" if company else role
        card_text = f"Add '{display_name}' to your watchlist?"
        new_action = await create_chat_pending_action(
            conn, action="add_to_watchlist", task_ids=[selected_id],
            task_titles=[{"id": selected_id, "role_title": role, "company_name": company}],
            count=1, owner_identity=owner_identity,
            conversation_id=active_action.get("conversation_id") or conv_id, expires_minutes=5,
        )
        new_action["card_text"] = card_text
        return (f"{card_text} Please confirm to proceed or click Cancel.", {"pending_action": new_action, "opportunity": selected_meta}, False)

    elif act_type == "delete_chat":
        if normalized_reply in ORDINAL_REPLIES:
            return ("That isn't a confirmation. Reply 'Confirm' to proceed or 'Cancel'.", None, False)
        target_conv_id = conv_id or active_action.get("conversation_id")
        if not target_conv_id and task_titles and isinstance(task_titles[0], dict):
            target_conv_id = task_titles[0].get("conversation_id")
        if not target_conv_id:
            return ("I couldn't identify the current conversation to delete.", None, False)
        claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
        if not claimed:
            return ("There are no pending actions to confirm. What would you like me to help you with?", None, False)
        has_access, err = await conversations.check_conversation_access(
            conn, target_conv_id, user_id=user_id, guest_id=guest_id, allow_shared=False
        )
        if not has_access:
            return (f"I couldn't delete this chat: {err or 'access denied'}.", None, False)
        ok = await conversations.delete_conversation(conn, target_conv_id)
        if ok:
            return ("Done: chat deleted.", {"conversation_deleted": True, "conversation_id": target_conv_id}, True)
        return ("I couldn't delete this conversation, nothing was changed.", None, False)

    return ("No action was recognized.", None, False)


async def handle_chat_extra_actions_stream(
    message: str, conv_id: str, user_id: Optional[str], guest_id: Optional[str], pool: Any,
) -> Optional[Dict[str, Any]]:
    """Handle extra deterministic action stream processing and pending-action resolution."""
    active_pool = pool or await get_pool()
    if not active_pool:
        return None
    owner_identity = user_id or guest_id or "default_user"

    # 1. Pending action resolution (Confirm, Cancel, or Disambiguation selection)
    async with active_pool.acquire() as conn:
        active_action = await get_active_chat_pending_action(conn, owner_identity, conv_id)
        if active_action and active_action.get("action") in ("add_to_watchlist", "add_to_watchlist_disambiguation", "delete_chat"):
            act = active_action["action"]
            if is_pending_action_cancel(message):
                await resolve_chat_pending_action(conn, active_action["id"], "cancelled")
                resp_msg = "Cancelled: chat was not deleted." if act == "delete_chat" else "Cancelled: listing was not added to your watchlist."
                return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": act, "success": True, "data": None, "verifiable": False}

            if is_pending_action_confirm(message) or act == "add_to_watchlist_disambiguation":
                resp_msg, ret_data, success = await execute_pending_extra_action(
                    conn, active_action, owner_identity, message, conv_id=conv_id, user_id=user_id, guest_id=guest_id
                )
                if act == "delete_chat" and success:
                    return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "delete_chat", "success": True, "data": ret_data, "verifiable": False}
                try:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called=act, verifiable=False)
                    conv_id = real_cid
                except Exception as e:
                    logger.debug("Could not persist extra action history: %s", e)
                return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": act, "success": success, "data": ret_data, "verifiable": False}

    # 2. Intent detection
    intent = parse_extra_action_intent(message)
    if not intent:
        return None

    if intent["action"] == "export_calendar":
        resp_msg = "Open the Calendar tab and use Export to download your schedule, or download it directly from /api/calendar/export.ics."
        async with active_pool.acquire() as conn:
            try:
                real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                await conversations.add_message(conn, real_cid, role="user", content=message)
                await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="export_calendar", verifiable=False)
                conv_id = real_cid
            except Exception as e:
                logger.debug("Could not persist calendar export history: %s", e)
        return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "export_calendar", "success": True, "data": {"export_path": "/api/calendar/export.ics"}, "verifiable": False}

    if intent["action"] == "delete_chat":
        card_text = "Delete this chat and its messages? This cannot be undone."
        resp_msg = f"{card_text} Please confirm to proceed or click Cancel."
        async with active_pool.acquire() as conn:
            pending = await create_chat_pending_action(
                conn, action="delete_chat", task_ids=[], task_titles=[{"conversation_id": conv_id}],
                count=1, owner_identity=owner_identity, conversation_id=conv_id, expires_minutes=5,
            )
            pending["card_text"] = card_text
            try:
                real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                await conversations.add_message(conn, real_cid, role="user", content=message)
                await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="delete_chat", verifiable=False)
                conv_id = real_cid
            except Exception as e:
                logger.debug("Could not persist delete chat history: %s", e)
        return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "delete_chat", "success": True, "data": {"pending_action": pending}, "verifiable": False}

    # Intent 3: Watchlist
    target = intent.get("target") or ""
    raw_items, _ = await get_all_opportunities(user_id=owner_identity, status="OPEN_CONFIRMED", page_size=200)
    matches = match_opportunities(target, raw_items)

    async with active_pool.acquire() as conn:
        if not matches:
            suggestions = [f"'{_opp_field(o, 'role_title')} @ {_opp_field(o, 'company_name')}'" for o in raw_items[:3]]
            resp_msg = f"I couldn't find a listing matching '{target}'. Here are some open listings: {', '.join(suggestions)}." if suggestions else f"I couldn't find a listing matching '{target}'."
            ret_data = None
        elif len(matches) == 1:
            opp = matches[0]
            card_text = f"Add '{opp['role_title']} @ {opp['company_name']}' to your watchlist?"
            resp_msg = f"{card_text} Please confirm to proceed or click Cancel."
            pending = await create_chat_pending_action(
                conn, action="add_to_watchlist", task_ids=[opp["id"]], task_titles=[opp],
                count=1, owner_identity=owner_identity, conversation_id=conv_id, expires_minutes=5,
            )
            pending["card_text"] = card_text
            ret_data = {"pending_action": pending, "opportunity": opp}
        else:
            candidates = matches[:3]
            items_str = " ".join(f"{i}) '{o['role_title']} @ {o['company_name']}'" for i, o in enumerate(candidates, 1))
            resp_msg = f"Which one: {items_str}?"
            pending = await create_chat_pending_action(
                conn, action="add_to_watchlist_disambiguation", task_ids=[o["id"] for o in candidates],
                task_titles=candidates, count=len(candidates), owner_identity=owner_identity,
                conversation_id=conv_id, expires_minutes=5,
            )
            pending["card_text"] = resp_msg
            ret_data = {"pending_action": pending, "matches": candidates}

        try:
            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
            await conversations.add_message(conn, real_cid, role="user", content=message)
            await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="add_to_watchlist", verifiable=False)
            conv_id = real_cid
        except Exception as e:
            logger.debug("Could not persist watchlist history: %s", e)

    return {"conversation_id": conv_id, "response": resp_msg, "message": resp_msg, "skill_used": "add_to_watchlist", "success": True, "data": ret_data, "verifiable": False}
