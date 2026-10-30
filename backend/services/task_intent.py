"""Guards that keep questions and capability asks from becoming tasks.

A task is only created from a concrete command with a meaningful title. A message that is
question-framed ("can you add deadlines for me?") is a request for information, not a task, unless
it still carries a concrete task ("can you add a task to buy milk tomorrow?").
"""

from __future__ import annotations

import re
from typing import Optional

STATEMENT = "statement"
COMMAND = "command"
QUESTION = "question"

MAX_TITLE_LEN = 200

CAPABILITY_REPLY = (
    "Yes, I can add tasks and deadlines. I haven't added anything yet because I need the details. "
    "Tell me the task name and when it's due, for example: \"add task Submit report tomorrow 5pm\". "
    "You can also paste several tasks (a table or a list) and I'll show you a preview to confirm "
    "before anything is added."
)

TITLE_CLARIFICATION = (
    "I haven't added anything, because I couldn't find a clear task name. "
    "What should the task be called, and when is it due? "
    "For example: \"add task Submit report tomorrow 5pm\"."
)

_PRONOUN_LEAD = re.compile(
    r"^(?:can|could|would|will|do|does|did|are|is|am|may|might|should)\s+"
    r"(?:you|u|i|we|compass|it|this|that|there)\b"
)
# A title that is itself addressed to the assistant ("Can you deadlines for me"), not "Do it by Friday".
_TITLE_QUESTION_LEAD = re.compile(r"^(?:(?:can|could|would|will)\s+(?:you|u)|(?:do|does|are|is)\s+(?:you|compass))\b")
_WH_LEAD = re.compile(r"^(?:what|what's|whats|how|why|when|where|who|which)\b")
_POLITE_PREFIX = re.compile(
    r"^(?:(?:hey|hi|ok|okay)[,!]?\s+)?(?:(?:can|could|would|will)\s+(?:you|u)\s+(?:please\s+)?|please\s+)",
    re.IGNORECASE,
)
_CREATION_PHRASE = re.compile(
    r"\b(?:add(?:ing)?|creat(?:e|ing)|mak(?:e|ing)|sett?(?:ing)?|schedul(?:e|ing)|put(?:ting)?|track(?:ing)?|remind(?:ing)?)\b"
    r".*\b(?:tasks?|todos?|to-dos?|deadlines?|reminders?)\b",
    re.IGNORECASE | re.DOTALL,
)

# Words that, on their own, are not a task name.
_FILLER_WORDS = frozenset({
    "task", "tasks", "todo", "todos", "deadline", "deadlines", "reminder", "reminders", "me", "you",
    "for", "a", "an", "the", "please", "add", "create", "new", "set", "my", "to", "it", "this",
    "that", "some", "any", "of", "on", "in", "at", "by", "can", "could", "would", "will", "i",
})


def is_question_framed(message: str) -> bool:
    """True when the message reads as a question: trailing '?' or an interrogative lead."""
    msg = (message or "").strip().lower()
    if not msg:
        return False
    return msg.endswith("?") or bool(_PRONOUN_LEAD.match(msg) or _WH_LEAD.match(msg))


def mentions_task_creation(message: str) -> bool:
    """True when the message talks about adding/creating/scheduling tasks or deadlines."""
    return bool(_CREATION_PHRASE.search(message or ""))


def has_explicit_task_phrase(message: str) -> bool:
    """The user literally asked to add/remind/schedule something, as opposed to the model inferring it."""
    return mentions_task_creation(message) or bool(re.search(r"\bremind me\b", message or "", re.IGNORECASE))


def strict_command_title(message: str) -> str:
    """Title captured from what follows the creation phrase; '' when there is none."""
    from backend.router_helpers import _extract_task_creation_args

    text = _POLITE_PREFIX.sub("", (message or "").strip().rstrip("?").strip())
    return _extract_task_creation_args(text).get("title", "") or ""


def title_problem(title: Optional[str]) -> Optional[str]:
    """Why a title cannot be used (None when it is a meaningful task name)."""
    clean = (title or "").strip()
    if not clean:
        return "empty"
    if len(clean) > MAX_TITLE_LEN:
        return "too_long"
    if "?" in clean or _TITLE_QUESTION_LEAD.match(clean.lower()):
        return "question_like"
    words = re.findall(r"[A-Za-z0-9']+", clean.lower())
    if not any(re.search(r"[A-Za-z]", w) for w in words):
        return "no_words"
    if all(w in _FILLER_WORDS for w in words):
        return "filler_only"
    return None


def classify_task_message(message: str) -> str:
    """STATEMENT (not a question), COMMAND (question-framed but concrete) or QUESTION."""
    if not is_question_framed(message):
        return STATEMENT
    return COMMAND if title_problem(strict_command_title(message)) is None else QUESTION


def blocks_task_creation(message: str) -> bool:
    """True when a message must not create a task: it is a question without a concrete task."""
    return classify_task_message(message) == QUESTION


def is_capability_question(message: str) -> bool:
    """A question about adding tasks/deadlines (answered conversationally, never executed)."""
    return blocks_task_creation(message) and mentions_task_creation(message)


def is_intake_intent(message: str) -> bool:
    """Messages handled deterministically before any model call: pasted task lists or capability asks."""
    from backend.services.task_intake_llm import looks_like_prose_task_list
    from backend.services.task_intake_parse import parse_task_list

    return (
        is_capability_question(message)
        or parse_task_list(message) is not None
        or looks_like_prose_task_list(message)
    )
