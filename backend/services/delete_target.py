"""Normalise the target of a chat delete request ("delete my deadline").

Deterministic token handling only (no regex), so there is no backtracking risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

FILLER_WORDS = frozenset({"my", "the", "a", "an", "this", "that", "please"})
GENERIC_NOUNS = frozenset(
    {"task", "tasks", "deadline", "deadlines", "todo", "todos", "item", "items", "reminder", "reminders"}
)
_POSITION_WORDS = frozenset({"last", "latest", "newest", "most", "recent"})
_OVERDUE_WORDS = frozenset({"overdue"})
_COMPLETED_WORDS = frozenset({"completed", "done"})
_STRIP = FILLER_WORDS | GENERIC_NOUNS | _POSITION_WORDS
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


@dataclass(frozen=True)
class DeleteTarget:
    """Parsed delete target: specific title text, genericness and an optional status filter."""

    text: str
    is_generic: bool
    status_filter: Optional[str] = None


def parse_delete_target(raw: str) -> DeleteTarget:
    """Like ``normalize_delete_target`` but also understands status words.

    ``overdue`` -> ``status_filter="overdue"``; ``completed``/``done`` -> ``"completed"``.
    Status words are removed from the searched text. Numeric IDs are returned unchanged.
    """
    text = (raw or "").strip().strip("'\"").strip()[:_MAX_TARGET_CHARS]
    if text.isdigit():
        return DeleteTarget(text, False, None)
    status_filter: Optional[str] = None
    kept = []
    for tok in text.lower().split():
        if tok in _OVERDUE_WORDS:
            status_filter = status_filter or "overdue"
        elif tok in _COMPLETED_WORDS:
            status_filter = status_filter or "completed"
        elif tok not in _STRIP:
            kept.append(tok)
    if not kept:
        return DeleteTarget("", True, status_filter)
    return DeleteTarget(" ".join(kept), False, status_filter)
