from __future__ import annotations

from typing import Collection, Sequence

MAX_NUDGES = 1

PERMISSION_PHRASES: tuple[str, ...] = (
    "would you like me to",
    "do you want me to",
    "want me to",
    "shall i",
    "should i go ahead",
    "should i proceed",
    "please confirm",
    "confirm or let me know",
    "let me know if you'd like",
    "let me know if you would like",
    "go ahead and",
    "before i make",
    "before i change",
    "before i update",
)

CHANGE_VERBS: tuple[str, ...] = (
    "update",
    "change",
    "move",
    "reschedule",
    "postpone",
    "push",
    "shift",
    "delete",
    "remove",
    "add",
    "create",
    "mark",
    "edit",
    "set the due",
    "new due date",
)

NUDGE_MESSAGE = (
    "Do not ask the user for permission in text. The system already asks the user to approve every data change before it runs. "
    "Call the appropriate tool now (for example edit_task, add_task, delete_task, update_task_status, apply_triage_plan or commit_schedule) with the exact changes you proposed. "
    "If you truly need information that you cannot look up with a tool, ask one specific question instead."
)


def reply_asks_for_permission(reply: str) -> bool:
    if not isinstance(reply, str) or not reply:
        return False
    lowered = reply.lower()
    has_permission_phrase = any(phrase in lowered for phrase in PERMISSION_PHRASES)
    has_change_verb = any(verb in lowered for verb in CHANGE_VERBS)
    return has_permission_phrase and has_change_verb


def nudge_messages(reply: str) -> list[dict[str, str]]:
    """The two messages that send the model back to make the tool call it only described."""
    return [{"role": "assistant", "content": reply}, {"role": "user", "content": NUDGE_MESSAGE}]


def should_nudge_for_tool_call(
    reply: str,
    tools_used: Sequence[str],
    nudges_used: int,
    mutating_tools: Collection[str],
) -> bool:
    if nudges_used >= MAX_NUDGES:
        return False
    if any(tool in mutating_tools for tool in tools_used):
        return False
    return reply_asks_for_permission(reply)
