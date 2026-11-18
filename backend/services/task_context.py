"""Keep the user's context in task names and domains for prose task lists (T-014 / N-025).

"arrays tomorrow, linked lists on thursday and trees on friday for my data structures exam" should
produce "Study arrays - Data Structures exam" with domain coursework, not a bare "arrays" in
"general". Conservative on purpose: nothing is added unless the message names the context itself.
"""

from __future__ import annotations

import re
from typing import Optional

_STUDY_KINDS = frozenset({"exam", "test", "quiz", "midterm", "final"})
_CONTEXT_RX = re.compile(
    r"\b(?:for|about|towards)\s+(?:(?:my|the|our|a|an)\s+)?([a-z][a-z0-9 &/+'-]{1,40}?)\s+"
    r"(exam|test|quiz|midterm|final|class|course|assignment|lab)\b",
    re.IGNORECASE,
)
_ARTICLES = frozenset({"my", "the", "our", "a", "an", "this", "that", "next", "last", "your"})
_COURSE_WORDS = re.compile(r"\b(?:exams?|quiz(?:zes)?|midterms?|homework|assignments?|lectures?|coursework|syllabus)\b", re.IGNORECASE)
_ACTION_VERBS = frozenset({
    "study", "finish", "write", "submit", "review", "read", "practice", "revise", "complete", "prepare",
    "do", "build", "fix", "call", "buy", "email", "send", "learn", "solve", "watch", "make", "plan",
})
_MAX_BARE_WORDS = 4
# Words that cannot sit inside a course name: they mean "for ..." and the exam/class noun are unrelated clauses
# ("call mom for dinner after the assignment").
_NOT_IN_COURSE_NAME = frozenset({
    "after", "before", "and", "or", "then", "but", "so", "to", "from", "at", "on", "in", "with", "by",
    "when", "while", "until", "tomorrow", "today", "tonight", "dinner", "lunch", "breakfast",
})


def find_context(message: str) -> Optional[tuple[str, str]]:
    """('Data Structures', 'exam') from "... for my data structures exam", or None."""
    for m in _CONTEXT_RX.finditer(message or ""):
        words = m.group(1).split()
        if not words or all(w.lower() in _ARTICLES for w in words):
            continue
        if any(w.lower() in _NOT_IN_COURSE_NAME for w in words):
            continue
        while words and words[0].lower() in _ARTICLES:
            words.pop(0)
        return " ".join(w if w.isupper() else w.capitalize() for w in words), m.group(2).lower()
    return None


def enrich_title(title: str, message: str) -> str:
    """Append the stated context to a bare topic name; titles that already carry it are unchanged."""
    ctx = find_context(message)
    clean = (title or "").strip()
    if not ctx or not clean:
        return clean
    label, kind = ctx
    if label.lower() in clean.lower():
        return clean
    words = clean.split()
    first = words[0].lower()
    if first in _ACTION_VERBS:
        return f"{clean[0].upper()}{clean[1:]} - {label} {kind}"
    if len(words) <= _MAX_BARE_WORDS:
        prefix = "Study " if kind in _STUDY_KINDS else ""
        topic = f"{clean[0].lower()}{clean[1:]}" if prefix else f"{clean[0].upper()}{clean[1:]}"
        return f"{prefix}{topic} - {label} {kind}"
    return clean


def infer_domain(domain: str, message: str) -> str:
    """Upgrade an unspecified ("general") domain to coursework when the message is plainly about class work."""
    if domain != "general":
        return domain
    return "coursework" if _COURSE_WORDS.search(message or "") or find_context(message) else domain
