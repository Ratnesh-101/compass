"""
Compass — Resume content merge.

Committing an import must never erase data the candidate already has: a partial import (for
example links only) only replaces the fields it actually carries.
"""
from __future__ import annotations

from typing import Any, Dict

from backend.models_career import ResumeContent


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def merge_resume_content(existing: ResumeContent, incoming: ResumeContent) -> ResumeContent:
    """Return a new ResumeContent: incoming non-empty fields win, empty ones keep `existing`.

    Dict fields (evidence classifications/notes) are merged key by key with incoming winning.
    Neither input is mutated.
    """
    existing_data: Dict[str, Any] = existing.model_dump()
    incoming_data: Dict[str, Any] = incoming.model_dump()
    merged: Dict[str, Any] = {}
    for field, current in existing_data.items():
        new_value = incoming_data.get(field)
        if isinstance(current, dict) and isinstance(new_value, dict):
            merged[field] = {**current, **new_value}
        elif _is_empty(new_value):
            merged[field] = current
        else:
            merged[field] = new_value
    return ResumeContent.model_validate(merged)
