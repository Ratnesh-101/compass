"""
Compass - Resume parsing fixes (N-013 / T-021 parse slips).

Small pure helpers used by `parse_uploaded_resume_text` so that:

- a status note such as "(currently in 3rd year)" is not glued onto the college name,
- a grade written before its label ("8.4/10 CGPA") is read as well as "CGPA 8.4/10",
- a college line and its degree line ("Pune Institute of Technology" then
  "B.Tech in Computer Science 2024-2028 CGPA 8.4/10") become one education entry with its dates,
- a sentence under a project header ("used by 200 students.") stays part of that project instead of
  becoming a project of its own.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

from backend.models_career import ResumeEducationItem
from backend.services.career_profile_derive import split_education_note, stated_year_of_study

_GRADE_AFTER_LABEL = re.compile(r"(?:CGPA|GPA|CPI|Grade)[\s:]*([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)?%?)", re.IGNORECASE)
_GRADE_BEFORE_LABEL = re.compile(r"([0-9]+(?:\.[0-9]+)?(?:\s*/\s*[0-9]+(?:\.[0-9]+)?)?%?)\s*(?:CGPA|GPA|CPI)\b", re.IGNORECASE)

_INSTITUTION_TERMS = ("university", "institute", "college", "school", "academy", "iit", "nit", "iiit")


def extract_grade(line: str) -> Optional[str]:
    """Grade text from "CGPA 8.4/10" or "8.4/10 CGPA", with spaces around the slash removed."""
    m = _GRADE_AFTER_LABEL.search(line) or _GRADE_BEFORE_LABEL.search(line)
    return re.sub(r"\s+", "", m.group(1)) if m else None


def education_line_parts(line: str) -> tuple[str, Optional[str], Optional[int]]:
    """(line without the status note, the note, stated year of study) for an education line."""
    cleaned, note = split_education_note(line)
    return cleaned, note, stated_year_of_study(note, line)


def _has_institution_word(text: str) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low) for t in _INSTITUTION_TERMS)


def merge_split_education_items(items: List[ResumeEducationItem]) -> List[ResumeEducationItem]:
    """Join a college-only entry with the degree-only entry that follows it.

    The parser creates one entry per line that mentions a degree or institution word. For a resume
    that puts the college on one line and the degree with its dates on the next, the first entry has
    no degree and the second repeats its degree as the "institution". Those two are one entry.
    """
    merged: List[ResumeEducationItem] = []
    for item in items:
        prev = merged[-1] if merged else None
        degree_only = (
            prev is not None
            and not (prev.degree or "").strip()
            and _has_institution_word(prev.institution or "")
            and (item.institution or "").strip() == (item.degree or "").strip()
            and not _has_institution_word(item.institution or "")
        )
        if degree_only and prev is not None:
            prev.degree = item.degree
            prev.field_of_study = prev.field_of_study or item.field_of_study
            prev.start_year = prev.start_year or item.start_year
            prev.end_year = prev.end_year or item.end_year
            prev.cgpa_or_grade = prev.cgpa_or_grade or item.cgpa_or_grade
            continue
        merged.append(item)
    return merged


def is_description_line(
    line: str, title_separators: Iterable[str], has_dates: bool, action_verbs: Set[str]
) -> bool:
    """True when a non-bullet line under a project header is a description sentence, not a new title.

    A new project title is short, has no terminal full stop and often a separator or date range.
    A description starts in lower case ("used by 200 students."), starts with an action verb
    ("Built a web app ..."), or is a full sentence ending in a full stop.
    """
    text = line.strip()
    if not text or has_dates:
        return False
    if any(sep in text for sep in title_separators):
        return False
    first = re.split(r"[\s,;:]+", text)[0].lower()
    if text[0].islower() or first in action_verbs:
        return True
    return text.endswith(".") and len(text.split()) >= 3
