"""Give the planning agent the real task ids behind a task listing.

The text a task listing returns shows titles only, so the model had to guess the
``task_id`` for edit_task / update_task_status and proposed changes to the wrong
task ("Task #2"). The hint is appended to the model-facing tool message only.
"""
from __future__ import annotations

from typing import Any

MAX_HINT_TASKS = 25


def task_id_hint(data: Any) -> str:
    """Return a one-line ``title=id`` map for a list of task dicts, or "" when not applicable."""
    if not isinstance(data, list):
        return ""
    pairs: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        task_id = item.get("id")
        title = item.get("title")
        if task_id is None or not isinstance(title, str) or not title.strip():
            continue
        pairs.append(f"{title.strip()} = {task_id}")
        if len(pairs) >= MAX_HINT_TASKS:
            break
    if not pairs:
        return ""
    return "\n\n[Task ids to use in tool calls (task_id): " + "; ".join(pairs) + "]"
