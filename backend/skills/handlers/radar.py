"""
Compass — Internship Radar AI Skill Handler.

Answers chat questions about internships from the same recommendation query the Career page uses,
so chat and the Radar tab never disagree. User-facing text is plain language: no internal terms.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from backend.memory.radar import get_user_opportunity_profile
from backend.models_radar import EligibilityClassification, OpportunityOut, OpportunityStatus
from backend.services.radar_prediction import estimate_recruitment_cycle
from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.radar")

# Must match the enum in QUERY_INTERNSHIP_RADAR_TOOL. "general" is a catch-all label, not a filterable
# category: filtering on it finds nothing, so it (and anything unknown) means "all categories".
VALID_RADAR_CATEGORIES = frozenset({"ai_ml", "swe", "backend", "data", "research", "cloud", "open_source"})
MAX_CHAT_RESULTS = 10
DEFAULT_CHAT_RESULTS = 8

_FIT_LABEL = {
    EligibilityClassification.ELIGIBLE: "Fits your profile",
    EligibilityClassification.POTENTIAL_MATCH: "Possible fit, check the details",
    EligibilityClassification.INSUFFICIENT_INFORMATION: "Fit not confirmed yet",
    EligibilityClassification.INELIGIBLE: "Probably not open to you",
}
_STATUS_LABEL = {
    OpportunityStatus.OPEN_CONFIRMED: "open now",
    OpportunityStatus.UPCOMING_CONFIRMED: "opening soon",
    OpportunityStatus.ANNOUNCED: "opening soon",
}
SEE_ALL_HINT = "See all internships: open the Career tab and choose Internship Radar."

STOP_WORDS = frozenset({
    "a", "an", "the", "for", "in", "of", "to", "me", "my", "i",
    "find", "show", "give", "get", "search", "looking", "look", "want", "need",
    "any", "some", "all", "best", "top", "good", "new", "please", "can", "you",
    "internship", "internships", "intern", "interns",
    "role", "roles", "job", "jobs", "opportunity", "opportunities", "program", "programs",
    "student", "students",
    "btech", "b", "tech", "be", "cse", "cs", "computer", "science", "engineering",
    "year", "1st", "2nd", "3rd", "4th", "first", "second", "third", "fourth", "final",
    "summer", "winter", "2026", "2027",
    "india", "indian", "remote", "abroad", "worldwide",
    "and",
})

CATEGORY_SYNONYMS: Dict[str, str] = {
    "frontend": "swe",
    "backend": "backend",
    "fullstack": "swe",
    "software": "swe",
    "sde": "swe",
    "swe": "swe",
    "ai": "ai_ml",
    "ml": "ai_ml",
    "machine": "ai_ml",
    "learning": "ai_ml",
    "deep": "ai_ml",
    "nlp": "ai_ml",
    "llm": "ai_ml",
    "genai": "ai_ml",
    "data": "data",
    "analytics": "data",
    "analyst": "data",
    "cloud": "cloud",
    "devops": "cloud",
    "sre": "cloud",
    "research": "research",
    "opensource": "open_source",
    "open-source": "open_source",
    "gsoc": "open_source",
}


def normalize_category(value: Any) -> Optional[str]:
    """Valid category, or None (meaning every category) for 'general', unknown or empty values."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in VALID_RADAR_CATEGORIES else None


def extract_search_keywords(query: str) -> List[str]:
    """Lowercase, split on non-alphanumeric (keep + and # inside tokens), drop stop words and numbers, return up to 4 distinct tokens."""
    if not query or not isinstance(query, str):
        return []
    q = query.lower()
    result: List[str] = []
    seen = set()
    for raw in re.split(r"[^a-z0-9+#]+", q):
        token = raw.lstrip("#+")
        if not token or not any(c.isalnum() for c in token):
            continue
        if token.isdigit() or token in STOP_WORDS:
            continue
        if token not in seen:
            seen.add(token)
            result.append(token)
            if len(result) == 4:
                break
    return result


def resolve_category(category: Any = None, query: str = "") -> Optional[str]:
    """Resolve category from explicit argument or infer from query synonyms."""
    norm = normalize_category(category)
    if norm is not None:
        return norm
    if isinstance(category, str):
        c_clean = category.strip().lower()
        if c_clean in CATEGORY_SYNONYMS:
            return CATEGORY_SYNONYMS[c_clean]
    if not query or not isinstance(query, str):
        return None
    q_lower = query.lower()
    if re.search(r"\bopen[- ]source\b", q_lower):
        return "open_source"
    for raw in re.split(r"[^a-z0-9+#]+", q_lower):
        token = raw.lstrip("#+")
        if token in CATEGORY_SYNONYMS:
            return CATEGORY_SYNONYMS[token]
    return None


def map_query_to_category(query: str) -> Optional[str]:
    """Map keywords in query to a valid radar category using CATEGORY_SYNONYMS."""
    return resolve_category(None, query)


def _clamp_limit(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CHAT_RESULTS
    return max(1, min(n, MAX_CHAT_RESULTS))


def _matches_any_keyword(item: OpportunityOut, keywords: List[str]) -> bool:
    fields = [
        item.company_name or "",
        item.role_title or "",
        item.category or "",
        item.description or "",
    ]
    text = " ".join(fields).lower()
    return any(kw in text for kw in keywords)


@register_skill("query_internship_radar")
async def handle_query_internship_radar(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Top internship matches for the user, from the same query as the Career page."""
    from backend.routers.radar import recommended_for_user

    query = (args.get("query") or "").strip() if isinstance(args.get("query"), str) else ""
    category = resolve_category(args.get("category"), query)
    india_only = bool(args.get("india_only", True))
    limit = _clamp_limit(args.get("limit", DEFAULT_CHAT_RESULTS))
    user_id = args.get("user_id", "default_user")

    profile = await get_user_opportunity_profile(user_id)
    keywords = extract_search_keywords(query) if query else []

    async def _fetch_opportunities(country_filter: bool) -> tuple[List[OpportunityOut], int, bool]:
        raw_items = await recommended_for_user(user_id, profile, india_only=country_filter)
        if category:
            raw_items = [o for o in raw_items if o.category == category]

        if keywords:
            matching = [o for o in raw_items if _matches_any_keyword(o, keywords)]
            if matching:
                return matching, len(matching), False
            return list(raw_items), len(raw_items), bool(raw_items)
        return list(raw_items), len(raw_items), False

    items, total, kw_fallback = await _fetch_opportunities(india_only)
    widened_to_worldwide = False
    if not items and india_only:
        items, total, kw_fallback = await _fetch_opportunities(False)
        widened_to_worldwide = True

    items = items[:limit]

    results = []
    lines = []
    for item in items:
        item.prediction = item.prediction or estimate_recruitment_cycle(item.cycles)
        cls = item.eligibility_classification
        results.append({
            "id": item.id,
            "company": item.company_name,
            "role": item.role_title,
            "category": item.category,
            "status": item.current_status,
            "location": item.location,
            "work_arrangement": item.work_arrangement,
            "compensation": item.compensation,
            "application_url": item.official_application_url,
            "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
            "eligibility": cls,
            "eligibility_explanation": item.eligibility_explanation,
            "predicted_window": item.prediction.estimated_open_window if item.prediction else None,
            "prediction_confidence": item.prediction.confidence if item.prediction else None,
        })
        status_text = _STATUS_LABEL.get(item.current_status, "check the company site")
        line = (
            f"• **{item.company_name}** — {item.role_title} ({status_text})\n"
            f"  - Where: {item.location or item.country or 'Not stated'} | {_FIT_LABEL.get(cls, 'Fit not confirmed yet')}"
        )
        if item.official_application_url:
            line += f"\n  - Link: {item.official_application_url}"
        lines.append(line)

    if not results:
        msg = "I could not find an open internship right now. Compass checks for new ones every day. " + SEE_ALL_HINT
        return {
            "success": True,
            "data": {
                "count": 0,
                "opportunities": [],
                "see_all_hint": SEE_ALL_HINT,
                "keywords": keywords,
                "widened_to_worldwide": widened_to_worldwide,
            },
            "summary": msg,
            "response": msg,
        }

    profile_note = "" if profile else "\n\nAdd your profile in Resume Studio so I can tell which of these fit you best."
    kw_str = ", ".join(keywords)

    if widened_to_worldwide:
        prefix = "I did not find India-based matches, so these are roles open to applicants worldwide or remote:\n\n"
        if kw_fallback:
            prefix += f"I did not find roles that mention {kw_str}; here are the top open internships from Compass Internship Radar instead:\n\n"
    elif kw_fallback:
        prefix = f"I did not find roles that mention {kw_str}; here are the top open internships from Compass Internship Radar instead:\n\n"
    else:
        prefix = f"Here are your top {len(results)} internship matches from Compass Internship Radar:\n\n"

    formatted_summary = (
        prefix
        + "\n\n".join(lines)
        + f"\n\n{SEE_ALL_HINT}"
        + profile_note
    )
    return {
        "success": True,
        "data": {
            "count": len(results),
            "total_matching": total,
            "opportunities": results,
            "see_all_hint": SEE_ALL_HINT,
            "keywords": keywords,
            "widened_to_worldwide": widened_to_worldwide,
        },
        "summary": formatted_summary,
        "response": formatted_summary,
    }
