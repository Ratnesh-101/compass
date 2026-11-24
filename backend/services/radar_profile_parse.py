"""
Compass — Radar profile text parsing helpers.

Pure, regex-light parsers that turn free-text resume fields (grade strings, locations,
education lists) into profile facts. When the text is ambiguous they return None (unknown)
instead of guessing, so a bad resume string can never invent or break an eligibility fact.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

_GRADE_LABELS = {"cgpa", "gpa", "cpi", "sgpa", "percentage", "percent"}
_RANK_WORDS = {"top", "rank", "ranked", "percentile"}
_MIN_SCALE = 4.0
_MAX_SCALE = 100.0
_DEFAULT_SCALE = 10.0

_US_STATE_CODES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
    "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)

_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "final": 4, "pre-final": 3, "prefinal": 3
}


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
            return (value, 100.0) if 0 <= value <= 100 else (None, None)
        if after < len(text) and text[after] == "/":
            nxt = next((m for m in numbers[idx + 1:] if m[1] == _next_non_space(text, after + 1)), None)
            if nxt is None:
                continue
            scale = nxt[0]
            if _MIN_SCALE <= scale <= _MAX_SCALE and 0 <= value <= scale:
                return value, scale
            return None, None
        if labelled:
            if words & {"percentage", "percent"}:
                return (value, 100.0) if 0 <= value <= 100.0 else (None, None)
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


def parse_academic_year(
    text: Optional[str],
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Optional[int]:
    """Derive academic year (1-6) from resume text, semester or date range."""
    if not text:
        return None
    t = str(text)[:2000]
    m_num = re.search(r"\b([1-6])\s*(?:st|nd|rd|th)\s*year\b", t, re.IGNORECASE)
    if m_num:
        return int(m_num.group(1))
    m_word = re.search(r"\b(first|second|third|fourth|fifth|final|pre-?final)\s*year\b", t, re.IGNORECASE)
    if m_word:
        return _ORDINAL_WORDS.get(m_word.group(1).lower().replace("-", ""))
    m_yr = re.search(r"\byear\s*([1-6])\b(?!\s*[-/]\s*\d)", t, re.IGNORECASE)
    if m_yr:
        return int(m_yr.group(1))
    m_sem = re.search(r"\b(?:sem(?:ester)?)\s*([1-8]|1[0-2])\b", t, re.IGNORECASE)
    if m_sem:
        sem = int(m_sem.group(1))
        return (sem + 1) // 2
    if start_year:
        today = today or date.today()
        cur_year = today.year
        if end_year and end_year > cur_year and start_year <= cur_year:
            calc = cur_year - start_year + 1
            if 1 <= calc <= 6:
                return calc
    return None


def parse_graduation_year(text: Optional[str]) -> Optional[int]:
    """Derive graduation year from education lines or cues."""
    if not text:
        return None
    t = str(text)[:2000]
    cue_match = re.search(
        r"\b(?:expected\s+graduation|graduating|class\s+of|expected)[\s:]*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]*)?(20\d\d)\b",
        t,
        re.IGNORECASE,
    )
    if cue_match:
        return int(cue_match.group(1))
    rng_match = re.search(r"\b(?:19|20)\d\d\s{0,5}[-–—~]\s{0,5}(20\d\d)\b", t)
    if rng_match:
        return int(rng_match.group(1))
    years = re.findall(r"\b(20\d\d)\b", t)
    return int(years[-1]) if years else None


def format_degree(degree: Optional[str], specialization: Optional[str] = None) -> str:
    """Format degree text without appending specialization when degree already contains it."""
    deg = (degree or "").strip()
    spec = (specialization or "").strip()
    if not deg:
        return spec
    if not spec or spec.lower() in deg.lower():
        return deg
    return f"{deg} in {spec}"


def derive_profile_facts(content: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Derive academic_year, graduation_year, cgpa, education start/end years, skills, and degree string."""
    today = today or date.today()
    if isinstance(content, dict) and "content" in content and isinstance(content["content"], (dict, object)):
        content = content["content"]

    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    edu_list = list(_get(content, "education", []) or [])
    skills_raw = list(_get(content, "skills", []) or [])
    notes = _get(content, "evidence_notes", {}) or {}

    edu = latest_education(edu_list)
    degree = _get(edu, "degree") if edu else None
    specialization = _get(edu, "field_of_study") if edu else None
    start_year = _get(edu, "start_year") if edu else None
    end_year = _get(edu, "end_year") if edu else None
    grade_str = _get(edu, "cgpa_or_grade") if edu else None

    cgpa, cgpa_scale = parse_grade(str(grade_str)) if grade_str else (None, None)

    note_text = " ".join(str(v) for k, v in notes.items() if str(k).startswith("education")) if isinstance(notes, dict) else ""
    full_text = " ".join(str(x) for x in [note_text, degree, _get(edu, "institution") if edu else None] if x)

    academic_year = parse_academic_year(full_text, start_year, end_year, today)
    if academic_year is None and start_year and end_year:
        session_start = today.year if today.month >= 7 else today.year - 1
        calc = session_start - end_year + (end_year - start_year) + 1
        if 1 <= calc <= 6:
            academic_year = calc

    grad_year = end_year or (parse_graduation_year(full_text) if full_text else None)
    degree_str = format_degree(degree, specialization)

    return {
        "academic_year": academic_year,
        "graduation_year": grad_year,
        "cgpa": cgpa,
        "cgpa_scale": cgpa_scale,
        "start_year": start_year,
        "end_year": end_year,
        "skills": [s for s in skills_raw if isinstance(s, str)],
        "degree_string": degree_str,
    }
