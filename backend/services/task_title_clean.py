"""Clean task titles of leftover date, priority and domain fragments (T-014 fallback title bug).

"Submit audit report by friday, high priority, hackathon domain" must become "Submit audit report"
(priority high, domain hackathon), never "Submit audit report by , high priority, hackathon domain".
"""

from __future__ import annotations

import re
from typing import Optional

_LEVELS = "low|medium|normal|high|urgent|critical"
_DOMAINS = "hackathon|coursework|code|general"
_LEVEL_CANON = {"low": "low", "medium": "medium", "normal": "medium", "high": "high", "urgent": "urgent", "critical": "urgent"}

_PRIORITY_FRAGMENT = re.compile(
    rf"[,;]?\s*\b(?:with\s+)?(?:(?:{_LEVELS})\s+priority|priority\s*[:=]?\s*(?:{_LEVELS}))\b",
    re.IGNORECASE,
)
_DOMAIN_FRAGMENT = re.compile(
    rf"[,;]?\s*\b(?:in\s+(?:the\s+)?)?(?:domain\s*[:=]?\s*(?:{_DOMAINS})|(?:{_DOMAINS})\s+domain)\b",
    re.IGNORECASE,
)
_PRIORITY_VALUE = re.compile(rf"\b(?:({_LEVELS})\s+priority|priority\s*[:=]?\s*({_LEVELS}))\b", re.IGNORECASE)
# "in" is deliberately absent: "Sign in", "Log in", "Check in" are complete titles (phrasal verbs).
_CONNECTORS = r"(?:by|on|at|due|before|until|for|with|and|to|from)"
_DANGLING_BEFORE_PUNCT = re.compile(r"\b(?:by|on|at|due|before|until)\s*(?=[,;]|$)", re.IGNORECASE)
_TRAILING_CONNECTOR = re.compile(rf"(?:\s+|^){_CONNECTORS}\s*$", re.IGNORECASE)
_EDGE_PUNCT = " .!?:;,-\u2013\u2014'\""


def extract_priority(text: str) -> Optional[str]:
    """Priority the user stated in words ("high priority", "priority: urgent"); None if not stated."""
    m = _PRIORITY_VALUE.search(text or "")
    if not m:
        return None
    return _LEVEL_CANON.get((m.group(1) or m.group(2)).lower())


def strip_priority_domain_fragments(text: str) -> str:
    """Remove "high priority" / "priority: low" / "hackathon domain" / "domain=code" phrases."""
    out = _PRIORITY_FRAGMENT.sub("", text or "")
    return _DOMAIN_FRAGMENT.sub("", out)


def tidy_title(text: str) -> str:
    """Remove dangling connectors ("by ,", trailing "by"), doubled commas and edge punctuation."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = _DANGLING_BEFORE_PUNCT.sub("", t)
    t = re.sub(r"\s+([,;])", r"\1", t)
    t = re.sub(r"([,;])(?:\s*[,;])+", r"\1", t)
    t = t.strip(_EDGE_PUNCT)
    while True:
        shorter = _TRAILING_CONNECTOR.sub("", t).strip(_EDGE_PUNCT)
        if shorter == t:
            break
        t = shorter
    return re.sub(r"\s+", " ", t).strip()


def clean_title(text: str) -> str:
    """Fragments stripped and the remainder tidied."""
    return tidy_title(strip_priority_domain_fragments(text))
