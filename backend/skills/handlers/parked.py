"""
Compass — Skill Handlers for Parked Thoughts ("Park it" shelf).

Handles park_thought, list_parked, and resolve_parked.
"""

import logging
from typing import Any, Dict
from backend.memory.parked import (
    park_thought,
    list_parked_thoughts,
    resolve_parked_thought,
    sanitize_parked_text,
)
from backend.persona import format_tool_response
from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.handlers.parked")


@register_skill("park_thought")
async def handle_park_thought(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Park a thought or tangent on the shelf for later."""
    raw_text = str(args.get("text") or "").strip()
    clean_text = sanitize_parked_text(raw_text)
    user_id = str(args.get("user_id") or "default_user")
    conv_id = args.get("conversation_id")

    if not clean_text:
        return {
            "response": "What would you like me to park for later?",
            "data": {"status": "error", "error": "empty_text"},
        }

    record = None
    if pool:
        try:
            async with pool.acquire() as conn:
                record = await park_thought(
                    conn,
                    text=clean_text,
                    user_id=user_id,
                    conversation_id=conv_id,
                )
        except Exception as e:
            logger.warning("Error parking thought in pool (continuing gracefully): %s", e)

    response_text = format_tool_response("park_thought", {"text": clean_text})
    return {
        "response": response_text,
        "data": {
            "status": "success",
            "thought": record or {"text": clean_text, "status": "parked"},
        },
    }


@register_skill("list_parked")
async def handle_list_parked(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """List thoughts on the parked shelf."""
    user_id = str(args.get("user_id") or "default_user")
    status = str(args.get("status") or "parked").lower().strip()
    if status not in ("parked", "done"):
        status = "parked"

    thoughts = []
    if pool:
        try:
            async with pool.acquire() as conn:
                thoughts = await list_parked_thoughts(conn, user_id=user_id, status=status)
        except Exception as e:
            logger.warning("Error listing parked thoughts (continuing gracefully): %s", e)

    if not thoughts:
        response_text = "Your parked shelf is empty right now."
    else:
        items = "\n".join([f"- [#{t['id']}] {t['text']}" for t in thoughts])
        response_text = f"Here is what's currently on your parked shelf:\n{items}"

    return {
        "response": response_text,
        "data": {
            "status": "success",
            "count": len(thoughts),
            "thoughts": thoughts,
        },
    }


@register_skill("resolve_parked")
async def handle_resolve_parked(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Resolve / mark done a parked thought."""
    thought_id = args.get("thought_id")
    user_id = str(args.get("user_id") or "default_user")

    try:
        tid = int(thought_id)
    except (TypeError, ValueError):
        return {
            "response": "Could you specify which parked item ID to mark as done?",
            "data": {"status": "error", "error": "invalid_thought_id"},
        }

    resolved = False
    if pool:
        try:
            async with pool.acquire() as conn:
                resolved = await resolve_parked_thought(conn, thought_id=tid, user_id=user_id)
        except Exception as e:
            logger.warning("Error resolving parked thought (continuing gracefully): %s", e)

    response_text = format_tool_response("resolve_parked", {"thought_id": str(tid), "resolved": str(resolved)})
    return {
        "response": response_text,
        "data": {
            "status": "success" if resolved else "not_found",
            "thought_id": tid,
            "resolved": resolved,
        },
    }
