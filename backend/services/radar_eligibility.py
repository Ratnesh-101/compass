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


def _degree_category(degree_str: str) -> str:
    """
    Categorizes degree into standardized academic levels:
    - undergrad: btech, be, bsc, bs, bca, bachelor, undergraduate
    - masters: mtech, me, ms, msc, mca, mba, master, postgraduate
    - phd: phd, doctorate, doctoral
    - unknown
    """
    d = _normalize_string(degree_str)
    if any(k in d for k in ["phd", "doctorate", "doctoral"]):
        return "phd"
    if any(k in d for k in ["mtech", "m tech", "me", "msc", "m sc", "ms", "mca", "mba", "master", "postgraduate"]):
        return "masters"
    if any(k in d for k in ["btech", "b tech", "be", "b e", "bsc", "b sc", "bs", "bca", "bachelor", "undergraduate"]):
        return "undergrad"
    return "other"


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

    # If opportunity has zero requirement data or completely empty
    if not reqs or (
        not reqs.eligible_academic_years
        and not reqs.eligible_graduation_years
        and not reqs.eligible_degree_types
        and not reqs.eligible_countries
        and reqs.work_auth_required is None
        and reqs.min_gpa is None
        and not reqs.required_skills
        and not reqs.no_active_backlogs
        and not reqs.has_conflicting_requirements
    ):
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
                "detail": f"Position requires academic year(s) {reqs.eligible_academic_years}, but your year is not set in profile."
            })
            academic_year_status = "unknown"
        elif profile.academic_year in reqs.eligible_academic_years:
            reasons.append({
                "field": "academic_year",
                "status": "pass",
                "detail": f"Your academic year ({profile.academic_year}) matches accepted years: {reqs.eligible_academic_years}."
            })
        else:
            reasons.append({
                "field": "academic_year",
                "status": "fail",
                "detail": f"Position targets year(s) {reqs.eligible_academic_years}; your profile indicates year {profile.academic_year}."
            })
            academic_year_status = "fail"

    # 2. Graduation Year Check (Cohort Matching)
    grad_year_status = "pass"
    if reqs.eligible_graduation_years:
        if profile.grad_year is None:
            reasons.append({
                "field": "grad_year",
                "status": "unknown",
                "detail": f"Target graduation batch is {reqs.eligible_graduation_years}, but your graduation year is unset."
            })
            grad_year_status = "unknown"
        elif profile.grad_year in reqs.eligible_graduation_years:
            reasons.append({
                "field": "grad_year",
                "status": "pass",
                "detail": f"Your graduation year ({profile.grad_year}) matches eligible batch: {reqs.eligible_graduation_years}."
            })
        else:
            reasons.append({
                "field": "grad_year",
                "status": "fail",
                "detail": f"Requires graduation in {reqs.eligible_graduation_years}. Your profile indicates {profile.grad_year}."
            })
            grad_year_status = "fail"

    # 3. CGPA / Minimum Grade Check
    cgpa_status = "pass"
    if reqs.min_gpa is not None:
        if profile.cgpa is None:
            reasons.append({
                "field": "cgpa",
                "status": "unknown",
                "detail": f"Position requires minimum CGPA of {reqs.min_gpa} (scale: {reqs.gpa_scale or 10.0}), but your CGPA is unset."
            })
            cgpa_status = "unknown"
        else:
            req_scale = float(reqs.gpa_scale or 10.0)
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
                    "detail": f"Requires minimum CGPA of {reqs.min_gpa}/{req_scale}. Your verified CGPA is {profile.cgpa}/{user_scale}."
                })
                cgpa_status = "fail"

    # 4. Degree Level & Specialization Check
    degree_status = "pass"
    if reqs.eligible_degree_types:
        if not profile.degree:
            reasons.append({
                "field": "degree",
                "status": "unknown",
                "detail": f"Requires degree type ({reqs.eligible_degree_types}), but degree is unconfigured in profile."
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
                    "detail": f"Requires degree in {reqs.eligible_degree_types} ({', '.join(allowed_cats)}); candidate degree is {profile.degree} ({user_cat})."
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
                        "detail": f"Degree ({profile.degree}) aligns with accepted degrees: {reqs.eligible_degree_types}."
                    })
                else:
                    reasons.append({
                        "field": "degree",
                        "status": "unknown",
                        "detail": f"Accepted degree types: {reqs.eligible_degree_types}. Profile degree is {profile.degree}. Equivalence requires verification."
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
        student_country = (profile.country_of_residence or profile.country_of_study or "India").lower()
        allowed_countries = [c.lower() for c in reqs.eligible_countries]
        is_allowed = any(student_country in c or c in student_country for c in allowed_countries)
        india_in_allowed = any("india" in c for c in allowed_countries)

        if not is_allowed and not (opportunity.is_india_eligible and india_in_allowed):
            reasons.append({
                "field": "country",
                "status": "fail",
                "detail": f"Position is restricted to applicants in {reqs.eligible_countries}. Candidate is based in {profile.country_of_residence or 'India'}."
            })
            country_status = "fail"
        elif is_allowed or (opportunity.is_india_eligible and india_in_allowed):
            reasons.append({
                "field": "country",
                "status": "pass",
                "detail": f"Applicant residence ({student_country.title()}) satisfies geographic criteria: {reqs.eligible_countries}."
            })
        else:
            reasons.append({
                "field": "country",
                "status": "unknown",
                "detail": f"Country eligibility ({reqs.eligible_countries}) requires verification for applicant location."
            })
            country_status = "unknown"

    # 7. Work Authorization & Sponsorship Check
    work_auth_status = "pass"
    if reqs.work_auth_required is True:
        target_country = (opportunity.country or "India").strip().lower()
        candidate_auth = (profile.work_authorization or "India").strip().lower()

        # If international on-site or hybrid role where work authorization is required
        if target_country not in ("india", "remote") and opportunity.work_arrangement != "remote":
            if reqs.sponsorship_available is False:
                # Employer explicitly does not sponsor
                if target_country not in candidate_auth:
                    reasons.append({
                        "field": "work_auth",
                        "status": "fail",
                        "detail": f"Requires work authorization in {opportunity.country}. Employer explicitly does not offer visa sponsorship."
                    })
                    work_auth_status = "fail"
                else:
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
                if target_country not in candidate_auth:
                    reasons.append({
                        "field": "work_auth",
                        "status": "unknown",
                        "detail": f"Position requires work authorization in {opportunity.country}; visa sponsorship availability is unconfirmed."
                    })
                    work_auth_status = "unknown"
                else:
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
                "detail": f"Mandatory skills require confirmation: missing [{', '.join(missing_mandatory)}]. Profile lists [{', '.join(user_skills_norm)}]."
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

    # -----------------------------------------------------------------------
    # Decision Matrix
    # -----------------------------------------------------------------------
    # 1. Any confirmed hard failure => INELIGIBLE
    failed_reasons = [r for r in reasons if r.get("status") == "fail"]
    if failed_reasons:
        failed_fields = [r["field"] for r in failed_reasons]
        explanation = f"Ineligible: Mandatory requirement(s) for {', '.join(failed_fields)} do not match your verified profile."
        return (EligibilityClassification.INELIGIBLE, explanation, reasons)

    # 2. Conflicting requirements or unknown mandatory requirements => POTENTIAL_MATCH (POTENTIALLY_ELIGIBLE)
    unknown_reasons = [r for r in reasons if r.get("status") == "unknown"]
    if unknown_reasons or reqs.has_conflicting_requirements:
        unknown_fields = [u["field"] for u in unknown_reasons]
        explanation = f"Possible match: Aligns with profile, but requires verification of: {', '.join(unknown_fields)}."
        return (EligibilityClassification.POTENTIAL_MATCH, explanation, reasons)

    # 3. All known mandatory requirements verified & passed
    explanation = "Confirmed eligible (Strong match): Your degree, academic cohort, CGPA, and authorization satisfy all mandatory requirements."
    return (EligibilityClassification.ELIGIBLE, explanation, reasons)
