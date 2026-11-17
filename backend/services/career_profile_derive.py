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


def resume_facts(content: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Facts the profile form needs, taken from resume content (ResumeContent or dict)."""
    edu_list = list(_get(content, "education", []) or [])
    edu = latest_education(edu_list)
    notes = _get(content, "evidence_notes", {}) or {}
    note_text = " ".join(str(v) for k, v in notes.items() if str(k).startswith("education"))
    stated = None
    start = end = None
    if edu is not None:
        stated = stated_year_of_study(
            note_text, _get(edu, "institution"), _get(edu, "degree"), _get(edu, "field_of_study")
        )
        start, end = _get(edu, "start_year"), _get(edu, "end_year")
    academic_year = stated or academic_year_from_dates(start, end, today)
    skills = [s for s in (_get(content, "skills", []) or []) if isinstance(s, str)]
    project_text = " ".join(
        f"{_get(p, 'title', '')} {_get(p, 'description', '')}" for p in (_get(content, "projects", []) or [])
    )
    return {
        "academic_year": academic_year,
        "academic_year_source": "stated" if stated else ("computed" if academic_year else None),
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
