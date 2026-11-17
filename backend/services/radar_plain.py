"""
Compass — Plain-language wording for Internship Radar eligibility results (N-014).

Pure functions. They turn a failed check into one readable sentence and pick a next step, so the
"what am I missing" text never shows Python lists, brackets or internal field names.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd"}

_DEGREE_PHRASE = {
    "masters": "a Master's degree",
    "phd": "a PhD",
    "undergrad": "a Bachelor's degree",
    "other": "a specific degree",
}


def ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


def join_plain(items: Iterable[object]) -> str:
    """'a, b and c' with no brackets or quotes."""
    parts = [str(i).strip() for i in items if str(i).strip()]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def short_degree_name(profile_degree: Optional[str], user_category: str) -> str:
    """'B.Tech' from 'B.Tech Computer Science'; falls back to a level label."""
    words = (profile_degree or "").split()
    if words and len(words[0]) <= 8:
        return words[0]
    return {"undergrad": "undergraduate", "masters": "Master's", "phd": "PhD"}.get(user_category, "your degree")


def degree_fail(allowed_categories: Sequence[str], profile_degree: Optional[str], user_category: str) -> str:
    needs = join_plain(_DEGREE_PHRASE.get(c, "a specific degree") for c in sorted(set(allowed_categories)))
    return f"This role needs {needs}. Your profile says {profile_degree or 'a different degree'}."


def year_fail(required_years: Sequence[int], profile_year: Optional[int]) -> str:
    years = join_plain(f"{ordinal(int(y))} year" for y in required_years)
    return f"This role is for {years} students. Your profile says {ordinal(int(profile_year))} year." if profile_year else (
        f"This role is for {years} students."
    )


def grad_year_fail(required_years: Sequence[int], profile_grad_year: Optional[int]) -> str:
    years = join_plain(str(y) for y in required_years)
    return f"This role is for students graduating in {years}. Your profile says {profile_grad_year}."


def cgpa_fail(min_gpa: float, scale: float, profile_cgpa: Optional[float], profile_scale: float) -> str:
    return (
        f"This role asks for at least {min_gpa:g} out of {scale:g}. "
        f"Your profile says {profile_cgpa:g} out of {profile_scale:g}."
    )


def country_fail(allowed: Sequence[str], student_country: str) -> str:
    return f"This role is only open to applicants in {join_plain(allowed)}. Your profile says {student_country}."


def next_step(
    failed_fields: Sequence[str],
    allowed_categories: Sequence[str],
    profile_degree: Optional[str],
    user_category: str,
) -> str:
    """One suggested next step for the first failed check."""
    if "degree" in failed_fields:
        who = short_degree_name(profile_degree, user_category)
        return f"Skip it, or look at similar roles open to {who} students."
    if "academic_year" in failed_fields or "grad_year" in failed_fields:
        return "Skip it for now, or look at roles that accept your year of study. You can apply to this one next year."
    if "cgpa" in failed_fields:
        return "Skip it, or look at roles with no minimum grade."
    if "country" in failed_fields:
        return "Skip it, or filter for roles in India or open to applicants in India."
    if "work_auth" in failed_fields:
        return "Skip it, or look for roles that offer visa sponsorship or are based in India."
    return "Skip it, or look at similar roles that fit your profile."


def ineligible_explanation(sentences: List[str], step: str) -> str:
    return " ".join([*sentences, step]).strip()
