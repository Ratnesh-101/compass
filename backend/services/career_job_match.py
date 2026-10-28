"""
Compass — Career Copilot Job Description Analysis & Requirement Matching Service.

Extracts structured requirements (mandatory, preferred, responsibilities, eligibility)
from job descriptions, compares them against the candidate's verified Master Profile,
and computes honest match evidence without hallucination or assuming missing evidence equals inability.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.models_career import (
    JobAnalysisReport,
    JobMatchEvidence,
    ResumeContent,
)
from backend.models_radar import OpportunityOut

logger = logging.getLogger("compass.services.career_job_match")


def extract_job_sections(job_text: str) -> Dict[str, List[str]]:
    """
    Extracts structured requirements from raw job description text.
    Distinguishes mandatory requirements from preferred qualifications and responsibilities.
    """
    lines = [line.strip() for line in job_text.splitlines() if line.strip()]

    mandatory: List[str] = []
    preferred: List[str] = []
    responsibilities: List[str] = []
    skills: List[str] = []

    current_section = "overview"

    for line in lines:
        line_low = line.lower()
        if any(h in line_low for h in ("basic qualifications", "minimum qualifications", "required qualifications", "must have", "requirements")):
            current_section = "mandatory"
            continue
        elif any(h in line_low for h in ("preferred qualifications", "desired qualifications", "bonus", "nice to have", "plus")):
            current_section = "preferred"
            continue
        elif any(h in line_low for h in ("responsibilities", "what you will do", "what you'll do", "the role", "job description")):
            current_section = "responsibilities"
            continue
        elif any(h in line_low for h in ("skills required", "tech stack", "technologies")):
            current_section = "skills"
            continue

        clean_item = line.strip(" -*•·")
        if not clean_item or len(clean_item) < 3:
            continue

        if current_section == "mandatory":
            if len(mandatory) < 15:
                mandatory.append(clean_item)
        elif current_section == "preferred":
            if len(preferred) < 15:
                preferred.append(clean_item)
        elif current_section == "responsibilities":
            if len(responsibilities) < 15:
                responsibilities.append(clean_item)
        elif current_section == "skills":
            for tok in re.split(r"[,•|\n]+", clean_item):
                s = tok.strip(" -:*•")
                if s and 1 < len(s) < 35 and s not in skills:
                    skills.append(s)

    return {
        "mandatory": mandatory,
        "preferred": preferred,
        "responsibilities": responsibilities,
        "skills": skills,
    }


def analyze_job_and_match(
    opportunity: OpportunityOut,
    master: ResumeContent,
    custom_description: Optional[str] = None,
) -> JobAnalysisReport:
    """
    Analyzes an opportunity's requirements and maps evidence from the candidate's master profile.
    Separates explicit requirements from inferred preferences, evaluates matches truthfully,
    and identifies genuine gaps without inventing qualifications.
    """
    raw_desc = custom_description or opportunity.description or ""
    full_text = f"{opportunity.role_title}\n{opportunity.category}\n{raw_desc}"

    sections = extract_job_sections(full_text)
    mandatory = sections["mandatory"]
    preferred = sections["preferred"]
    responsibilities = sections["responsibilities"]

    # Gather explicit required skills from opportunity requirements model if present
    req_skills: Set[str] = set()
    if opportunity.requirements and opportunity.requirements.required_skills:
        req_skills.update(s.strip() for s in opportunity.requirements.required_skills if s.strip())
    req_skills.update(sections["skills"])

    # If no explicit skills found in section headers, scan for standard tech keywords in description
    if not req_skills:
        common_tech = ["Python", "JavaScript", "React", "Node.js", "PostgreSQL", "FastAPI", "Docker", "Git", "SQL", "C++", "Java", "AWS", "PyTorch"]
        for tech in common_tech:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(tech) + r"(?![A-Za-z0-9_])", full_text, re.IGNORECASE):
                req_skills.add(tech)

    skills_list = sorted(list(req_skills))

    # Check if candidate profile is complete
    is_empty_profile = (
        not master
        or (not master.skills and not master.projects and not master.education and not (master.full_name or "").strip())
    )

    if is_empty_profile:
        gap_actions = [
            {
                "skill": s,
                "learning_resource_type": "Official documentation, interactive courses, and hands-on tutorials",
                "project_idea": f"Create a demonstration project showcasing practical {s} implementation with test suites",
                "evidence_appearance": f"Public GitHub repository with verifiable commits and CI/CD demonstrating {s}",
            }
            for s in skills_list
        ]
        return JobAnalysisReport(
            opportunity_id=opportunity.id,
            role_title=opportunity.role_title,
            company_name=opportunity.company_name,
            mandatory_qualifications=mandatory,
            preferred_qualifications=preferred,
            responsibilities=responsibilities,
            required_skills=skills_list,
            location_and_eligibility={
                "location": opportunity.location or "Not specified",
                "is_remote": getattr(opportunity, "work_arrangement", "") == "remote",
                "target_years": getattr(opportunity.requirements, "eligible_graduation_years", []) if opportunity.requirements else [],
            },
            matches=[],
            match_score=0.0,
            summary_verdict="Complete your profile to view your skill overlap estimate and personalized action plan.",
            missing_critical_skills=skills_list,
            skill_overlap_estimate=0.0,
            matched_skills=[],
            missing_skills=skills_list,
            partial_skills=[],
            gap_actions=gap_actions,
            has_complete_profile=False,
            profile_missing_message="Complete your profile to view skill overlap analysis. No verified skills found.",
            formula_explanation="Skill overlap estimate = (matched + 0.5 * partial) / total required skills",
        )

    # Build Master Profile evidence index
    master_skills_norm = {s.strip().lower(): s for s in master.skills}
    learning_skills_norm = {s.strip().lower(): s for s in getattr(master, "learning_skills", [])}
    master_projects_text = " ".join(
        f"{p.title} {p.description} {' '.join(p.highlights)} {' '.join(p.technologies)}"
        for p in master.projects
    ).lower()

    matches: List[JobMatchEvidence] = []
    matched_skills: List[str] = []
    partial_skills: List[str] = []
    missing_skills: List[str] = []
    gap_actions: List[Dict[str, Any]] = []

    # 1. Match Required Skills
    for skill in skills_list:
        s_low = skill.lower()
        if s_low in master_skills_norm:
            matched_skills.append(skill)
            matches.append(
                JobMatchEvidence(
                    requirement=skill,
                    category="technical_skill",
                    is_mandatory=True,
                    match_status="supported",
                    supporting_facts=[f"Verified in Master Profile: '{master_skills_norm[s_low]}'"],
                    reasoning=f"Candidate has verified mastery of {skill}.",
                    confidence=1.0,
                )
            )
        elif s_low in master_projects_text or s_low in learning_skills_norm:
            partial_skills.append(skill)
            source = "learning list" if s_low in learning_skills_norm else "project implementations"
            matches.append(
                JobMatchEvidence(
                    requirement=skill,
                    category="technical_skill",
                    is_mandatory=True,
                    match_status="partial",
                    supporting_facts=[f"Mentioned in candidate {source}."],
                    reasoning=f"Skill {skill} is tracked in candidate {source} but not yet a verified primary competency.",
                    confidence=0.8,
                )
            )
        else:
            missing_skills.append(skill)
            gap_actions.append({
                "skill": skill,
                "learning_resource_type": "Official documentation, interactive courses, and hands-on tutorials",
                "project_idea": f"Create a demonstration project showcasing practical {skill} implementation with test suites",
                "evidence_appearance": f"Public GitHub repository with verifiable commits and CI/CD demonstrating {skill}",
            })
            matches.append(
                JobMatchEvidence(
                    requirement=skill,
                    category="technical_skill",
                    is_mandatory=True,
                    match_status="missing_evidence",
                    supporting_facts=[],
                    reasoning=(
                        f"Skill '{skill}' is required by {opportunity.company_name} but absent from verified master profile. "
                        "Do not fabricate — deliberate candidate action required to verify."
                    ),
                    confidence=0.9,
                )
            )

    # 2. Match Mandatory Qualifications
    for q in mandatory:
        q_low = q.lower()
        # Education match check
        if any(term in q_low for term in ("degree", "bachelor", "b.tech", "computer science")):
            has_edu = len(master.education) > 0
            if has_edu:
                edu = master.education[0]
                matches.append(
                    JobMatchEvidence(
                        requirement=q,
                        category="qualification",
                        is_mandatory=True,
                        match_status="supported",
                        supporting_facts=[f"Education: {edu.degree} at {edu.institution}"],
                        reasoning="Candidate academic credentials satisfy degree requirements.",
                        confidence=1.0,
                    )
                )
            else:
                matches.append(
                    JobMatchEvidence(
                        requirement=q,
                        category="qualification",
                        is_mandatory=True,
                        match_status="missing_evidence",
                        supporting_facts=[],
                        reasoning="Candidate profile does not contain verified education records.",
                        confidence=0.8,
                    )
                )

    # Compute honest skill overlap estimate (0 - 100)
    total_eval = max(len(skills_list), 1)
    skill_overlap = round(min(100.0, ((len(matched_skills) + 0.5 * len(partial_skills)) / total_eval) * 100.0), 1)

    # Transparent, non-promising verdict
    if skill_overlap >= 80:
        verdict = f"Skill overlap estimate: {skill_overlap}%. High requirement coverage with {len(matched_skills)} verified and {len(partial_skills)} partial competencies."
    elif skill_overlap >= 50:
        verdict = f"Skill overlap estimate: {skill_overlap}%. Moderate requirement coverage: core skills verified with {len(missing_skills)} actionable skill gaps."
    else:
        verdict = f"Skill overlap estimate: {skill_overlap}%. Foundational overlap: {len(missing_skills)} required skills identified for active skill building."

    return JobAnalysisReport(
        opportunity_id=opportunity.id,
        role_title=opportunity.role_title,
        company_name=opportunity.company_name,
        mandatory_qualifications=mandatory,
        preferred_qualifications=preferred,
        responsibilities=responsibilities,
        required_skills=skills_list,
        location_and_eligibility={
            "location": opportunity.location or "Not specified",
            "is_remote": getattr(opportunity, "work_arrangement", "") == "remote",
            "target_years": getattr(opportunity.requirements, "eligible_graduation_years", []) if opportunity.requirements else [],
        },
        matches=matches,
        match_score=skill_overlap,
        summary_verdict=verdict,
        missing_critical_skills=missing_skills,
        skill_overlap_estimate=skill_overlap,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        partial_skills=partial_skills,
        gap_actions=gap_actions,
        has_complete_profile=True,
        profile_missing_message=None,
        formula_explanation="Skill overlap estimate = (matched + 0.5 * partial) / total required skills",
    )

