"""Saved Career profile as a context block for the chat (N-010). Read-only, owner-scoped."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


def _ordinal(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def format_candidate_profile(profile: Any, full_name: str = "") -> str:
    """One compact context block from the saved candidate profile, or '' when there is nothing to say."""
    parts: List[str] = []
    if full_name:
        parts.append(f"Name: {full_name}")
    degree = " ".join(x for x in (getattr(profile, "degree", None), getattr(profile, "degree_specialization", None)) if x)
    if degree:
        parts.append(f"Degree: {degree}")
    if getattr(profile, "university", None):
        parts.append(f"University: {profile.university}")
    year = getattr(profile, "academic_year", None)
    if isinstance(year, int):
        parts.append(f"Current year of study: {_ordinal(year)} year")
    if getattr(profile, "grad_year", None):
        parts.append(f"Graduation year: {profile.grad_year}")
    cgpa = getattr(profile, "cgpa", None)
    if cgpa is not None:
        scale = getattr(profile, "cgpa_scale", None) or 10.0
        parts.append(f"CGPA: {cgpa}/{scale:g}")
    skills = [s for s in (getattr(profile, "skills", None) or []) if s][:15]
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    country = getattr(profile, "country_of_study", None)
    if country:
        parts.append(f"Country: {country}")
    if not parts:
        return ""
    return (
        "[CANDIDATE PROFILE saved in the Career tab. Use these facts directly; do not ask the user for them "
        "and never write placeholders like [Your Name]]:\n" + "\n".join(f"- {p}" for p in parts)
    )


async def load_candidate_profile_context(owner_id: Optional[str]) -> str:
    """Read-only: the caller's saved candidate profile as a context block. '' on any miss or error."""
    if not owner_id:
        return ""
    try:
        from backend.memory.radar import get_user_opportunity_profile_and_master

        # One call: it already reads the master resume, so the display name comes from that same read.
        profile, master = await get_user_opportunity_profile_and_master(owner_id)
        full_name = (getattr(getattr(master, "content", None), "full_name", "") or "").strip()
        if profile is None and not full_name:
            return ""
        if profile is None:
            return f"[CANDIDATE PROFILE saved in the Career tab]:\n- Name: {full_name}"
        return format_candidate_profile(profile, full_name)
    except Exception as e:
        logger.debug("Candidate profile context unavailable: %s", e)
        return ""
