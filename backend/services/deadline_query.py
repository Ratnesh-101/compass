"""Search query for verifying a stored deadline against live web sources.

Searching the raw task title ("Nebius submission draft") surfaced unrelated events and
produced a wrong drift date. The query now names the event (the project when it has a
real name), drops generic task words, and asks for the official rules page.
"""
from __future__ import annotations

from typing import Optional

GENERIC_TAIL_WORDS = frozenset({
    "submission", "submissions", "submit", "draft", "deadline", "due", "final", "finalize", "date",
})
PLACEHOLDER_PROJECTS = frozenset({"", "general", "none", "default", "other"})


def _strip_generic_tail(subject: str) -> str:
    words = subject.split()
    while len(words) > 1 and words[-1].lower().strip(".,:;") in GENERIC_TAIL_WORDS:
        words.pop()
    return " ".join(words)


def event_subject(title: str, project: Optional[str]) -> str:
    """Prefer a real project name over the task title; strip trailing generic task words."""
    project_name = (project or "").strip()
    chosen = project_name if project_name.lower() not in PLACEHOLDER_PROJECTS else (title or "").strip()
    return _strip_generic_tail(" ".join(chosen.split()))


def build_deadline_query(title: str, project: Optional[str], domain: Optional[str]) -> str:
    subject = event_subject(title, project)
    if (domain or "").strip().lower() == "hackathon":
        return f"{subject} Devpost official rules submission period deadline"
    return f"{subject} official deadline date"
