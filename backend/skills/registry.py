"""
Compass — Skill Registry and Dispatcher.

Maintains the central map of skill names to their async handler implementations.
"""

from typing import Any, Callable, Coroutine, Dict
import logging

logger = logging.getLogger("compass.skills")

SkillHandler = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
SKILL_REGISTRY: Dict[str, SkillHandler] = {}


def register_skill(name: str):
    """Decorator to register a skill handler function into SKILL_REGISTRY."""
    def decorator(fn: SkillHandler):
        SKILL_REGISTRY[name] = fn
        return fn
    return decorator


async def dispatch_skill(skill_name: str, args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Dispatch execution to registered skill handler or return fallback response."""
    if skill_name in SKILL_REGISTRY:
        return await SKILL_REGISTRY[skill_name](args, pool)
    raise ValueError(f"Skill '{skill_name}' is not registered in SKILL_REGISTRY.")
