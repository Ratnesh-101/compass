"""
Compass — Radar profile text parsing helpers.

Pure, regex-light parsers that turn free-text resume fields (grade strings, locations,
education lists) into profile facts. When the text is ambiguous they return None (unknown)
instead of guessing, so a bad resume string can never invent or break an eligibility fact.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

_GRADE_LABELS = {"cgpa", "gpa", "cpi", "sgpa"}
_RANK_WORDS = {"top", "rank", "ranked", "percentile"}
_MIN_SCALE = 4.0
_MAX_SCALE = 100.0
_DEFAULT_SCALE = 10.0

_US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
    "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)


def _scan_numbers(text: str) -> List[Tuple[float, int, int]]:
    """Standalone decimal numbers as (value, start, end); numbers glued to letters are skipped."""
    found: List[Tuple[float, int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if not text[i].isdigit():
            i += 1
            continue
        j = i
        seen_dot = False
        while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot and j + 1 < n and text[j + 1].isdigit())):
            seen_dot = seen_dot or text[j] == "."
            j += 1
        glued = (i > 0 and text[i - 1].isalpha()) or (j < n and text[j].isalpha())
        if not glued:
            found.append((float(text[i:j]), i, j))
        i = j
    return found


def _next_non_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] == " ":
        pos += 1
    return pos


def parse_grade(grade_str: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Return (value, scale) for a resume grade string, or (None, None) when unclear/invalid."""
    if not grade_str:
        return None, None
    text = str(grade_str).strip().lower()[:80]
    words = set(re.findall(r"[a-z]+", text))
    if words & _RANK_WORDS:
        return None, None
    labelled = bool(words & _GRADE_LABELS)
    numbers = _scan_numbers(text)
    for idx, (value, _, end) in enumerate(numbers):
        after = _next_non_space(text, end)
        if after < len(text) and text[after] == "%":
            return (value, 100.0) if 0 < value <= 100 else (None, None)
        if after < len(text) and text[after] == "/":
            nxt = next((m for m in numbers[idx + 1:] if m[1] == _next_non_space(text, after + 1)), None)
            if nxt is None:
                continue
            scale = nxt[0]
            if _MIN_SCALE <= scale <= _MAX_SCALE and 0 <= value <= scale:
                return value, scale
            return None, None
        if labelled:
            return (value, _DEFAULT_SCALE) if 0 <= value <= _DEFAULT_SCALE else (None, None)
    return None, None


def derive_country(location: Optional[str]) -> Optional[str]:
    """Whole-word country cue from a resume location; None when it is not clearly stated."""
    if not location:
        return None
    raw = str(location)
    words = set(re.findall(r"[a-z]+", raw.lower()))
    if "india" in words:
        return "India"
    if "usa" in words or "us" in words or {"united", "states"} <= words:
        return "USA"
    upper_tokens = set(re.findall(r"\b[A-Z]{2}\b", raw))
    if upper_tokens & _US_STATE_CODES:
        return "USA"
    return None


def _end_year(entry: Any) -> Optional[int]:
    value = entry.get("end_year") if isinstance(entry, dict) else getattr(entry, "end_year", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def latest_education(edu_list: List[Any]) -> Any:
    """Entry with the greatest end_year; the first entry when no entry has a year."""
    if not edu_list:
        return None
    dated = [(y, e) for e in edu_list if (y := _end_year(e)) is not None]
    return max(dated, key=lambda pair: pair[0])[1] if dated else edu_list[0]
