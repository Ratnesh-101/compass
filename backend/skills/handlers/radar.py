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
from backend.services.radar_freshness import is_fresh_open, verification_age_days
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


# ---- Profile-aware search: parse the student's message, score listings, list the best 8 ----

_YEAR_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "final": 4}
_YEAR_RE = re.compile(r"\b([1-4])(?:st|nd|rd|th)[- ]year\b", re.IGNORECASE)
_YEAR_WORD_RE = re.compile(r"\b(first|second|third|fourth|final)[- ]year\b", re.IGNORECASE)
_BRANCH_RE = re.compile(
    r"\b(cse|cs|computer science|information technology|ece|eee|mechanical|civil)\b",
    re.IGNORECASE,
)
_IT_RE = re.compile(r"\bIT\b")
_BRANCH_CANON = {
    "cse": "cse", "cs": "cse", "computer science": "cse",
    "it": "it", "information technology": "it",
    "ece": "ece", "eee": "eee", "mechanical": "mechanical", "civil": "civil",
}
_CITY_RE = re.compile(
    r"\b(bangalore|bengaluru|hyderabad|pune|mumbai|delhi|noida|gurgaon|gurugram|chennai|kolkata|ahmedabad)\b",
    re.IGNORECASE,
)
_STIPEND_RE = re.compile(r"\bstipend\b[^0-9]{0,20}(\d[\d,]{0,8})", re.IGNORECASE)
_DURATION_RE = re.compile(r"\b(\d{1,2})\s{0,2}months?\b", re.IGNORECASE)

# interest -> (word pattern matched in title and description, categories)
INTEREST_PATTERNS: Dict[str, tuple] = {
    "ai_ml": (r"\b(?:ml|ai|machine learning|deep learning|nlp|computer vision|data science|llm|genai)\b", ("ai_ml",)),
    "web": (r"\b(?:web|full[- ]?stack|react|node)\b", ("swe",)),
    "data": (r"\b(?:data|analytics|analyst)\b", ("data",)),
    "security": (r"\b(?:security|cyber|infosec|pentest)\b", ()),
    "backend": (r"\b(?:backend|back[- ]end|api|server)\b", ("backend",)),
    "frontend": (r"\b(?:frontend|front[- ]end|ui engineer)\b", ("swe",)),
    "mobile": (r"\b(?:mobile|android|ios|flutter)\b", ()),
    "devops": (r"\b(?:devops|sre|cloud|kubernetes)\b", ("cloud",)),
    "research": (r"\b(?:research|researcher)\b", ("research",)),
}
_INTEREST_QUERY_RE = {
    "ai_ml": re.compile(r"\b(?:ml|ai|machine learning|deep learning|nlp|computer vision|data science|llm|genai)\b", re.IGNORECASE),
    "web": re.compile(r"\b(?:web|full[- ]?stack)\b", re.IGNORECASE),
    "data": re.compile(r"\b(?:data|analytics)\b", re.IGNORECASE),
    "security": re.compile(r"\b(?:security|cyber ?security|infosec)\b", re.IGNORECASE),
    "backend": re.compile(r"\bback[- ]?end\b", re.IGNORECASE),
    "frontend": re.compile(r"\bfront[- ]?end\b", re.IGNORECASE),
    "mobile": re.compile(r"\b(?:mobile|android|ios|flutter)\b", re.IGNORECASE),
    "devops": re.compile(r"\b(?:devops|sre|cloud)\b", re.IGNORECASE),
    "research": re.compile(r"\bresearch\b", re.IGNORECASE),
}
_NON_TECH_RE = re.compile(
    r"\b(?:hr|human resources|talent acquisition|payroll|recruiter|recruiting|recruitment|sales|finance|content|design|marketing)\b",
    re.IGNORECASE,
)
_ENGINEERING_RE = re.compile(r"\b(?:engineer|engineering|developer|software|sde|swe|research|scientist)\b", re.IGNORECASE)
MIN_RELEVANT = 3
SCORED_RESULTS = 8


def parse_internship_query(message: str) -> Dict[str, Any]:
    """Pull profile hints (year, branch, interests, location, remote, stipend, duration) out of a message."""
    out: Dict[str, Any] = {
        "year": None, "branch": None, "interests": [], "location": None,
        "remote": False, "stipend": None, "duration_months": None,
    }
    if not isinstance(message, str) or not message.strip():
        return out
    text = " ".join(message.split())[:600]
    m = _YEAR_RE.search(text)
    if m:
        out["year"] = int(m.group(1))
    else:
        m = _YEAR_WORD_RE.search(text)
        if m:
            out["year"] = _YEAR_WORDS[m.group(1).lower()]
    m = _BRANCH_RE.search(text)
    if m:
        out["branch"] = _BRANCH_CANON.get(m.group(1).lower())
    elif _IT_RE.search(text):
        out["branch"] = "it"
    out["interests"] = [k for k, rx in _INTEREST_QUERY_RE.items() if rx.search(text)]
    m = _CITY_RE.search(text)
    if m:
        out["location"] = m.group(1).lower()
    elif re.search(r"\bindia\b", text, re.IGNORECASE):
        out["location"] = "india"
    out["remote"] = bool(re.search(r"\bremote\b", text, re.IGNORECASE))
    m = _STIPEND_RE.search(text)
    if m:
        out["stipend"] = m.group(1).replace(",", "")
    m = _DURATION_RE.search(text)
    if m:
        out["duration_months"] = int(m.group(1))
    return out


def score_internship(item: OpportunityOut, parsed: Dict[str, Any], message: str = "") -> Dict[str, Any]:
    """Score one listing. 'matches' counts interest hits; only listings with matches are relevant."""
    title = (item.role_title or "").lower()
    haystack = f"{title} {(item.description or '').lower()}"
    matches = 0
    for interest in parsed.get("interests") or []:
        pattern, cats = INTEREST_PATTERNS[interest]
        if (item.category in cats) or re.search(pattern, haystack):
            matches += 1
    technical = bool(parsed.get("interests")) or parsed.get("branch") in ("cse", "it", "ece")
    score = 3 * matches
    if parsed.get("branch") in ("cse", "it") and _ENGINEERING_RE.search(title):
        score += 2
    asked_design = bool(re.search(r"\bdesign\b", message or "", re.IGNORECASE))
    non_tech = _NON_TECH_RE.search(title)
    if non_tech and technical and not (asked_design and non_tech.group(0).lower() == "design"):
        score -= 4
    if is_fresh_open(item):
        score += 1
    if parsed.get("remote") and (item.work_arrangement or "").lower() == "remote":
        score += 1
    return {"score": score, "matches": matches}


def verification_note(item: OpportunityOut) -> str:
    """'verified today', 'verified N days ago' or 'needs re-check'."""
    if not is_fresh_open(item):
        return "needs re-check"
    age = verification_age_days(item)
    if age is None:
        return "needs re-check"
    if age <= 0:
        return "verified today"
    return f"verified {age} day{'s' if age != 1 else ''} ago"


def rank_internships(items: List[OpportunityOut], parsed: Dict[str, Any], message: str = "") -> tuple:
    """Return (relevant, closest): interest-matching listings best first, and non-penalised near misses."""
    city = parsed.get("location")
    relevant: List[tuple] = []
    others: List[tuple] = []
    for idx, item in enumerate(items):
        sc = score_internship(item, parsed, message)
        city_ok = not city or city == "india" or city in (item.location or "").lower()
        row = (-sc["score"], idx, item)
        if sc["matches"] > 0 and city_ok:
            relevant.append(row)
        elif city_ok and sc["score"] > 1:
            others.append(row)
    relevant.sort(key=lambda r: (r[0], r[1]))
    others.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in relevant], [r[2] for r in others]


def _scored_line(item: OpportunityOut) -> str:
    line = f"- **{item.company_name}**: {item.role_title} | {item.location or item.country or 'Not stated'} | {verification_note(item)}"
    if item.official_application_url:
        line += f"\n  Apply: {item.official_application_url}"
    return line


def format_scored_answer(relevant: List[OpportunityOut], closest: List[OpportunityOut]) -> str:
    """Top 8, or 'I found only N' plus the closest and an offer to widen."""
    n = len(relevant)
    if n >= MIN_RELEVANT:
        shown = relevant[:SCORED_RESULTS]
        head = f"Here are the top {len(shown)} internships that match your profile:\n\n"
        return head + "\n".join(_scored_line(o) for o in shown) + f"\n\n{SEE_ALL_HINT}"
    shown = (relevant + closest)[:3]
    head = f"I found only {n} listing{'s' if n != 1 else ''} that match; "
    if shown:
        head += "here is the closest:\n\n" + "\n".join(_scored_line(o) for o in shown) + "\n\n"
    else:
        head += "I have nothing close to show, so I will not pad this with unrelated roles.\n\n"
    return head + "Want me to widen the search? I can drop the interest filter or the location filter.\n" + SEE_ALL_HINT


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
    parsed = parse_internship_query(query)
    if parsed["interests"]:
        raw = await recommended_for_user(user_id, profile, india_only=india_only)
        widened = False
        if not raw and india_only:
            raw, widened = await recommended_for_user(user_id, profile, india_only=False), True
        relevant, closest = rank_internships(list(raw), parsed, query)
        if len(relevant) >= MIN_RELEVANT:
            shown = relevant[:SCORED_RESULTS]
        else:
            shown = (relevant + closest)[:3]
        text = format_scored_answer(relevant, closest)
        return {
            "success": True,
            "data": {
                "count": len(shown),
                "total_matching": len(relevant),
                "opportunities": [
                    {"id": o.id, "company": o.company_name, "role": o.role_title, "category": o.category,
                     "location": o.location, "application_url": o.official_application_url,
                     "verification": verification_note(o), "status": o.current_status}
                    for o in shown
                ],
                "see_all_hint": SEE_ALL_HINT,
                "keywords": keywords,
                "profile": parsed,
                "widened_to_worldwide": widened,
            },
            "summary": text,
            "response": text,
        }

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
