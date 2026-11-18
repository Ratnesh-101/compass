"""Remove internal-only keys from tool output before it is shown to the user.

The model still receives the full text (``tool_payload`` in agent_step_executor).
Only the user-visible observe step goes through ``redact_internal_keys``.
"""

from __future__ import annotations

import re

_INTERNAL_KEYS = ("user_id", "owner", "include_demo", "is_guest")
_KEY_ALT = "|".join(_INTERNAL_KEYS)

# "user_id": "abc", / 'user_id': 'abc', / "include_demo": false, / 'is_guest': True,
_PAIR_RE = re.compile(
    r"""\s*(["'])(?:%s)\1\s*:\s*(?:"[^"]*"|'[^']*'|[^,}\]\s]+)\s*,?""" % _KEY_ALT
)


def redact_internal_keys(text: str) -> str:
    """Return ``text`` without ``user_id``/``owner``/``include_demo``/``is_guest`` pairs."""
    if not isinstance(text, str) or not text:
        return text
    cleaned = _PAIR_RE.sub("", text)
    # A pair removed at the end of an object can leave ", }".
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned
