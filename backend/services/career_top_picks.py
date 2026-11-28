"""Relevance filter for "Prepare my top 3 matches".

Takes the already ranked recommendations (fresh, verified, India first) and keeps only the listings that fit
the candidate's skills. Pure functions: no network, no database.
"""
from __future__ import annotations

import re
from typing import Any, List, Sequence

_NON_TECHNICAL_WORDS = (
    "hr", "human resources", "talent acquisition", "recruiter", "recruitment", "recruiting", "payroll",
    "sales", "finance", "accounts", "accounting", "content", "copywriter", "marketing", "business development",
)
_TECHNICAL_TITLE_WORDS = (
    "engineer", "developer", "software", "backend", "frontend", "full stack", "full-stack", "devops", "sde",
    "ml", "ai", "machine learning", "data", "python", "react", "web", "cloud", "security", "research",
)


def _has_word(text: str, term: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def _skill_terms(skills: Sequence[str]) -> List[str]:
    """Individual skill names; a labelled list such as 'Languages: Python, Java' is split."""
    terms: List[str] = []
    for raw in skills:
        if not isinstance(raw, str):
            continue
        body = raw.split(":", 1)[-1]
        for part in re.split(r"[,;/|]", body):
            term = part.strip().lower()
            if len(term) >= 2 and term not in terms:
                terms.append(term)
    return terms


def relevance_score(opp: Any, skills: Sequence[str]) -> int:
    """Higher is better. Zero or less means the listing does not fit this profile."""
    title = (getattr(opp, "role_title", "") or "").lower()
    text = f"{title} {(getattr(opp, 'description', '') or '').lower()}"
    terms = _skill_terms(skills)
    overlap_title = sum(1 for t in terms if _has_word(title, t))
    overlap_text = sum(1 for t in terms if _has_word(text, t))
    score = overlap_title * 3 + overlap_text
    if any(_has_word(title, w) for w in _TECHNICAL_TITLE_WORDS):
        score += 2
    if terms and any(_has_word(title, w) for w in _NON_TECHNICAL_WORDS):
        score -= 10  # clearly non-technical role for a technical profile
    return score


def select_relevant(ranked: Sequence[Any], skills: Sequence[str]) -> List[Any]:
    """Relevant listings only, in `ranked` order (fresh, verified, India first)."""
    return [o for o in ranked if relevance_score(o, skills) > 0]


def only_n_message(count: int, limit: int) -> str:
    return f"Only {count} listings matched your profile" if count < limit else ""
