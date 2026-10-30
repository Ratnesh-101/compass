"""
Compass — Skill Registry and Dispatcher.

Maintains the central map of skill names to their async handler implementations.
"""

import logging
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger("compass.skills")

SkillHandler = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
SKILL_REGISTRY: Dict[str, SkillHandler] = {}


def register_skill(name: str):
    """Decorator to register a skill handler function into SKILL_REGISTRY."""
    def decorator(fn: SkillHandler):
        SKILL_REGISTRY[name] = fn
        return fn
    return decorator


EXTERNAL_SIDE_EFFECT_TOOLS = frozenset({"commit_schedule", "ingest_url"})
HIGH_RISK_TOOLS = frozenset({"delete_task", "apply_triage_plan", "commit_schedule"})
GUEST_DISALLOWED_TOOLS = EXTERNAL_SIDE_EFFECT_TOOLS | HIGH_RISK_TOOLS


def is_tool_allowed_for_identity(
    tool_name: str,
    identity: Optional[Any] = None,
    is_guest: Optional[bool] = None,
) -> bool:
    """Return True if the identity is permitted to execute tool_name."""
    guest_flag = False
    if is_guest is not None:
        guest_flag = bool(is_guest)
    elif hasattr(identity, "is_guest"):
        guest_flag = bool(identity.is_guest)
    elif not identity:
        guest_flag = True
    else:
        guest_flag = str(identity).startswith("guest_")

    if guest_flag and tool_name in GUEST_DISALLOWED_TOOLS:
        return False
    return True


async def dispatch_skill(
    skill_name: str,
    args: Dict[str, Any],
    pool: Any,
    is_guest: Optional[bool] = None,
) -> Dict[str, Any]:
    """Dispatch execution to registered skill handler or return fallback response."""
    user_id = args.get("user_id") if isinstance(args, dict) else None
    guest_flag = False
    if is_guest is not None:
        guest_flag = bool(is_guest)
    elif isinstance(args, dict) and "is_guest" in args:
        guest_flag = bool(args.get("is_guest"))
    elif user_id and str(user_id).startswith("guest_"):
        guest_flag = True

    if guest_flag and skill_name in GUEST_DISALLOWED_TOOLS:
        raise PermissionError(
            f"Permission denied: Guest sessions are forbidden from invoking high-risk or external side-effect tool '{skill_name}'. Please sign in."
        )
    if skill_name in SKILL_REGISTRY:
        return await SKILL_REGISTRY[skill_name](args, pool)
    raise ValueError(f"Skill '{skill_name}' is not registered in SKILL_REGISTRY.")
