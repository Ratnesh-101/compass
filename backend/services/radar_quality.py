"""
Compass — Internship Radar listing quality: dedupe, entry-level and fit filters, country ranking.

Pure functions over OpportunityOut. No database access, so everything here is unit-testable.
Dedupe runs at query time (no schema migration): rows for the same company and title are merged
into one, keeping the stricter requirements and the better-sourced record.
"""
from __future__ import annotations

import re
from datetime import timezone
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from backend.models_radar import (
    EligibilityClassification,
    OpportunityOut,
    OpportunityRequirementsOut,
    OpportunitySourceOut,
    OpportunityStatus,
)
from backend.services.career_job_match import build_skill_index, skill_in_index
from backend.services.radar_eligibility import countries_named_in_location

# ---------------------------------------------------------------------------
# Name normalization and dedupe
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = {
    "inc", "incorporated", "ltd", "limited", "llc", "llp", "corp", "corporation", "co", "company",
    "technologies", "technology", "pvt", "private", "gmbh", "plc",
}


def normalize_company(name: Optional[str]) -> str:
    """'DirecTV, Inc.' and 'DIRECTV' both become 'directv'."""
    tokens = re.sub(r"[^\w\s]", " ", (name or "").lower()).split()
    while len(tokens) > 1 and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def normalize_title(title: Optional[str]) -> str:
    t = re.sub(r"[^\w\s]", " ", (title or "").lower())
    t = re.sub(r"\binternships?\b", "intern", t)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)  # "Summer 2026" and "Summer 2027" are the same role
    return " ".join(t.split())


def dedupe_key(opp: OpportunityOut) -> Tuple[str, str, str]:
    """Company + title, plus country so the same title in two countries stays two listings."""
    return (normalize_company(opp.company_name), normalize_title(opp.role_title), (opp.country or "").strip().lower())


_STATUS_ORDER = {
    OpportunityStatus.OPEN_CONFIRMED: 0,
    OpportunityStatus.UPCOMING_CONFIRMED: 1,
    OpportunityStatus.ANNOUNCED: 2,
    OpportunityStatus.NEEDS_VERIFICATION: 3,
    OpportunityStatus.DISCOVERED: 4,
}
_AUTHORITY_ORDER = {"tier_1": 0, "tier_2": 1, "tier_3": 2}
_AGGREGATOR_HOSTS = ("linkedin.", "indeed.", "glassdoor.", "ziprecruiter.")


def _requirements_richness(opp: OpportunityOut) -> int:
    r = opp.requirements
    if not r:
        return 0
    return sum([
        bool(r.eligible_degree_types), bool(r.eligible_academic_years), bool(r.eligible_graduation_years),
        bool(r.eligible_countries), r.min_gpa is not None, bool(r.required_skills),
        r.no_active_backlogs is True, r.work_auth_required is True,
    ])


def _best_authority(opp: OpportunityOut) -> int:
    ranks = [_AUTHORITY_ORDER.get(s.source_authority, 3) for s in opp.sources]
    return min(ranks) if ranks else 3


def _ts(opp: OpportunityOut) -> float:
    dt = opp.last_verified_at
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _best_first_key(opp: OpportunityOut) -> tuple:
    return (
        _STATUS_ORDER.get(opp.current_status, 5),
        _best_authority(opp),
        0 if opp.official_source_confirmed else 1,
        -_requirements_richness(opp),
        -_ts(opp),
        opp.id,
    )


def _intersect_or_first(lists: List[list]) -> list:
    """Stricter list: the overlap when the lists overlap, otherwise the best-sourced list."""
    non_empty = [lst for lst in lists if lst]
    if not non_empty:
        return []
    common = [x for x in non_empty[0] if all(x in other for other in non_empty[1:])]
    return common or list(non_empty[0])


def _union(lists: Iterable[Iterable[str]]) -> List[str]:
    seen: Dict[str, None] = {}
    for items in lists:
        for item in items:
            if item and item not in seen:
                seen[item] = None
    return list(seen)


def merge_requirements(reqs: List[Optional[OpportunityRequirementsOut]]) -> Optional[OpportunityRequirementsOut]:
    """Merge requirement sets, best-sourced first. The result is never looser than any input."""
    present = [r for r in reqs if r is not None]
    if not present:
        return None
    first = present[0]

    def _grade(r: OpportunityRequirementsOut) -> float:
        return (float(r.min_gpa) / float(r.gpa_scale or 10.0)) if r.min_gpa is not None else -1.0

    strictest_gpa = max(present, key=_grade)
    sponsorship = [r.sponsorship_available for r in present if r.sponsorship_available is not None]
    caveats = _union([[(r.other_mandatory_requirements or "").strip()] for r in present])
    return first.model_copy(update={
        "eligible_degree_types": _intersect_or_first([r.eligible_degree_types for r in present]),
        "eligible_academic_years": _intersect_or_first([r.eligible_academic_years for r in present]),
        "eligible_graduation_years": _intersect_or_first([r.eligible_graduation_years for r in present]),
        "eligible_countries": _intersect_or_first([r.eligible_countries for r in present]),
        "required_skills": _union(r.required_skills for r in present),
        "preferred_skills": _union(r.preferred_skills for r in present),
        "min_gpa": strictest_gpa.min_gpa,
        "gpa_scale": strictest_gpa.gpa_scale if strictest_gpa.min_gpa is not None else first.gpa_scale,
        "no_active_backlogs": True if any(r.no_active_backlogs is True for r in present) else first.no_active_backlogs,
        "work_auth_required": True if any(r.work_auth_required is True for r in present) else first.work_auth_required,
        "sponsorship_available": (False if False in sponsorship else (True if sponsorship else None)),
        "has_conflicting_requirements": any(r.has_conflicting_requirements for r in present),
        "other_mandatory_requirements": "; ".join(caveats) or None,
        "unknown_requirements": _union(r.unknown_requirements for r in present),
    })


def _is_aggregator_url(url: Optional[str]) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(h in host for h in _AGGREGATOR_HOSTS)


def merge_duplicates(group: List[OpportunityOut]) -> OpportunityOut:
    """Collapse rows for one listing into the best-sourced one, keeping stricter requirements."""
    # A row the user saved or tracks is shown first, so Save/Unsave and notes act on the row they see.
    ordered = sorted(group, key=lambda o: (not o.is_saved, not bool(o.application_status), _best_first_key(o)))
    best = ordered[0]
    if len(ordered) == 1:
        return best

    sources: List[OpportunitySourceOut] = []
    seen_src = set()
    for o in ordered:
        for s in o.sources:
            k = (s.source_url, s.source_name)
            if k not in seen_src:
                seen_src.add(k)
                sources.append(s)

    url = best.official_application_url
    if not url or _is_aggregator_url(url):
        url = next((o.official_application_url for o in ordered if o.official_application_url and not _is_aggregator_url(o.official_application_url)), url)

    closes = [o.confirmed_close_date for o in ordered if o.confirmed_close_date]
    tracked = next((o for o in ordered if o.application_status), None)
    longest = max((o.description or "" for o in ordered), key=len)
    return best.model_copy(update={
        "sources": sources,
        "requirements": merge_requirements([o.requirements for o in ordered]),
        "official_application_url": url,
        "confirmed_close_date": min(closes) if closes else None,
        "description": longest if len(longest) > len(best.description or "") else best.description,
        "is_saved": any(o.is_saved for o in ordered),
        "application_status": tracked.application_status if tracked else best.application_status,
        "application_date": tracked.application_date if tracked else best.application_date,
        "personal_deadline": next((o.personal_deadline for o in ordered if o.personal_deadline), best.personal_deadline),
        "private_notes": next((o.private_notes for o in ordered if o.private_notes), best.private_notes),
    })


def dedupe_opportunities(items: List[OpportunityOut]) -> List[OpportunityOut]:
    """One row per listing, in first-seen order of the group."""
    groups: Dict[Tuple[str, str, str], List[OpportunityOut]] = {}
    for o in items:
        key = dedupe_key(o)
        if not key[0] or not key[1]:
            groups[(f"id:{o.id}", "", "")] = [o]
            continue
        groups.setdefault(key, []).append(o)
    return [merge_duplicates(g) for g in groups.values()]


# ---------------------------------------------------------------------------
# Fit filters
# ---------------------------------------------------------------------------

_SENIOR_ALWAYS_RE = re.compile(r"\b(senior|sr|staff|principal|director|vice president)\b", re.IGNORECASE)
_SENIOR_CONTEXT_RE = re.compile(r"\b(lead|manager|head of|vp)\b", re.IGNORECASE)
_ENTRY_WORD_RE = re.compile(
    r"\b(intern|interns|internship|trainee|apprentice|apprenticeship|fellow|fellowship|co-?op|student)\b",
    re.IGNORECASE,
)
YEARLY_SALARY_LIMIT = 70_000        # USD/EUR/GBP: above this a "yearly" figure is a full-time salary
YEARLY_SALARY_LIMIT_INR = 1_500_000

_YEARLY_RE = re.compile(r"(/\s*(year|yr)\b|\bper\s+(year|annum)\b|\byearly\b|\bannual(ly)?\b|\blpa\b)", re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?", re.IGNORECASE)


def yearly_salary_exceeds_internship_range(compensation: Optional[str]) -> bool:
    """True for a yearly figure that is a full-time salary (e.g. 'USD 90,000 - 120,000 / year')."""
    text = (compensation or "").strip()
    if not text or not _YEARLY_RE.search(text):
        return False
    m = _AMOUNT_RE.search(text)
    if not m:
        return False
    amount = float(m.group(1).replace(",", ""))
    if re.search(r"\b(lakh|lakhs|lpa)\b", text, re.IGNORECASE):
        amount *= 100_000  # "28 LPA" is 2,800,000 rupees a year
    elif m.group(2):
        amount *= 1000
    inr = bool(re.search(r"\binr\b|₹|\brs\.?\b|lakh|lpa", text, re.IGNORECASE))
    return amount > (YEARLY_SALARY_LIMIT_INR if inr else YEARLY_SALARY_LIMIT)


def is_entry_level_listing(opp: OpportunityOut) -> bool:
    """False for senior-titled roles and for full-time salaries that are not internship pay."""
    title = opp.role_title or ""
    if _SENIOR_ALWAYS_RE.search(title):
        return False
    if _SENIOR_CONTEXT_RE.search(title) and not _ENTRY_WORD_RE.search(title):
        return False
    return not yearly_salary_exceeds_internship_range(opp.compensation)


_CLEARANCE_RE = re.compile(
    r"(security clearance|secret clearance|top secret|ts\s*/\s*sci|public trust|"
    r"u\.?s\.? citizen(ship)?|citizenship (is )?required|must be a (u\.?s\.? )?citizen|"
    r"green card|permanent resident (status )?required)",
    re.IGNORECASE,
)


def requires_clearance_or_citizenship(opp: OpportunityOut) -> bool:
    parts = [opp.role_title or "", opp.description or ""]
    r = opp.requirements
    if r:
        parts.append(r.other_mandatory_requirements or "")
        parts.extend(str(u) for u in r.unknown_requirements)
    return bool(_CLEARANCE_RE.search(" ".join(parts)))


_COUNTRY_ALIASES = {"usa": "united states", "us": "united states", "u s": "united states", "uk": "united kingdom"}
_GLOBAL_WORDS = {"", "global", "worldwide", "remote", "anywhere", "international"}


def _canon_country(value: Optional[str]) -> str:
    norm = " ".join(re.sub(r"[^\w\s]", " ", (value or "").lower()).split())
    return _COUNTRY_ALIASES.get(norm, norm)


def profile_country_of(profile) -> str:
    """Canonical country of the candidate, India when none is saved (the Radar default audience)."""
    if profile is not None:
        c = _canon_country(getattr(profile, "country_of_residence", None) or getattr(profile, "country_of_study", None))
        if c:
            return c
    return "india"


def country_rank(opp: OpportunityOut, profile_country: str) -> int:
    """0 = listing is in the candidate's country, 1 = explicitly open to it, 2 = anything else."""
    named = countries_named_in_location(opp.location)
    if named and profile_country not in named:
        return 2
    listing = _canon_country(opp.country)
    if listing == profile_country:
        return 0
    if profile_country in named:
        return 0
    if listing in _GLOBAL_WORDS and opp.is_india_eligible and profile_country == "india":
        return 1
    return 2


def refine_listings(
    items: List[OpportunityOut],
    profile_country: str = "india",
    country_filter: bool = True,
) -> List[OpportunityOut]:
    """Dedupe, then drop senior/clearance/non-fitting listings. Country filter is optional."""
    out = []
    for o in dedupe_opportunities(items):
        if not is_entry_level_listing(o) or requires_clearance_or_citizenship(o):
            continue
        if country_filter and country_rank(o, profile_country) > 1:
            continue
        out.append(o)
    return out


@lru_cache(maxsize=256)
def _profile_skill_index(skills: tuple) -> Dict[str, str]:
    """Skill index for a profile's saved skills (labelled lists like 'Languages: Python, Java' are split)."""
    return build_skill_index([s for s in skills if isinstance(s, str)])


def recommendation_rank_key(o: OpportunityOut, profile, profile_country: str) -> tuple:
    """Sort key for recommendations. Lower sorts first.

    1. Country: listings in the candidate's country (or explicitly open to it) before everything else.
    2. Status: fresh OPEN_CONFIRMED, then upcoming, then stale open, then the rest.
    3. Eligibility: ELIGIBLE, POTENTIAL_MATCH, INSUFFICIENT_INFORMATION, INELIGIBLE.
    4. Preferred role fit, 5. skill overlap, 6. closest deadline.
    """


    if o.current_status == OpportunityStatus.OPEN_CONFIRMED:
        status_weight = 2 if o.needs_recheck else 0
    elif o.current_status in (OpportunityStatus.UPCOMING_CONFIRMED, OpportunityStatus.ANNOUNCED):
        status_weight = 1
    else:
        status_weight = 3
    eligibility_weight = {
        EligibilityClassification.ELIGIBLE: 0,
        EligibilityClassification.POTENTIAL_MATCH: 1,
        EligibilityClassification.INSUFFICIENT_INFORMATION: 2,
        EligibilityClassification.INELIGIBLE: 3,
    }.get(o.eligibility_classification, 2)

    role_bonus = 0
    if profile and profile.preferred_roles:
        pref = [r.lower() for r in profile.preferred_roles]
        if any(p in (o.role_title or "").lower() or p in (o.category or "").lower() for p in pref):
            role_bonus = -1

    skill_bonus = 0
    if profile and profile.skills and o.requirements and o.requirements.required_skills:
        index = _profile_skill_index(tuple(profile.skills))
        req_s = {s.strip().lower() for s in o.requirements.required_skills if s.strip()}
        skill_bonus = -sum(1 for r in req_s if skill_in_index(r, index))

    deadline_weight = o.confirmed_close_date.toordinal() if o.confirmed_close_date else 9999999
    return (country_rank(o, profile_country), status_weight, eligibility_weight, role_bonus, skill_bonus, deadline_weight)
