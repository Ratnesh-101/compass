"""Small chat helpers kept out of chat_stream.py: the router-tier extra_body switch and the greeting fast path."""

import json
import logging
from typing import Any, Optional

from backend.router_helpers import is_greeting_intent

logger = logging.getLogger("compass.services.chat_fastpath")

GREETING_REPLY = (
    "Hi! I'm Compass. I can plan your week, keep track of your deadlines and help you find internships. "
    "Try \u201cPlan my week\u201d or \u201cFind internships for me\u201d."
)

_warned_extra_body = False


def parse_router_extra_body(raw: Any) -> Optional[dict]:
    """Parse the ROUTER_EXTRA_BODY setting (a JSON object string).

    Returns a dict, or None when the value is empty, invalid JSON, or not a JSON object. Never raises.
    A bad non-empty value logs one warning per process.
    """
    global _warned_extra_body
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if not _warned_extra_body:
        _warned_extra_body = True
        logger.warning("ROUTER_EXTRA_BODY is not a valid JSON object; ignoring it")
    return None


def router_extra_body(settings: Any) -> Optional[dict]:
    """The parsed ROUTER_EXTRA_BODY for a settings object (None when unset or unusable)."""
    return parse_router_extra_body(getattr(settings, "ROUTER_EXTRA_BODY", ""))


def apply_router_extra_body(call_kwargs: dict, settings: Any) -> dict:
    """Add extra_body to the router-tier chat kwargs only when the setting holds a valid JSON object."""
    extra = router_extra_body(settings)
    if extra is not None:
        call_kwargs["extra_body"] = extra
    return call_kwargs


def is_greeting_fastpath(req: Any, message: str) -> bool:
    """True for a pure greeting in a plain chat turn (no continue, specialist, edit target or empty text)."""
    if not message or not message.strip():
        return False
    if getattr(req, "continue_message_id", None):
        return False
    get_spec = getattr(req, "get_specialist_id", None)
    if (get_spec() if callable(get_spec) else getattr(req, "specialist_id", None)):
        return False
    if getattr(req, "target_message_id", None):
        return False
    return is_greeting_intent(message)
