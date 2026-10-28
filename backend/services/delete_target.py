"""Normalise the target of a chat delete request ("delete my deadline").

Deterministic token handling only (no regex), so there is no backtracking risk.
"""

from __future__ import annotations

from typing import Tuple

FILLER_WORDS = frozenset({"my", "the", "a", "an", "this", "that", "please"})
GENERIC_NOUNS = frozenset(
    {"task", "tasks", "deadline", "deadlines", "todo", "todos", "item", "items", "reminder", "reminders"}
)
_STRIP = FILLER_WORDS | GENERIC_NOUNS
_MAX_TARGET_CHARS = 200


def normalize_delete_target(raw: str) -> Tuple[str, bool]:
    """Return ``(specific_text, is_generic)`` for a raw delete target.

    ``is_generic`` is True when nothing specific is left after removing
    determiners, fillers and generic nouns (e.g. "my deadline", "the task").
    Purely numeric targets (task IDs) are returned unchanged.
    """
    text = (raw or "").strip().strip("'\"").strip()[:_MAX_TARGET_CHARS]
    if text.isdigit():
        return text, False
    kept = [tok for tok in text.lower().split() if tok not in _STRIP]
    if not kept:
        return "", True
    return " ".join(kept), False
