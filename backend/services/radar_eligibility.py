"""
Compass — Internship Radar Deterministic Eligibility Assessment Engine.

Evaluates an opportunity's published requirements against a student's personal profile.
Produces inspectable classifications (ELIGIBLE, POTENTIAL_MATCH / POTENTIALLY_ELIGIBLE, INELIGIBLE, INSUFFICIENT_INFORMATION)
with granular reason codes and evidence summaries.

Strict Requirements & Principles:
1. Missing graduation year or degree requirement is NOT assumed to mean open to all.
2. Missing work auth requirement is NOT assumed to mean universal eligibility.
3. Every classification is backed by structured reasons inspectable by the user.
4. Fail closed for ELIGIBLE: POTENTIALLY_ELIGIBLE and INSUFFICIENT_INFORMATION must never count as ELIGIBLE.
5. Ineligible on any mandatory failure: A single definitive mandatory failure produces INELIGIBLE.
6. Preferred qualifications do NOT reject: A missing preferred skill or credential does not disqualify.
7. Conflicting requirements: If listing has contradictory constraints, flag conflict and withhold ELIGIBLE.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from backend.services import radar_plain as plain
from backend.models_radar import (
    EligibilityClassification,
    OpportunityOut,
    OpportunityRequirementsOut,
    UserOpportunityProfileIn,
)


def _normalize_string(val: Optional[str]) -> str:
    if not val:
        return ""
    # Lowercase and remove punctuation like periods, dashes
    clean = re.sub(r"[^\w\s]", " ", val.lower())
    return " ".join(clean.split())


def _degree_tokens(degree_str: str) -> Set[str]:
    """Whole-word tokens plus adjacent-pair joins ("b e" -> "be"), never substrings."""
    words = _normalize_string(degree_str).split()
    tokens: Set[str] = set(words)
    tokens.update(a + b for a, b in zip(words, words[1:]))
    return tokens


_PHD_TOKENS = {"phd", "doctorate", "doctoral"}
_MASTERS_STRONG = {"mtech", "msc", "mca", "mba", "master", "masters", "postgraduate", "mphil"}
_UNDERGRAD_STRONG = {"btech", "bsc", "bca", "bba", "bcom", "bachelor", "bachelors", "undergraduate"}
# Short forms that are also common words/abbreviations: only trusted when nothing stronger matched.
_MASTERS_WEAK = {"ms", "me"}
_UNDERGRAD_WEAK = {"be", "bs"}


def _degree_category(degree_str: str) -> str:
    """
    Categorizes degree into standardized academic levels using whole-word tokens:
    - undergrad: btech, be, bsc, bs, bca, bachelor, undergraduate
    - masters: mtech, me, ms, msc, mca, mba, master, postgraduate
    - phd: phd, doctorate, doctoral
    - other
    """
    t = _degree_tokens(degree_str)
    if t & _PHD_TOKENS:
        return "phd"
    if t & _MASTERS_STRONG:
        return "masters"
    if t & _UNDERGRAD_STRONG:
        return "undergrad"
    if t & _MASTERS_WEAK:
        return "masters"
    if t & _UNDERGRAD_WEAK:
        return "undergrad"
    return "other"


_COUNTRY_ALIASES = {
    "usa": "united states", "us": "united states", "u s": "united states", "u s a": "united states",
    "america": "united states", "uk": "united kingdom", "u k": "united kingdom", "england": "united kingdom",
    "uae": "united arab emirates",
}
_GLOBAL_COUNTRY_WORDS = {"worldwide", "global", "anywhere", "international"}


def _canonical_country(val: Optional[str]) -> str:
    norm = _normalize_string(val)
    return _COUNTRY_ALIASES.get(norm, norm)


def _country_allowed(student_country: str, allowed_entries: List[str]) -> bool:
    """Whole-word country match; a short name never matches by substring."""
    student_tokens = set(student_country.split())
    if not student_tokens:
        return False
    for entry in allowed_entries:
        canon = _canonical_country(entry)
        entry_tokens = set(canon.split())
        if entry_tokens & _GLOBAL_COUNTRY_WORDS or student_tokens <= entry_tokens:
            return True
    return False


# "country" is deliberately absent: ingestion infers eligible_countries from the location text, so a
# country match alone is not an employer requirement and can never make a listing ELIGIBLE.
_SUBSTANTIVE_FIELDS = {"academic_year", "grad_year", "degree", "cgpa", "backlogs", "work_auth"}

_CHECK_LABELS = {
    "academic_year": "year of study",
    "grad_year": "graduation year",
    "degree": "degree",
    "cgpa": "CGPA",
    "backlogs": "backlog status",
    "work_auth": "work authorization",
    "country": "country",
    "required_skills": "required skills",
}

# Countries/regions a listing location may name. Used only to contradict an inferred "India" match.
_NAMED_COUNTRIES = {
    "united states": ("united states", "usa", "u s a", "u s", "us"),
    "canada": ("canada",),
    "united kingdom": ("united kingdom", "uk", "u k", "england"),
    "germany": ("germany",),
    "france": ("france",),
    "ireland": ("ireland",),
    "netherlands": ("netherlands",),
    "singapore": ("singapore",),
    "australia": ("australia",),
    "united arab emirates": ("united arab emirates", "uae"),
}


def countries_named_in_location(location: Optional[str]) -> Set[str]:
    """Canonical countries explicitly named in a location string, e.g. 'Remote (United States | Canada)'.

    India is reported when the text names India or an Indian city. Whole-word matching only, so
    'Indiana' never reads as India and 'us' inside 'Austin' is ignored.
    """
    norm = f" {_normalize_string(location)} "
    found: Set[str] = set()
    for canon, names in _NAMED_COUNTRIES.items():
        if any(f" {n} " in norm for n in names):
            found.add(canon)
    if re.search(r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|noida|chennai|kolkata)\b", norm):
        found.add("india")
    return found


def _passed_check_labels(reasons: List[Dict[str, Any]]) -> List[str]:
    """Human labels of the checks that actually passed, in the order they ran."""
    out: List[str] = []
    for r in reasons:
        label = _CHECK_LABELS.get(r.get("field", ""))
        if r.get("status") == "pass" and label and label not in out:
            out.append(label)
    return out


def _has_substantive_requirements(reqs: OpportunityRequirementsOut) -> bool:
    return bool(
        reqs.eligible_academic_years
        or reqs.eligible_graduation_years
        or reqs.eligible_degree_types
        or reqs.eligible_countries
        or reqs.work_auth_required is True
        or reqs.min_gpa is not None
        or reqs.required_skills
        or reqs.no_active_backlogs is True
        or reqs.has_conflicting_requirements
        or (reqs.other_mandatory_requirements or "").strip()
        or reqs.unknown_requirements
    )


def _requirement_gpa_scale(reqs: OpportunityRequirementsOut) -> Optional[float]:
    """Scale of the listing's minimum grade; infers percent for large values, None when ambiguous."""
    if reqs.gpa_scale:
        return float(reqs.gpa_scale)
    min_gpa = float(reqs.min_gpa or 0)
    if min_gpa > 10.0:
        return 100.0
    if min_gpa <= 4.0:
        return None
    return 10.0


def evaluate_eligibility(
    opportunity: OpportunityOut,
    profile: Optional[UserOpportunityProfileIn],
) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Evaluates eligibility for a given opportunity and profile deterministically.

    Returns:
        (classification, explanation, reasons_list)
    """
    if profile is None:
        return (
            EligibilityClassification.INSUFFICIENT_INFORMATION,
            "No candidate profile found. Complete your profile in Resume Studio to evaluate verified eligibility.",
            [{"field": "profile", "status": "missing", "detail": "Candidate profile not configured in Resume Studio."}]
        )

    reqs: Optional[OpportunityRequirementsOut] = opportunity.requirements
    reasons: List[Dict[str, Any]] = []

    # Substantive data = something we can actually compare against the candidate. Preferred skills,
    # sponsorship flags, False-valued flags and free-text caveats are not comparable facts.
    if not reqs or not _has_substantive_requirements(reqs):
        reasons.append({
            "field": "requirements_data",
            "status": "unspecified",
            "detail": "The listing does not specify explicit academic year, degree, CGPA, or graduation cutoff requirements."
        })
        return (
            EligibilityClassification.INSUFFICIENT_INFORMATION,
            "Mandatory eligibility requirements cannot be extracted with sufficient confidence. Manual review required.",
            reasons
        )

    # 0. Check for Contradictory Requirements
    if reqs.has_conflicting_requirements:
        reasons.append({
            "field": "conflicting_requirements",
            "status": "unknown",
            "detail": "Listing contains contradictory or conflicting mandatory requirements. Manual review needed before confirming eligibility."
        })

    # 1. Academic Year Check
    academic_year_status = "pass"
    if reqs.eligible_academic_years:
        if profile.academic_year is None:
            reasons.append({
                "field": "academic_year",
                "status": "unknown",
                "detail": f"Position requires academic year(s) {plain.join_plain(reqs.eligible_academic_years)}, but your year is not set in profile."
            })
            academic_year_status = "unknown"
        elif profile.academic_year in reqs.eligible_academic_years:
            reasons.append({
                "field": "academic_year",
                "status": "pass",
                "detail": f"Your academic year ({profile.academic_year}) matches accepted years: {plain.join_plain(reqs.eligible_academic_years)}."
            })
        else:
            reasons.append({
                "field": "academic_year",
                "status": "fail",
                "detail": plain.year_fail(reqs.eligible_academic_years, profile.academic_year)
            })
            academic_year_status = "fail"

    # 2. Graduation Year Check (Cohort Matching)
    grad_year_status = "pass"
    if reqs.eligible_graduation_years:
        if profile.grad_year is None:
            reasons.append({
                "field": "grad_year",
                "status": "unknown",
                "detail": f"Target graduation batch is {plain.join_plain(reqs.eligible_graduation_years)}, but your graduation year is unset."
            })
            grad_year_status = "unknown"
        elif profile.grad_year in reqs.eligible_graduation_years:
            reasons.append({
                "field": "grad_year",
                "status": "pass",
                "detail": f"Your graduation year ({profile.grad_year}) matches eligible batch: {plain.join_plain(reqs.eligible_graduation_years)}."
            })
        else:
            reasons.append({
                "field": "grad_year",
                "status": "fail",
                "detail": plain.grad_year_fail(reqs.eligible_graduation_years, profile.grad_year)
            })
            grad_year_status = "fail"

    # 3. CGPA / Minimum Grade Check
    cgpa_status = "pass"
    if reqs.min_gpa is not None:
        req_scale = _requirement_gpa_scale(reqs)
        if req_scale is None:
            reasons.append({
                "field": "cgpa",
                "status": "unknown",
                "detail": f"Position requires a minimum grade of {reqs.min_gpa} but does not state its scale; cannot compare reliably."
            })
            cgpa_status = "unknown"
        elif profile.cgpa is None:
            reasons.append({
                "field": "cgpa",
                "status": "unknown",
                "detail": f"Position requires minimum CGPA of {reqs.min_gpa} (scale: {req_scale}), but your CGPA is unset."
            })
            cgpa_status = "unknown"
        else:
            user_scale = float(profile.cgpa_scale or 10.0)
            # Normalize to 10.0 scale for comparison
            normalized_req_gpa = (float(reqs.min_gpa) / req_scale) * 10.0
            normalized_user_gpa = (float(profile.cgpa) / user_scale) * 10.0

            if normalized_user_gpa >= normalized_req_gpa - 1e-4:
                reasons.append({
                    "field": "cgpa",
                    "status": "pass",
                    "detail": f"Your CGPA ({profile.cgpa}/{user_scale}) satisfies the minimum requirement of {reqs.min_gpa}/{req_scale}."
                })
            else:
                reasons.append({
                    "field": "cgpa",
                    "status": "fail",
                    "detail": plain.cgpa_fail(float(reqs.min_gpa), req_scale, profile.cgpa, user_scale)
                })
                cgpa_status = "fail"

    # 4. Degree Level & Specialization Check
    degree_status = "pass"
    if reqs.eligible_degree_types:
        if not profile.degree:
            reasons.append({
                "field": "degree",
                "status": "unknown",
                "detail": f"Requires degree type ({plain.join_plain(reqs.eligible_degree_types)}), but degree is unconfigured in profile."
            })
            degree_status = "unknown"
        else:
            norm_user_deg = _normalize_string(profile.degree)
            user_cat = _degree_category(profile.degree)

            allowed_norms = [_normalize_string(d) for d in reqs.eligible_degree_types]
            allowed_cats = {_degree_category(d) for d in reqs.eligible_degree_types}

            # Check if degree categories mismatch definitively (e.g. requires PhD, candidate is undergrad)
            if user_cat != "other" and allowed_cats and user_cat not in allowed_cats and "other" not in allowed_cats:
                reasons.append({
                    "field": "degree",
                    "status": "fail",
                    "detail": plain.degree_fail(sorted(allowed_cats), profile.degree, user_cat)
                })
                degree_status = "fail"
            else:
                # Direct string or category match
                direct_match = any(
                    a in norm_user_deg or norm_user_deg in a or _degree_category(a) == user_cat
                    for a in allowed_norms
                )
                if direct_match:
                    reasons.append({
                        "field": "degree",
                        "status": "pass",
                        "detail": f"Degree ({profile.degree}) aligns with accepted degrees: {plain.join_plain(reqs.eligible_degree_types)}."
                    })
                else:
                    reasons.append({
                        "field": "degree",
                        "status": "unknown",
                        "detail": f"Accepted degree types: {plain.join_plain(reqs.eligible_degree_types)}. Profile degree is {profile.degree}. Equivalence requires verification."
                    })
                    degree_status = "unknown"

    # 5. Backlogs Check
    backlog_status = "pass"
    if reqs.no_active_backlogs is True:
        if profile.active_backlogs is None:
            reasons.append({
                "field": "backlogs",
                "status": "unknown",
                "detail": "Listing explicitly prohibits active backlogs; candidate backlog status is unconfirmed."
            })
            backlog_status = "unknown"
        elif profile.active_backlogs > 0:
            reasons.append({
                "field": "backlogs",
                "status": "fail",
                "detail": f"Listing requires 0 active backlogs. Profile indicates {profile.active_backlogs} active backlogs."
            })
            backlog_status = "fail"
        else:
            reasons.append({
                "field": "backlogs",
                "status": "pass",
                "detail": "Candidate has 0 active backlogs, satisfying employer requirement."
            })

    # 6. Country & Geographic Residence Check
    country_status = "pass"
    if reqs.eligible_countries:
        student_country = _canonical_country(profile.country_of_residence or profile.country_of_study)
        if not student_country:
            # Nothing to compare against: not a verified fact either way.
            reasons.append({
                "field": "country",
                "status": "unspecified",
                "detail": f"Position is restricted to {plain.join_plain(reqs.eligible_countries)}; your country is not set in your profile."
            })
            country_status = "unspecified"
        elif _country_allowed(student_country, reqs.eligible_countries):
            named = countries_named_in_location(opportunity.location)
            student_named = student_country in named
            if named and not student_named and not any(
                set(_canonical_country(e).split()) & _GLOBAL_COUNTRY_WORDS for e in reqs.eligible_countries
            ):
                # The stored country list says yes, but the published location names other countries only.
                shown = ", ".join(sorted(c.title() for c in named))
                reasons.append({
                    "field": "country",
                    "status": "fail",
                    "detail": f"The listing location names {shown}, not {student_country.title()}."
                })
                country_status = "fail"
            else:
                reasons.append({
                    "field": "country",
                    "status": "pass",
                    "detail": f"Applicant residence ({student_country.title()}) satisfies geographic criteria: {plain.join_plain(reqs.eligible_countries)}."
                })
        else:
            reasons.append({
                "field": "country",
                "status": "fail",
                "detail": plain.country_fail(reqs.eligible_countries, student_country.title())
            })
            country_status = "fail"

    # 7. Work Authorization & Sponsorship Check
    work_auth_status = "pass"
    work_auth_verified = False
    if reqs.work_auth_required is True:
        target_country = (opportunity.country or "India").strip().lower()
        candidate_auth = [_canonical_country(a) for a in (profile.work_authorization or "").replace(";", ",").split(",")]
        candidate_auth = [a for a in candidate_auth if a]
        has_auth = _country_allowed(_canonical_country(target_country), candidate_auth) if candidate_auth else None

        # If international on-site or hybrid role where work authorization is required
        if target_country not in ("india", "remote") and opportunity.work_arrangement != "remote":
            if reqs.sponsorship_available is False:
                # Employer explicitly does not sponsor
                if has_auth is None:
                    reasons.append({
                        "field": "work_auth",
                        "status": "unknown",
                        "detail": f"Requires work authorization in {opportunity.country} and employer does not sponsor; your work authorization is not set in your profile."
                    })
                    work_auth_status = "unknown"
                elif not has_auth:
                    reasons.append({
                        "field": "work_auth",
                        "status": "fail",
                        "detail": f"Requires work authorization in {opportunity.country}. Employer explicitly does not offer visa sponsorship."
                    })
                    work_auth_status = "fail"
                else:
                    work_auth_verified = True
                    reasons.append({
                        "field": "work_auth",
                        "status": "pass",
                        "detail": f"Candidate possesses verified work authorization for {opportunity.country}."
                    })
            elif reqs.sponsorship_available is True:
                reasons.append({
                    "field": "work_auth",
                    "status": "pass",
                    "detail": "International visa sponsorship is explicitly confirmed available by employer."
                })
            else:
                # Sponsorship policy is unknown / unconfirmed
                if not has_auth:
                    reasons.append({
                        "field": "work_auth",
                        "status": "unknown",
                        "detail": f"Position requires work authorization in {opportunity.country}; visa sponsorship availability is unconfirmed."
                    })
                    work_auth_status = "unknown"
                else:
                    work_auth_verified = True
                    reasons.append({
                        "field": "work_auth",
                        "status": "pass",
                        "detail": f"Candidate authorized to work in {opportunity.country}."
                    })
        else:
            # Domestic or remote position
            reasons.append({
                "field": "work_auth",
                "status": "pass",
                "detail": "Work authorization satisfied in domestic (India) or remote jurisdiction."
            })

    # 8. Mandatory Skills Check
    # Rule: If skills are marked MANDATORY in requirements, lack of proficiency produces 'unknown' or 'fail'
    skills_status = "pass"
    if reqs.required_skills:
        req_skills_norm = {_normalize_string(s) for s in reqs.required_skills if s.strip()}
        user_skills_norm = {_normalize_string(s) for s in (profile.skills or []) if s.strip()}

        missing_mandatory = [s for s in req_skills_norm if not any(s in u or u in s for u in user_skills_norm)]
        matched_mandatory = [s for s in req_skills_norm if any(s in u or u in s for u in user_skills_norm)]

        if missing_mandatory:
            reasons.append({
                "field": "required_skills",
                "status": "unknown",
                "detail": f"This role asks for skills you have not listed yet: {plain.join_plain(missing_mandatory)}. Add them to your profile if you have them."
            })
            skills_status = "unknown"
        else:
            reasons.append({
                "field": "required_skills",
                "status": "pass",
                "detail": f"All published mandatory skills satisfied: [{', '.join(matched_mandatory)}]."
            })

    # 9. Preferred Skills Check (Informational ONLY — Never rejects or blocks ELIGIBLE)
    if reqs.preferred_skills:
        pref_norm = {_normalize_string(s) for s in reqs.preferred_skills if s.strip()}
        user_skills_norm = {_normalize_string(s) for s in (profile.skills or []) if s.strip()}
        matched_pref = [s for s in pref_norm if any(s in u or u in s for u in user_skills_norm)]
        reasons.append({
            "field": "preferred_skills",
            "status": "info",
            "detail": f"Preferred qualifications matched ({len(matched_pref)}/{len(pref_norm)}): {matched_pref if matched_pref else 'None (preferred qualifications do not affect mandatory eligibility)'}."
        })

    # 10. Free-text / unparsed mandatory requirements can never be verified automatically
    caveats = [c for c in [(reqs.other_mandatory_requirements or "").strip(), *reqs.unknown_requirements] if c and str(c).strip()]
    if caveats:
        reasons.append({
            "field": "other_requirements",
            "status": "unknown",
            "detail": f"Additional listing requirements need manual review: {'; '.join(str(c) for c in caveats)[:300]}."
        })

    # -----------------------------------------------------------------------
    # Decision Matrix
    # -----------------------------------------------------------------------
    # 1. Any confirmed hard failure => INELIGIBLE
    failed_reasons = [r for r in reasons if r.get("status") == "fail"]
    if failed_reasons:
        failed_fields = [r["field"] for r in failed_reasons]
        user_cat = _degree_category(profile.degree) if profile.degree else "other"
        allowed_cats = sorted({_degree_category(d) for d in reqs.eligible_degree_types})
        explanation = plain.ineligible_explanation(
            [str(r.get("detail", "")).strip() for r in failed_reasons],
            plain.next_step(failed_fields, allowed_cats, profile.degree, user_cat),
        )
        return (EligibilityClassification.INELIGIBLE, explanation, reasons)

    # 2. Conflicting requirements or unknown mandatory requirements => POTENTIAL_MATCH (POTENTIALLY_ELIGIBLE)
    # STRICTNESS RULE: To be truly ELIGIBLE (Strong Match), critical criteria must be explicitly 'pass'.
    # If key fields are 'unknown' or missing, it's only a Potential Match.
    critical_fields = ["academic_year", "grad_year", "degree"]
    missing_critical = [r["field"] for r in reasons if r.get("status") == "unknown" and r["field"] in critical_fields]

    unknown_reasons = [r for r in reasons if r.get("status") == "unknown"]
    # ELIGIBLE needs at least one real pass on a substantive check; with none, nothing was verified.
    has_substantive_pass = work_auth_verified or any(
        r.get("status") == "pass" and r["field"] in _SUBSTANTIVE_FIELDS and r["field"] != "work_auth"
        for r in reasons
    )
    has_substantive_unknown = any(r["field"] in _SUBSTANTIVE_FIELDS for r in unknown_reasons)
    country_passed = any(r["field"] == "country" and r.get("status") == "pass" for r in reasons)
    if (
        not has_substantive_pass and not has_substantive_unknown and not reqs.has_conflicting_requirements
        and country_passed
    ):
        # Only the (possibly inferred) country matched. That is not an employer requirement.
        return (
            EligibilityClassification.POTENTIAL_MATCH,
            "Possible match: Requirements not published by the employer. Only your country was compared, "
            "so check the listing for degree, year and other conditions before applying.",
            reasons,
        )
    if not has_substantive_pass and not has_substantive_unknown and not reqs.has_conflicting_requirements:
        return (
            EligibilityClassification.INSUFFICIENT_INFORMATION,
            "Mandatory eligibility requirements cannot be extracted with sufficient confidence. Manual review required.",
            reasons,
        )
    if unknown_reasons or reqs.has_conflicting_requirements or missing_critical or country_status == "unspecified":
        unknown_fields = [u["field"] for u in unknown_reasons] or ["country"]
        explanation = f"Possible match: Aligns with profile, but requires verification of: {', '.join(unknown_fields)}."
        return (EligibilityClassification.POTENTIAL_MATCH, explanation, reasons)

    # 3. All known mandatory requirements verified & passed. Name only the checks that were actually made.
    checked = _passed_check_labels(reasons)
    explanation = (
        f"Confirmed eligible (Strong match): your {', '.join(checked)} meet the requirements the employer published."
        if checked else "Confirmed eligible (Strong match)."
    )
    return (EligibilityClassification.ELIGIBLE, explanation, reasons)
