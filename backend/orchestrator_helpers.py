"""
Compass — Orchestrator Mapping and Parsing Helpers.

Provides canonical normalization maps for priorities, statuses, ISO dates,
and fallback chat response formatters.
"""

import time
import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("compass.orchestrator.helpers")

PRIORITY_MAP = {
    "urgent": "urgent", "critical": "urgent", "p0": "urgent", "asap": "urgent",
    "high": "high", "p1": "high", "important": "high",
    "medium": "medium", "normal": "medium", "p2": "medium", "moderate": "medium",
    "low": "low", "p3": "low", "minor": "low",
}

STATUS_MAP = {
    "open": "open", "todo": "open", "to_do": "open", "pending": "open", "not_started": "open",
    "in_progress": "in_progress", "in progress": "in_progress", "doing": "in_progress", "wip": "in_progress",
    "done": "done", "completed": "done", "finished": "done", "closed": "done",
    "overdue": "overdue",
}


def parse_iso_date(val: Optional[str]) -> Optional[date]:
    """Parse ISO date strings into date objects, rolling past years forward if needed."""
    if not val:
        return None
    try:
        clean = val.strip().split("T")[0].split(" ")[0]
        parsed = datetime.strptime(clean, "%Y-%m-%d").date()
        today = date.today()
        # If the date was parsed with a past year (e.g. LLM defaulted to 2024/2025 instead of current year),
        # roll it forward to the current year or next occurrence.
        if parsed < today and parsed.year < today.year:
            try:
                candidate = date(today.year, parsed.month, parsed.day)
                if candidate >= today:
                    return candidate
                return date(today.year + 1, parsed.month, parsed.day)
            except ValueError:
                pass
        return parsed
    except Exception:
        return None


async def format_chat_response(
    conv_id: str,
    message: str,
    text_reply: Optional[str],
    user_id: Optional[str],
    guest_id: Optional[str],
    persist: bool,
    start_time: float,
    verifiable: bool = False,
    tone: Optional[str] = None,
) -> Dict[str, Any]:
    """Format and persist canonical chat response payload."""
    from backend.router_helpers import is_greeting_intent
    from backend.persona import format_greeting_by_tone, format_fallback_by_tone
    from backend.memory import conversations

    is_empty_reply = not (text_reply or "").strip()
    is_greeting = is_greeting_intent(message)
    chat_success = True
    chat_error = None

    if is_empty_reply:
        if is_greeting:
            text_reply = format_greeting_by_tone(tone)
        else:
            chat_success = False
            chat_error = "empty_model_response"
            from backend.config import get_settings
            s = get_settings()
            key = s.NEBIUS_API_KEY or ""
            if not key or key.startswith("your_nebius") or key.startswith("mock") or key in ("mock", "mock-key-not-used-in-tests"):
                text_reply = "Model key missing or invalid. See the setup notes. Please retry."
            else:
                text_reply = "I encountered an empty response from the model. Please retry."
    elif is_greeting:
        text_reply = format_greeting_by_tone(tone)

    safe_reply = text_reply or ""

    if persist:
        try:
            from backend.memory.db import get_pool
            pool = await get_pool()
            if pool:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(
                        conn, conv_id, user_id=user_id, guest_id=guest_id
                    )
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(conn, real_cid, role="assistant", content=safe_reply, skill_called="chat", verifiable=verifiable)
                    conv_id = real_cid
        except Exception as e:
            logger.debug(f"Could not persist message history: {e}")

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    return {
        "conversation_id": conv_id,
        "response": safe_reply,
        "message": safe_reply,
        "skill_used": "chat",
        "success": chat_success,
        "error": chat_error,
        "data": {"can_retry": not chat_success} if not chat_success else None,
        "verifiable": verifiable,
        "routing_latency_ms": latency_ms,
    }
