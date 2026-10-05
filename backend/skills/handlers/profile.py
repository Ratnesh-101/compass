"""
Compass — Profile Facts Skill Handlers.

Handles `remember_fact` and `forget_fact` skills to persist and update
personal details (name, goals, preferences) across conversations.
"""

from typing import Any, Dict
import logging
from backend.skills.registry import register_skill
from backend.memory.profile import set_profile_fact, delete_profile_fact

logger = logging.getLogger("compass.skills.profile")


@register_skill("remember_fact")
async def handle_remember_fact(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Store or update an explicit personal fact or preference."""
    key = str(args.get("key", "")).strip().lower()
    value = str(args.get("value", "")).strip()
    user_id = str(args.get("user_id") or "default_user")

    if not key or not value:
        return {
            "success": False,
            "error": "Both 'key' and 'value' are required to remember a fact.",
            "summary": "I couldn't catch that detail — what would you like me to remember?",
        }

    try:
        async with pool.acquire() as conn:
            record = await set_profile_fact(conn, key=key, value=value, user_id=user_id)

        clean_key = key.replace("_", " ")
        if key in ("name", "user_name", "first_name"):
            summary = f"Nice to meet you, {value}. I'll remember that."
        else:
            summary = f"Noted. I'll remember that your {clean_key} is {value}."

        return {
            "success": True,
            "summary": summary,
            "data": {
                "key": key,
                "value": value,
                "record": record,
            },
        }
    except Exception as e:
        logger.error("Failed to store profile fact: %s", e, exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "summary": "I had trouble saving that detail just now.",
        }


@register_skill("forget_fact")
async def handle_forget_fact(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Remove a previously stored personal fact or preference."""
    key = str(args.get("key", "")).strip().lower()
    user_id = str(args.get("user_id") or "default_user")

    if not key:
        return {
            "success": False,
            "error": "A 'key' is required to forget a fact.",
            "summary": "What would you like me to forget?",
        }

    try:
        async with pool.acquire() as conn:
            removed = await delete_profile_fact(conn, key=key, user_id=user_id)

        if removed:
            summary = "Done. I've forgotten that and won't bring it up again."
        else:
            summary = f"I didn't have anything saved for '{key}' anyway."

        return {
            "success": True,
            "summary": summary,
            "data": {
                "key": key,
                "removed": removed,
            },
        }
    except Exception as e:
        logger.error("Failed to delete profile fact: %s", e, exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "summary": "I had trouble clearing that detail just now.",
        }
