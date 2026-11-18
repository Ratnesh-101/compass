"""
Compass - Fill the candidate (radar) profile from a committed resume.

The radar profile already copies degree, university, graduation year, CGPA and skills from the
master resume (backend.memory.radar.derive_profile_from_master_resume). It cannot know the year of
study, the country when the location line has no country word, or the target tracks. This module
derives those from facts the resume states, never from guesses:

- year of study: an explicit phrase ("currently in 3rd year", "Third Year") wins; otherwise it is
  computed from the education start/end years and today's date (a 2024-2028 degree seen in
  November 2026 is year 3).
- country: a country word in the location, a +91 phone prefix, or a well-known Indian city.
- tracks: only from skills and project text the resume lists, and only when the user has not
  picked tracks yet.

Everything is pure except `enrich_radar_profile_from_resume`, which writes through the existing
radar memory functions.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from backend.services.radar_profile_parse import derive_country, latest_education

logger = logging.getLogger("compass.services.career_profile_derive")

_ORDINAL_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "final": 4, "pre-final": 3, "prefinal": 3}

_STATED_YEAR_PATTERNS = (
    re.compile(r"\b([1-5])\s*(?:st|nd|rd|th)[\s-]*year\b", re.IGNORECASE),
    re.compile(r"\b(first|second|third|fourth|fifth|final|pre-?final)[\s-]*year\b", re.IGNORECASE),
    re.compile(r"\byear\s*([1-5])\b(?!\s*[-/]\s*\d)", re.IGNORECASE),
)

_NOTE_RE = re.compile(
    r"\(([^)]*\b(?:currently|pursuing|expected|ongoing|year|semester|sem)\b[^)]*)\)", re.IGNORECASE
)

_INDIAN_CITIES = frozenset(
    "pune mumbai delhi bengaluru bangalore hyderabad chennai kolkata ahmedabad noida gurgaon gurugram "
    "jaipur lucknow indore bhopal chandigarh kochi coimbatore nagpur surat vadodara patna".split()
)

# Tracks must match the option labels of the Candidate Profile form (RadarProfileModal ROLE_OPTIONS).
TRACK_AI_ML = "Artificial Intelligence and Machine Learning"
TRACK_GENAI = "Generative AI and LLM Engineering"
TRACK_SWE = "Software Engineering"
TRACK_BACKEND = "Backend Engineering"
TRACK_DATA = "Data Science & Analytics"
TRACK_CLOUD = "Cloud and Infrastructure Engineering"

_TRACK_KEYWORDS = (
    (TRACK_GENAI, ("llm", "langchain", "openai", "rag", "transformers", "generative ai", "gpt", "prompt")),
    (TRACK_AI_ML, ("pytorch", "tensorflow", "machine learning", "deep learning", "scikit", "sklearn", "keras", "nlp", "computer vision")),
    (TRACK_DATA, ("pandas", "numpy", "tableau", "power bi", "data analysis", "data science", "matplotlib")),
    (TRACK_BACKEND, ("fastapi", "django", "flask", "node.js", "nodejs", "express", "spring", "postgresql", "mongodb", "sql", "rest api")),
    (TRACK_CLOUD, ("aws", "azure", "gcp", "docker", "kubernetes", "terraform", "devops", "linux")),
    (TRACK_SWE, ("python", "java", "c++", "javascript", "typescript", "react", "golang", "rust", "c#")),
)
MAX_TRACKS = 4


def stated_year_of_study(*texts: Optional[str]) -> Optional[int]:
    """Year of study (1-5) that the text explicitly states, or None.

    Handles "currently in 3rd year", "(Third Year)", "Year 3". A range such as "Year 2024-2028" is
    not a year of study.
    """
    for text in texts:
        if not text:
            continue
        for pattern in _STATED_YEAR_PATTERNS:
            m = pattern.search(str(text))
            if not m:
                continue
            raw = m.group(1).lower()
            value = int(raw) if raw.isdigit() else _ORDINAL_WORDS.get(raw.replace(" ", ""))
            if value and 1 <= value <= 5:
                return value
    return None


def academic_year_from_dates(
    start_year: Optional[int], end_year: Optional[int], today: Optional[date] = None
) -> Optional[int]:
    """Year of study (1-5) from the degree's start/end years and today's date.

    The academic session is taken to start in July. Only the end year is required: without a start
    year a four-year programme is assumed (the common B.Tech/B.E. length), which is returned only
    when the result is a plausible year 1-4. Returns None when the student has already graduated or
    has not started yet, so nothing wrong is ever filled in.
    """
    if not end_year:
        return None
    today = today or date.today()
    session_start = today.year if today.month >= 7 else today.year - 1
    length = 4
    if start_year and 2 <= end_year - start_year <= 5:
        length = end_year - start_year
    year = session_start - end_year + length + 1
    return year if 1 <= year <= min(length, 5) else None


_YEAR = r"(?<!\d)(20\d\d)(?!\d)"
# "Expected (2028)", "Expected 2028", "Class of 2028", "graduating May 2028", "batch of 2028", "till 2028".
_GRAD_CUE_RE = re.compile(
    r"\b(?:expected|exp\.?|class\s+of|batch(?:\s+of)?|graduat\w*|passing\s+out|until|till|to)"
    r"[\s:()\[\],.-]{0,8}(?:[A-Za-z]{3,9}\.?[\s,]+)?" + _YEAR,
    re.IGNORECASE,
)
# "2024 - 2028", "2024-28", "2024 to 2028".
_YEAR_RANGE_RE = re.compile(_YEAR + r"\s*(?:[-\u2013\u2014~/]|to)\s*(20\d\d|\d{2})(?!\d)", re.IGNORECASE)
_ANY_YEAR_RE = re.compile(_YEAR)


def extract_education_years(*texts: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """(start_year, graduation_year) stated in education text, either may be None.

    Reads "Expected (2028)", "Expected 2028", "Class of 2028", "2024 - 2028", "2024-28" and a bare
    "May 2028". A graduation cue ("expected", "class of", ...) wins over other years in the text; a
    range gives start and end; otherwise the last year mentioned is the graduation year.
    """
    text = " ".join(str(t) for t in texts if t)
    if not text.strip():
        return None, None
    start: Optional[int] = None
    end: Optional[int] = None
    rng = None
    for rng in _YEAR_RANGE_RE.finditer(text):
        pass  # keep the last range
    if rng is not None:
        first = int(rng.group(1))
        raw_end = rng.group(2)
        last = int(raw_end) if len(raw_end) == 4 else 2000 + int(raw_end)
        if last >= first:
            start, end = first, last
    cue = None
    for cue in _GRAD_CUE_RE.finditer(text):
        pass  # keep the last cue
    if cue is not None:
        end = int(cue.group(1))
    if end is None:
        years = [int(y) for y in _ANY_YEAR_RE.findall(text)]
        end = years[-1] if years else None
    if start is not None and end is not None and start >= end:
        start = None
    return start, end


def split_education_note(text: Optional[str]) -> tuple[str, Optional[str]]:
    """Split "Pune Institute of Technology, (currently in 3rd year)" into (institution, note).

    A parenthesised note about status or year is removed from the name and returned separately.
    Plain parentheses that are part of a name (for example "(Autonomous)") stay.
    """
    raw = (text or "").strip()
    notes: List[str] = []

    def _grab(m: re.Match[str]) -> str:
        notes.append(m.group(1).strip())
        return " "

    cleaned = _NOTE_RE.sub(_grab, raw)
    bare = re.search(r"[,;-]\s*(currently\s+in\s+[^,;()]+|pursuing[^,;()]*)\s*$", cleaned, re.IGNORECASE)
    if bare:
        notes.append(bare.group(1).strip())
        cleaned = cleaned[: bare.start()]
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;-")
    return cleaned, ("; ".join(notes) if notes else None)


def infer_country(location: Optional[str], phone: Optional[str]) -> Optional[str]:
    """Country the resume clearly states: a country word, a +91 phone prefix or a major Indian city."""
    named = derive_country(location)
    if named:
        return named
    if phone and re.match(r"\s*\+?\s*91[\s-]?\d", str(phone)):
        return "India"
    words = set(re.findall(r"[a-z]+", (location or "").lower()))
    if words & _INDIAN_CITIES:
        return "India"
    return None


def derive_tracks(skills: List[str], project_text: str = "") -> List[str]:
    """Up to MAX_TRACKS profile tracks supported by skills the resume lists."""
    haystack = " ".join([*(s.lower() for s in skills or []), (project_text or "").lower()])
    padded = f" {haystack} "
    tracks: List[str] = []
    for track, words in _TRACK_KEYWORDS:
        for w in words:
            hit = (f" {w} " in padded) if len(w) <= 3 else (w in haystack)
            if hit:
                tracks.append(track)
                break
        if len(tracks) >= MAX_TRACKS:
            break
    return tracks


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


_SCHOOL_RE = re.compile(
    r"\bclass\s*(?:x|xi|xii|10|11|12)(?:th)?\b|\b(?:10|12)th\b|\bschool\b(?!\s+of\b)|\bdps\b|\bhsc\b|\bssc\b"
    r"|\bcbse\b|\bicse\b|\b(?:senior\s+)?(?:higher\s+)?secondary\b|\bintermediate\b",
    re.IGNORECASE,
)


def _is_school_entry(edu: Any) -> bool:
    """True for a high-school entry (Class X / XII, school, DPS, ...)."""
    text = " ".join(str(_get(edu, k) or "") for k in ("institution", "degree", "field_of_study"))
    return bool(_SCHOOL_RE.search(text))


def _entry_years(edu: Any, note_text: str = "") -> tuple[Optional[int], Optional[int]]:
    """(start, end) of one education entry: parsed years first, else read from its text."""
    start, end = _get(edu, "start_year"), _get(edu, "end_year")
    if not end:
        text_start, text_end = extract_education_years(
            _get(edu, "institution"), _get(edu, "degree"), _get(edu, "field_of_study"), note_text
        )
        end = text_end
        start = start or text_start
    return (int(start) if start else None), (int(end) if end else None)


def pick_education(edu_list: List[Any], today: Optional[date] = None, note_text: str = "") -> Any:
    """The education entry that describes the candidate's current degree.

    High-school entries are skipped (unless nothing else is listed). Among entries still in
    progress (end year this year or later) the one listed first wins, because resumes list the
    main degree first. With none in progress, the entry with the most recent end year wins.
    """
    if not edu_list:
        return None
    today = today or date.today()
    pool = [e for e in edu_list if not _is_school_entry(e)] or list(edu_list)
    dated = [(e, _entry_years(e, note_text)[1]) for e in pool]
    in_progress = [e for e, end in dated if end is not None and end >= today.year]
    if in_progress:
        return in_progress[0]
    past = [(e, end) for e, end in dated if end is not None]
    if past:
        return max(past, key=lambda pair: pair[1])[0]
    return latest_education(pool)


def resume_facts(content: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Facts the profile form needs, taken from resume content (ResumeContent or dict)."""
    edu_list = list(_get(content, "education", []) or [])
    notes = _get(content, "evidence_notes", {}) or {}
    note_text = " ".join(str(v) for k, v in notes.items() if str(k).startswith("education"))
    edu = pick_education(edu_list, today, note_text if len(edu_list) == 1 else "")
    stated = None
    start = end = None
    if edu is not None:
        stated = stated_year_of_study(
            note_text, _get(edu, "institution"), _get(edu, "degree"), _get(edu, "field_of_study")
        )
        # The parser can miss a year written as "Expected (2028)" or "Class of 2028"; read it from the text.
        start, end = _entry_years(edu, note_text)
    grad_year = int(end) if end and 2024 <= int(end) <= 2035 else None  # the profile accepts only this range
    academic_year = stated or academic_year_from_dates(start, end, today)
    skills = [s for s in (_get(content, "skills", []) or []) if isinstance(s, str)]
    project_text = " ".join(
        f"{_get(p, 'title', '')} {_get(p, 'description', '')}" for p in (_get(content, "projects", []) or [])
    )
    return {
        "academic_year": academic_year,
        "academic_year_source": "stated" if stated else ("computed" if academic_year else None),
        "grad_year": grad_year,
        "country": infer_country(_get(content, "location"), _get(content, "phone")),
        "tracks": derive_tracks(skills, project_text),
    }


async def enrich_radar_profile_from_resume(user_id: str, content: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Fill year of study, country and tracks on the saved radar profile from the resume.

    Never overwrites something the user chose: a year of study the user set stays unless the resume
    states a year explicitly; tracks are filled only when empty. Returns what changed.
    """
    from backend.memory import radar as radar_memory

    changed: Dict[str, Any] = {}
    try:
        facts = resume_facts(content, today)
        profile = await radar_memory.get_user_opportunity_profile(user_id)
        if profile is None:
            profile = radar_memory.derive_profile_from_master_resume(content)
        if profile is None:
            return changed
        if facts["grad_year"] and not profile.grad_year:
            profile.grad_year = facts["grad_year"]
            changed["grad_year"] = facts["grad_year"]
        if facts["academic_year"] and (
            profile.academic_year is None or facts["academic_year_source"] == "stated"
        ):
            if profile.academic_year != facts["academic_year"]:
                profile.academic_year = facts["academic_year"]
                changed["academic_year"] = facts["academic_year"]
        if facts["country"] and not profile.country_of_study:
            profile.country_of_study = facts["country"]
            profile.country_of_residence = profile.country_of_residence or facts["country"]
            changed["country"] = facts["country"]
        if facts["tracks"] and not profile.preferred_roles:
            profile.preferred_roles = facts["tracks"]
            changed["tracks"] = facts["tracks"]
        if changed:
            await radar_memory.upsert_user_opportunity_profile(user_id, profile)
    except Exception as err:  # profile fill-in is a convenience: never fail the resume save
        logger.warning("Could not fill the candidate profile from the resume: %s", type(err).__name__)
    return changed
