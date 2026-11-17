"""
Compass — Internship Radar AI Skill Handler.

Answers chat questions about internships from the same recommendation query the Career page uses,
so chat and the Radar tab never disagree. User-facing text is plain language: no internal terms.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.memory.radar import get_all_opportunities, get_user_opportunity_profile
from backend.models_radar import EligibilityClassification, OpportunityOut, OpportunityStatus
from backend.services.radar_prediction import estimate_recruitment_cycle
from backend.services.radar_quality import profile_country_of, recommendation_rank_key, refine_listings
from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.radar")

# Must match the enum in QUERY_INTERNSHIP_RADAR_TOOL. "general" is a catch-all label, not a filterable
# category: filtering on it finds nothing, so it (and anything unknown) means "all categories".
VALID_RADAR_CATEGORIES = frozenset({"ai_ml", "swe", "backend", "data", "research", "cloud", "open_source"})
MAX_CHAT_RESULTS = 5
DEFAULT_CHAT_RESULTS = 5

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


def normalize_category(value: Any) -> Optional[str]:
    """Valid category, or None (meaning every category) for 'general', unknown or empty values."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in VALID_RADAR_CATEGORIES else None


def _clamp_limit(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CHAT_RESULTS
    return max(1, min(n, MAX_CHAT_RESULTS))


async def _search_listings(user_id: str, profile: Any, query: str, category: Optional[str], india_only: bool) -> List[OpportunityOut]:
    from backend.routers.radar import _enrich_opportunity  # lazy: the router imports this package's siblings

    raw, _total = await get_all_opportunities(
        user_id=user_id, category=category, search=query, india_only=india_only, page=1, page_size=50
    )
    pc = profile_country_of(profile)
    items = [_enrich_opportunity(o, profile) for o in refine_listings(raw, pc, country_filter=india_only)]
    items = [o for o in items if o.eligibility_classification != EligibilityClassification.INELIGIBLE]
    items.sort(key=lambda o: recommendation_rank_key(o, profile, pc))
    return items


@register_skill("query_internship_radar")
async def handle_query_internship_radar(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Top internship matches for the user, from the same query as the Career page."""
    query = (args.get("query") or "").strip() if isinstance(args.get("query"), str) else ""
    category = normalize_category(args.get("category"))
    india_only = args.get("india_only", True)
    limit = _clamp_limit(args.get("limit", DEFAULT_CHAT_RESULTS))
    user_id = args.get("user_id", "default_user")

    profile = await get_user_opportunity_profile(user_id)
    if query:
        items = await _search_listings(user_id, profile, query, category, bool(india_only))
    else:
        from backend.routers.radar import recommended_for_user

        items = await recommended_for_user(user_id, profile, india_only=bool(india_only))
        if category:
            items = [o for o in items if o.category == category]
    total = len(items)
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
        msg = (
            "I could not find an internship that fits your profile right now. "
            "Next step: check back in a few days, or ask me to include roles outside India. "
            + SEE_ALL_HINT
        )
        return {
            "success": True,
            "data": {"count": 0, "opportunities": [], "see_all_hint": SEE_ALL_HINT},
            "summary": msg,
            "response": msg,
        }

    profile_note = "" if profile else "\n\nAdd your profile in Resume Studio so I can tell which of these fit you best."
    formatted_summary = (
        f"Here are your top {len(results)} internship matches from Compass Internship Radar:\n\n"
        + "\n\n".join(lines)
        + f"\n\n{SEE_ALL_HINT}"
        + profile_note
    )
    return {
        "success": True,
        "data": {"count": len(results), "total_matching": total, "opportunities": results, "see_all_hint": SEE_ALL_HINT},
        "summary": formatted_summary,
        "response": formatted_summary,
    }
