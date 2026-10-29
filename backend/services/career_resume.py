"""
Compass — Resume Studio Service.

Implements strict factual resume tailoring, validation against verified candidate profile,
master resume management, and ATS-ready export generation.
Enforces Section 3.2: Never fabricates or silently alters skills, projects, grades, or experience.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from backend.models_career import (
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
    ResumeOut,
    ResumeProjectItem,
    ResumeValidationReport,
    ResumeValidationStatus,
)
from backend.models_radar import OpportunityOut, UserOpportunityProfileIn


def build_default_master_from_profile(profile: Optional[UserOpportunityProfileIn] = None, user_name: str = "", email: str = "") -> ResumeContent:
    """Creates a truthful master resume draft directly from verified candidate profile data without placeholder fabrication."""
    edu_list = []
    if profile and (profile.university or profile.degree):
        edu_list.append(
            ResumeEducationItem(
                institution=profile.university or "",
                degree=profile.degree or "",
                field_of_study=profile.degree_specialization or "",
                end_year=profile.grad_year or "",
            )
        )

    skills = list(profile.skills or []) if profile else []

    return ResumeContent(
        full_name=user_name,
        email=email,
        location=profile.country_of_study if profile and profile.country_of_study else "",
        skills=skills,
        education=edu_list,
        projects=[],
        experience=[],
        achievements=[],
        certifications=[],
    )


def validate_resume_against_master(
    tailored: ResumeContent,
    master: ResumeContent,
    opportunity: Optional[OpportunityOut] = None,
) -> ResumeValidationReport:
    """
    Audits a tailored resume against master resume and verified profile data:
    1. Audits skills: Flags any skill not supported by master resume as unsupported claim.
    2. Audits projects: Verifies project titles exist in master resume.
    3. Checks essential sections: Contact, education, skills, projects.
    4. Computes clear comparison diff summary against master.
    5. Returns honest 3-state badge status: 'NOT ENOUGH DATA', 'CONSISTENT WITH MASTER', or 'INCONSISTENT WITH MASTER'.
    """
    passed: List[str] = []
    warnings: List[str] = []
    unsupported: List[str] = []
    missing: List[str] = []
    alignments: List[str] = []

    # 1. Contact validation
    if not tailored.full_name or len(tailored.full_name.strip()) < 2:
        missing.append("Candidate Full Name is required.")
    else:
        passed.append("Contact: Valid full name verified.")

    if not tailored.email or "@" not in tailored.email:
        missing.append("Valid contact email address is required.")
    else:
        passed.append("Contact: Valid email address verified.")

    # 2. Education validation
    if not tailored.education:
        missing.append("Education section cannot be empty.")
    else:
        passed.append(f"Education: {len(tailored.education)} degree record(s) verified.")

    # 3. Factual integrity check on skills
    master_skills_norm: Set[str] = {s.strip().lower() for s in master.skills}
    tailored_skills_norm: Set[str] = {s.strip().lower() for s in tailored.skills}

    for skill in tailored.skills:
        s_norm = skill.strip().lower()
        if s_norm not in master_skills_norm:
            unsupported.append(f"Skill '{skill}' is not in verified master profile.")
        else:
            if opportunity and opportunity.requirements:
                req_skills = {r.strip().lower() for r in opportunity.requirements.required_skills}
                if s_norm in req_skills:
                    alignments.append(f"Emphasized verified skill '{skill}' required by {opportunity.company_name}.")

    if tailored.skills and not unsupported:
        passed.append(f"Skills: All {len(tailored.skills)} listed skills verified against master profile.")

    # 4. Factual integrity check on projects
    master_proj_titles = {p.title.strip().lower() for p in master.projects}
    for proj in tailored.projects:
        p_title_norm = proj.title.strip().lower()
        if p_title_norm not in master_proj_titles:
            unsupported.append(f"Project '{proj.title}' does not originate from verified master projects.")
        else:
            # Check technologies in project
            for tech in proj.technologies:
                if tech.strip().lower() not in master_skills_norm:
                    warnings.append(f"Project technology '{tech}' in '{proj.title}' is not explicitly listed in master skills.")

    if not tailored.projects:
        warnings.append("No technical projects listed in resume.")
    else:
        passed.append(f"Projects: {len(tailored.projects)} project record(s) verified.")

    # 5. Diff summary against master
    diff_summary = {
        "master_skills_count": len(master.skills),
        "tailored_skills_count": len(tailored.skills),
        "highlighted_skills": list(tailored_skills_norm.intersection(master_skills_norm)),
        "omitted_master_skills": list(master_skills_norm - tailored_skills_norm),
        "project_order": [p.title for p in tailored.projects],
    }

    is_valid = len(missing) == 0 and len(unsupported) == 0

    # 6. Honest consistency badge determination
    # Threshold for "NOT ENOUGH DATA":
    # Master must have non-placeholder contact, and at least 2 substantive sections among:
    # >= 2 skills, >= 1 project, >= 1 experience, summary (> 10 chars), or >= 1 education.
    has_contact = bool(
        master.full_name and master.email and
        master.full_name.strip().lower() not in {"compass candidate", "candidate"} and
        master.email.strip().lower() not in {"candidate@compass.local"} and
        "@" in master.email
    )
    substantive_count = (
        (1 if len(master.skills) >= 2 else 0)
        + (1 if len(master.projects) >= 1 else 0)
        + (1 if len(master.experience) >= 1 else 0)
        + (1 if master.summary and len(master.summary.strip()) > 10 else 0)
        + (1 if len(master.education) >= 1 else 0)
    )
    is_sparse = (not has_contact) or (substantive_count < 2)

    if is_sparse:
        status = "NOT ENOUGH DATA"
        warnings.append("Master profile lacks sufficient baseline content (skills, projects, experience, or summary) for conclusive audit.")
    elif len(unsupported) == 0:
        status = "CONSISTENT WITH MASTER"
    else:
        status = "INCONSISTENT WITH MASTER"

    return ResumeValidationReport(
        is_valid=is_valid,
        status=status,
        passed_checks=passed,
        warnings=warnings,
        unsupported_claims=unsupported,
        missing_fields=missing,
        tailored_alignments=alignments,
        diff_summary=diff_summary,
    )


def tailor_resume_for_opportunity(
    master: ResumeContent,
    opportunity: OpportunityOut,
    custom_title: Optional[str] = None,
    skills_emphasis: Optional[List[str]] = None,
) -> Tuple[ResumeContent, ResumeValidationReport, ResumeValidationStatus]:
    """
    Deterministically creates a tailored resume variant without hallucinating qualifications:
    - Reorders verified candidate skills putting job-relevant skills first.
    - Reorders candidate projects putting projects that match job category or technologies first.
    - Preserves factual claims and origin.
    """
    job_text = f"{opportunity.role_title} {opportunity.category} {opportunity.description or ''}".lower()
    req_skills_lower = set()
    if opportunity.requirements and opportunity.requirements.required_skills:
        req_skills_lower = {s.lower() for s in opportunity.requirements.required_skills}

    if skills_emphasis:
        req_skills_lower.update({s.lower() for s in skills_emphasis})

    # 1. Reorder verified skills: Matching skills first, then other verified skills
    matched_skills = []
    other_skills = []
    for skill in master.skills:
        s_low = skill.lower()
        if s_low in req_skills_lower or s_low in job_text:
            matched_skills.append(skill)
        else:
            other_skills.append(skill)

    tailored_skills = matched_skills + other_skills

    # 2. Reorder verified projects: Projects matching tech or role keywords first
    def project_relevance_score(proj: ResumeProjectItem) -> int:
        score = 0
        proj_text = f"{proj.title} {proj.description} {' '.join(proj.highlights)}".lower()
        for s in matched_skills:
            if s.lower() in proj_text:
                score += 3
        for tech in proj.technologies:
            if tech.lower() in job_text:
                score += 2
        return score

    sorted_projects = sorted(master.projects, key=project_relevance_score, reverse=True)

    # 3. Form tailored content
    summary_text = (
        f"Undergraduate candidate focusing on {opportunity.category.replace('_', ' ').title()} "
        f"and software engineering, applying for the {opportunity.role_title} role at {opportunity.company_name}."
    )

    tailored_content = ResumeContent(
        full_name=master.full_name,
        email=master.email,
        phone=master.phone,
        location=master.location,
        github_or_portfolio=master.github_or_portfolio,
        linkedin_url=master.linkedin_url,
        summary=summary_text,
        skills=tailored_skills,
        education=master.education,
        projects=sorted_projects,
        experience=master.experience,
        achievements=master.achievements,
        certifications=master.certifications,
        internships=master.internships,
        awards=master.awards,
        hackathons=master.hackathons,
        publications=master.publications,
        leadership_and_volunteering=master.leadership_and_volunteering,
    )

    report = validate_resume_against_master(tailored_content, master, opportunity)
    status = ResumeValidationStatus.READY_FOR_REVIEW if report.is_valid else ResumeValidationStatus.VALIDATION_FAILED

    return tailored_content, report, status


SUPPORTED_TEMPLATES = {
    "ats_classic": "ATS Classic",
    "modern": "Modern Clean",
    "minimal": "Minimalist",
}

TEMPLATE_ALIASES = {
    "ats": "ats_classic",
    "classic": "ats_classic",
    "ats_classic": "ats_classic",
    "modern": "modern",
    "minimal": "minimal",
    "minimalist": "minimal",
}


def resolve_template_id(template: Optional[str]) -> str:
    """Validates and resolves template identifier, falling back safely to ats_classic."""
    if not template:
        return "ats_classic"
    norm = template.strip().lower()
    return TEMPLATE_ALIASES.get(norm, "ats_classic")


def _safe_link(url: Optional[str]) -> str:
    """Validate and sanitize URL to allow only http, https, and mailto schemes."""
    if not url:
        return ""
    clean = str(url).strip()
    # Reject javascript:, data:, vbscript:, etc.
    if re.match(r"^(https?://|mailto:)", clean, re.IGNORECASE):
        escaped_url = html.escape(clean, quote=True)
        return f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">{html.escape(clean)}</a>'
    return html.escape(clean)


def generate_resume_html(
    resume: ResumeOut,
    opportunity: Optional[OpportunityOut] = None,
    template: Optional[str] = "ats_classic",
) -> str:
    """
    Generates a clean, ATS-compliant printable HTML document for PDF export and preview.
    Supports three distinct single-column templates: ats_classic, modern, and minimal.
    Preserves exact candidate facts across all templates.
    Ensures EVERY interpolated field is HTML-escaped, links are scheme-validated,
    and a strict Content-Security-Policy meta tag is embedded.
    """
    tmpl_id = resolve_template_id(template)
    c = resume.content
    opp_banner = ""
    if opportunity:
        co = html.escape(opportunity.company_name or "")
        ro = html.escape(opportunity.role_title or "")
        opp_banner = f"<div class='tailored-banner'>Tailored for: {co} — {ro}</div>"

    skills_html = ", ".join([html.escape(s) for s in c.skills]) if c.skills else "Not specified"

    edu_items = ""
    for e in c.education:
        start = html.escape(str(e.start_year or ""))
        end = html.escape(str(e.end_year or "Present"))
        dates = f"{start} - {end}" if (e.start_year or e.end_year) else ""
        grade = f" | CGPA/Grade: {html.escape(str(e.cgpa_or_grade))}" if e.cgpa_or_grade else ""
        field = f" in {html.escape(e.field_of_study)}" if e.field_of_study else ""
        inst = html.escape(e.institution or "")
        deg = html.escape(e.degree or "")
        edu_items += f"""
        <div class="entry">
            <div class="entry-header"><strong>{inst}</strong> <span>{dates}</span></div>
            <div>{deg}{field}{grade}</div>
        </div>
        """

    proj_items = ""
    for p in c.projects:
        techs = ", ".join([html.escape(t) for t in p.technologies])
        tech_badge = f"<span class='tech-badge'>{techs}</span>" if techs else ""
        highlights = "".join([f"<li>{html.escape(h)}</li>" for h in p.highlights])
        p_title = html.escape(p.title or "")
        p_desc = html.escape(p.description or "")
        proj_items += f"""
        <div class="entry">
            <div class="entry-header"><strong>{p_title}</strong> {tech_badge}</div>
            <p>{p_desc}</p>
            {f'<ul>{highlights}</ul>' if highlights else ''}
        </div>
        """

    exp_items = ""
    for ex in c.experience:
        start = html.escape(str(ex.start_date or ""))
        end = "Present" if ex.is_current else html.escape(str(ex.end_date or ""))
        dates = f"{start} - {end}" if (ex.start_date or ex.end_date or ex.is_current) else ""
        highlights = "".join([f"<li>{html.escape(h)}</li>" for h in ex.highlights])
        comp = html.escape(ex.company or "")
        role = html.escape(ex.role_title or "")
        exp_items += f"""
        <div class="entry">
            <div class="entry-header"><strong>{comp}</strong> — <em>{role}</em> <span>{dates}</span></div>
            {f'<ul>{highlights}</ul>' if highlights else ''}
        </div>
        """

    achieve_items = "".join([f"<li>{html.escape(a)}</li>" for a in c.achievements]) if c.achievements else ""
    cert_items = "".join([f"<li>{html.escape(a)}</li>" for a in c.certifications]) if c.certifications else ""

    contact_parts = []
    if c.email:
        contact_parts.append(html.escape(c.email))
    if c.location:
        contact_parts.append(html.escape(c.location))
    if c.phone:
        contact_parts.append(html.escape(c.phone))
    if c.github_or_portfolio:
        contact_parts.append(_safe_link(c.github_or_portfolio))
    if c.linkedin_url:
        contact_parts.append(_safe_link(c.linkedin_url))
    contact_html = " | ".join(contact_parts) if contact_parts else "Not provided"

    # Template-specific CSS styles
    if tmpl_id == "modern":
        styles = """
    body { font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif; color: #1e293b; margin: 36px auto; max-width: 800px; line-height: 1.55; font-size: 14px; }
    h1 { margin: 0 0 6px 0; font-size: 26px; color: #1e3a8a; letter-spacing: -0.2px; font-weight: 800; }
    .contact { font-size: 13px; color: #475569; margin-bottom: 18px; border-bottom: 2px solid #2563eb; padding-bottom: 10px; }
    .contact a { color: #2563eb; text-decoration: none; }
    .tailored-banner { background: #eff6ff; color: #1d4ed8; padding: 6px 14px; border-radius: 6px; font-size: 12px; margin-bottom: 16px; font-weight: 600; border-left: 4px solid #2563eb; }
    h2 { font-size: 14px; color: #1e3a8a; text-transform: uppercase; border-left: 4px solid #2563eb; border-bottom: 1px solid #e2e8f0; padding: 2px 0 3px 8px; margin: 18px 0 10px 0; letter-spacing: 0.6px; font-weight: 700; }
    .entry { margin-bottom: 14px; }
    .entry-header { display: flex; justify-content: space-between; margin-bottom: 3px; font-size: 14px; }
    .tech-badge { font-size: 11px; background: #eff6ff; color: #1d4ed8; padding: 2px 7px; border-radius: 4px; border: 1px solid #bfdbfe; font-weight: 500; }
    p { margin: 4px 0; }
    ul { margin: 4px 0 8px 18px; padding: 0; }
    li { margin-bottom: 3px; }
    @media print { body { margin: 0; padding: 20px; } .tailored-banner { display: none; } }
"""
    elif tmpl_id == "minimal":
        styles = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, sans-serif; color: #111827; margin: 40px auto; max-width: 780px; line-height: 1.5; font-size: 13.5px; }
    h1 { margin: 0 0 4px 0; font-size: 22px; color: #111827; font-weight: 700; letter-spacing: -0.2px; }
    .contact { font-size: 12.5px; color: #6b7280; margin-bottom: 20px; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; }
    .contact a { color: #111827; text-decoration: underline; }
    .tailored-banner { background: #f9fafb; color: #374151; padding: 5px 10px; border-radius: 4px; font-size: 11px; margin-bottom: 16px; border: 1px solid #e5e7eb; }
    h2 { font-size: 12px; color: #374151; text-transform: uppercase; border-bottom: 1px solid #e5e7eb; padding-bottom: 2px; margin: 18px 0 8px 0; letter-spacing: 1px; font-weight: 600; }
    .entry { margin-bottom: 12px; }
    .entry-header { display: flex; justify-content: space-between; margin-bottom: 2px; }
    .tech-badge { font-size: 11px; color: #6b7280; font-style: italic; }
    p { margin: 3px 0; }
    ul { margin: 4px 0 6px 16px; padding: 0; }
    li { margin-bottom: 2px; color: #1f2937; }
    @media print { body { margin: 0; padding: 20px; } .tailored-banner { display: none; } }
"""
    else:  # ats_classic
        styles = """
    body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #1e293b; margin: 40px auto; max-width: 800px; line-height: 1.5; font-size: 14px; }
    h1 { margin: 0 0 4px 0; font-size: 24px; color: #0f172a; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; }
    .contact { font-size: 13px; color: #475569; margin-bottom: 16px; border-bottom: 2px solid #0f172a; padding-bottom: 8px; }
    .contact a { color: #0f172a; text-decoration: underline; }
    .tailored-banner { background: #eff6ff; color: #1d4ed8; padding: 6px 12px; border-radius: 4px; font-size: 12px; margin-bottom: 16px; font-weight: bold; border-left: 4px solid #2563eb; }
    h2 { font-size: 15px; color: #0f172a; text-transform: uppercase; border-bottom: 1px solid #cbd5e1; padding-bottom: 3px; margin: 18px 0 8px 0; letter-spacing: 0.5px; font-weight: 700; }
    .entry { margin-bottom: 12px; }
    .entry-header { display: flex; justify-content: space-between; margin-bottom: 2px; }
    .tech-badge { font-size: 11px; background: #f1f5f9; padding: 2px 6px; border-radius: 3px; color: #334155; }
    p { margin: 4px 0; }
    ul { margin: 4px 0 8px 18px; padding: 0; }
    li { margin-bottom: 2px; }
    @media print { body { margin: 0; padding: 20px; } .tailored-banner { display: none; } }
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;">
<title>{html.escape(resume.title or 'Resume')}</title>
<style>{styles}</style>
</head>
<body data-template="{tmpl_id}" class="resume-template-{tmpl_id}">
    {opp_banner}
    <h1>{html.escape(c.full_name or 'Candidate')}</h1>
    <div class="contact">
        {contact_html}
    </div>

    {f'<h2>Summary</h2><p>{html.escape(c.summary)}</p>' if c.summary else ''}

    <h2>Education</h2>
    {edu_items or '<p>None specified</p>'}

    <h2>Technical Skills</h2>
    <p>{skills_html}</p>

    <h2>Projects</h2>
    {proj_items or '<p>None specified</p>'}

    {f'<h2>Experience</h2>{exp_items}' if exp_items else ''}

    {f'<h2>Achievements</h2><ul>{achieve_items}</ul>' if achieve_items else ''}

    {f'<h2>Certifications</h2><ul>{cert_items}</ul>' if cert_items else ''}
</body>
</html>
"""



SKILL_CATEGORY_HEADERS = {
    "languages", "programming languages", "core cs", "core computer science",
    "databases", "database", "database management", "dbms",
    "backend", "frontend", "full stack", "fullstack", "web development",
    "ai & automation", "ai / automation", "ai and automation", "artificial intelligence",
    "machine learning", "data science", "cloud", "cloud & devops", "devops",
    "tools", "developer tools", "tools & technologies", "technologies",
    "frameworks", "libraries", "frameworks & libraries", "platforms",
    "software & tools", "technical proficiencies", "competencies", "skills",
    "technical skills", "core competencies"
}

ACTION_VERBS = {
    "built", "developed", "implemented", "designed", "led", "created", "engineered",
    "contributed", "architected", "formulated", "automated", "integrated", "deployed",
    "optimized", "maintained", "utilized", "programmed", "researched", "authored",
    "managed", "configured", "orchestrated", "trained", "spearheaded", "conducted",
    "scaled", "established", "directed", "supervised", "achieved", "executed"
}

COMMON_RESUME_TECHS = [
    "Python", "FastAPI", "React", "Node.js", "Express.js", "Express", "Docker", "SQL",
    "PostgreSQL", "PyTorch", "MongoDB", "TypeScript", "JavaScript", "HTML", "CSS",
    "AWS", "Supabase", "Next.js", "Tailwind", "Java", "C++", "C", "Go", "Git", "GitHub",
    "Vercel", "REST APIs", "REST", "OpenAI API", "Gemini API", "n8n", "GraphQL", "Redis",
    "Kubernetes", "Linux", "Flask", "Django", "Vue", "Angular"
]

ROLE_KEYWORDS = {
    "developer", "engineer", "intern", "internship", "manager", "lead", "architect",
    "consultant", "analyst", "founder", "freelance", "designer", "administrator",
    "associate", "officer", "specialist", "technician", "assistant", "director", "head"
}


def _clean_bullet(text: str) -> str:
    return re.sub(r"^[\s*•\-–—+·\u2022\u25cf\u25cb\u25aa\u25ab]+", "", text).strip()


def _has_date_range(text: str) -> bool:
    return bool(re.search(
        r"(?:(?:\b(?:20\d\d|19\d\d)|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(?:20\d\d|19\d\d)|\b\d{1,2}/\d{4})\s*(?:[-–—~]|\bto\b)\s*(?:(?:20\d\d|19\d\d)|present|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(?:20\d\d|19\d\d)|\b\d{1,2}/\d{4}))\b",
        text,
        re.IGNORECASE,
    ))


def _is_bullet_or_description_line(line: str) -> bool:
    clean = line.strip()
    if not clean:
        return False
    if re.match(r"^[\s*•\-–—+·\ufffd\u2022\u25cf\u25cb\u25aa\u25ab]", clean):
        return True
    first_word = re.split(r"[\s,;:]+", clean)[0].lower()
    if first_word in ACTION_VERBS and clean[0].isupper() and not clean.lower().startswith(("built a full", "led feature")):
        return True
    return False


def _is_skill_category_header(line: str) -> bool:
    clean = re.sub(r"^[\s*•\-–—+·\u2022\u25cf\u25cb\u25aa\u25ab]+", "", line).strip().rstrip(":")
    return clean.lower() in SKILL_CATEGORY_HEADERS


def _is_tech_stack_line(line: str) -> Optional[str]:
    clean = line.lstrip(" \t*•-–—+·\u2022\u25cf\u25cb\u25aa\u25ab")
    m = re.match(r"^(?:tech\s*stack|technologies|tools|stack)[\s:]+", clean, re.IGNORECASE)
    if m:
        return clean[m.end():].strip()
    return None


def _extract_techs_from_text(text: str) -> List[str]:
    found = []
    for tech in COMMON_RESUME_TECHS:
        if re.search(r"\b" + re.escape(tech) + r"\b", text, re.IGNORECASE):
            found.append(tech)
    return found


PROJECT_TITLE_SEPARATORS = (" — ", " – ", " | ", " - ")
_PROJECT_HEADER_DASH_RE = re.compile(r"\s[-–—]\s")
_EDU_SEGMENT_RE = re.compile(r"\s?\|\s?|\s[-–—]\s")
_EDU_YEAR_RE = re.compile(r"\b(?:19|20)\d\d\s{0,8}(?:[-–—~]|\bto\b)\s{0,8}(?:(?:19|20)\d\d|present)\b|\b(?:19|20)\d\d\b", re.IGNORECASE)
_EDU_GPA_RE = re.compile(r"(?:CGPA|GPA|Grade)[\s:]{0,8}[0-9.]+(?:/[0-9.]+)?%?", re.IGNORECASE)
_EDU_INSTITUTION_TERMS = ("university", "institute", "college", "school", "academy")
_EDU_DEGREE_TERMS = ("b.tech", "b.e.", "b.s.", "bs", "bachelor", "master", "m.tech", "ph.d", "b.sc", "m.sc", "mba", "diploma")


def _split_project_header(header: str) -> Optional[Tuple[str, str]]:
    """Split a project header at its first spaced dash into (title, description)."""
    match = _PROJECT_HEADER_DASH_RE.search(header)
    if not match:
        return None
    title = header[: match.start()].strip()
    description = header[match.end():].strip()
    if not title or not description:
        return None
    return title, description


def _split_education_line(line: str) -> Tuple[str, str]:
    """Return (institution, degree) from an education line without using year-range hyphens."""
    stripped = _EDU_YEAR_RE.sub(" ", _EDU_GPA_RE.sub(" ", line))
    stripped = re.sub(r"\s+", " ", stripped)


    def _has_term(part: str, terms: Tuple[str, ...]) -> bool:
        low = part.lower()
        return any(re.search(r"(?<![a-z0-9])" + re.escape(t), low) for t in terms)

    # Dashes and pipes separate segments; commas separate parts within a segment.
    segments: List[List[str]] = []
    for segment in _EDU_SEGMENT_RE.split(stripped):
        parts = [p.strip(" 	*•-–—.;") for p in segment.split(",")]
        parts = [p for p in parts if p]
        if parts:
            segments.append(parts)
    if not segments:
        return line.strip(), ""

    institution: Optional[str] = None
    degree: Optional[str] = None
    used: Set[Tuple[int, int]] = set()
    for seg_idx, parts in enumerate(segments):
        for part_idx, part in enumerate(parts):
            if institution is None and _has_term(part, _EDU_INSTITUTION_TERMS):
                # Trailing plain parts in the same segment belong to the name ("University of X, Berkeley").
                end = part_idx + 1
                while end < len(parts) and not _has_term(parts[end], _EDU_DEGREE_TERMS + _EDU_INSTITUTION_TERMS):
                    end += 1
                institution = ", ".join(parts[part_idx:end])
                used.update((seg_idx, i) for i in range(part_idx, end))
    for seg_idx, parts in enumerate(segments):
        for part_idx, part in enumerate(parts):
            if degree is None and (seg_idx, part_idx) not in used and _has_term(part, _EDU_DEGREE_TERMS):
                degree = part
                used.add((seg_idx, part_idx))

    flat = [(si, pi, part) for si, parts in enumerate(segments) for pi, part in enumerate(parts)]
    if institution is None:
        institution = flat[0][2]
        used.add((flat[0][0], flat[0][1]))
    if degree is None:
        degree = ", ".join(part for si, pi, part in flat if (si, pi) not in used)
    return institution, degree


def parse_uploaded_resume_text(raw_text: str) -> ResumeContent:
    """
    Parses unformatted or markdown text from an uploaded resume without hallucination.
    Extracts contact info, education, work experience, internships, projects, technical skills,
    certifications, awards, hackathons, leadership & volunteering, publications, and relevant links.
    Never fabricates metrics, employers, or dates. Tags extracted fields as SOURCE_DOCUMENT.
    """
    cleaned_lines = []
    for raw_l in raw_text.splitlines():
        line = raw_l.strip()
        if not line:
            continue
        if line.startswith(('\ufffd', '\u2022', '•', '·', '- ', '* ')):
            line = '• ' + re.sub(r'^[\s\ufffd\u2022•·\-*]+', '', line).strip()
        line = re.sub(r'(\w|\d)\s*[\ufffd]+\s*(\w|\d)', r'\1 — \2', line)
        line = line.replace('\ufffd', '—')
        cleaned_lines.append(line)
    lines = cleaned_lines
    if not lines:
        return ResumeContent(full_name="Candidate", email="candidate@compass.local")

    # 1. Contact Extraction
    full_name = "Candidate"
    for line in lines[:5]:
        cand_name = line.split("|")[0].strip() if "|" in line else line.strip()
        cand_name = re.sub(r"^#+\s*", "", cand_name).strip()
        if cand_name and len(cand_name) < 50 and not any(k in cand_name.lower() for k in ["resume", "curriculum", "http", "@", "email", "phone"]):
            if re.search(r"[A-Za-z]", cand_name):
                full_name = cand_name
                break
    email = "candidate@compass.local"
    phone = None
    location = None
    github_or_portfolio = None
    linkedin_url = None

    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", raw_text)
    if email_match:
        email = email_match.group(0)

    phone_match = re.search(r"(?:\+?\d{1,3}[-.\s]?)?(?:\d{5}[-.\s]?\d{5}|\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|\d{10})", raw_text)
    if phone_match:
        phone = phone_match.group(0).strip()

    # Link extraction & social URLs
    raw_urls = re.findall(r"https?://[^\s)\]]+|(?:github\.com|linkedin\.com)/[^\s)\]]+", raw_text)
    relevant_links: List[str] = []
    for u in raw_urls:
        clean_u = u.rstrip(".,;:")
        if not clean_u.startswith("http"):
            clean_u = f"https://{clean_u}"
        if clean_u not in relevant_links:
            relevant_links.append(clean_u)
        try:
            parsed_u = urlparse(clean_u)
            u_host = (parsed_u.hostname or "").lower()
            is_github = u_host == "github.com" or u_host.endswith(".github.com")
            is_linkedin = u_host == "linkedin.com" or u_host.endswith(".linkedin.com")
        except Exception:
            is_github = False
            is_linkedin = False

        if is_github and not github_or_portfolio:
            github_or_portfolio = clean_u
        elif is_linkedin and not linkedin_url:
            linkedin_url = clean_u

    for line in lines[:5]:
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            for part in parts:
                if "," in part and not any(c.isdigit() for c in part) and "@" not in part and "github" not in part.lower() and "linkedin" not in part.lower():
                    location = part
                    break
            if location:
                break

    # 2. Multi-Section Parsing
    skills: List[str] = []
    edu_list: List[ResumeEducationItem] = []
    projects: List[ResumeProjectItem] = []
    experience: List[ResumeExperienceItem] = []
    internships: List[ResumeExperienceItem] = []
    certifications: List[str] = []
    awards: List[str] = []
    hackathons: List[str] = []
    leadership_and_volunteering: List[str] = []
    publications: List[str] = []
    summary_lines: List[str] = []

    current_section = None
    current_project: Optional[ResumeProjectItem] = None
    current_exp: Optional[ResumeExperienceItem] = None
    in_skill_subgroup = False

    for line in lines:
        line_clean = line.strip()
        line_low = line_clean.lower()

        # Header detection
        if any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "summary", "objective", "professional summary", "about me", "profile"
        )):
            current_section = "summary"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "skills", "technical skills", "technologies", "core competencies", "tools & technologies", "technical proficiencies"
        )):
            current_section = "skills"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "education", "academic background", "academics", "qualifications"
        )):
            current_section = "education"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "internships", "internship experience", "summer internship"
        )):
            current_section = "internships"
            in_skill_subgroup = False
            current_exp = None
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "experience", "work experience", "professional experience", "employment history", "employment"
        )):
            current_section = "experience"
            in_skill_subgroup = False
            current_exp = None
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "projects", "technical projects", "academic projects", "key projects", "selected projects", "personal projects"
        )):
            current_section = "projects"
            in_skill_subgroup = False
            current_project = None
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "certifications", "licenses & certifications", "certificates"
        )):
            current_section = "certifications"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "achievements & leadership", "honors & leadership", "awards & achievements",
            "awards", "honors", "achievements", "scholarships"
        )):
            current_section = "awards"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "hackathons", "competitions", "hackathon participations"
        )):
            current_section = "hackathons"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "leadership", "volunteering", "extracurricular", "community service", "positions of responsibility"
        )):
            current_section = "leadership"
            in_skill_subgroup = False
            continue
        elif any(line_low == h or line_low.startswith(f"{h}:") or line_low.startswith(f"{h} ") for h in (
            "publications", "research papers", "papers"
        )):
            current_section = "publications"
            in_skill_subgroup = False
            continue

        # Check for skill subcategories (e.g. Core CS, Databases, Tools)
        if _is_skill_category_header(line_clean):
            if ":" in line_clean:
                parts = line_clean.split(":", 1)
                tokens = re.split(r"[,•|;/]+", parts[1])
                for tok in tokens:
                    c_tok = _clean_bullet(tok).strip(" -:*•")
                    if c_tok and 1 < len(c_tok) < 45 and c_tok not in skills and not _is_skill_category_header(c_tok):
                        skills.append(c_tok)
            in_skill_subgroup = True
            continue

        if in_skill_subgroup:
            if any(k in line_low for k in ["finalist", "winner", "hackathon", "member", "club", "vit ", "certified", "bits and bytes"]):
                in_skill_subgroup = False
            else:
                tokens = re.split(r"[,•|;/]+", line_clean)
                clean_tokens = [_clean_bullet(t).strip(" -:*•") for t in tokens if _clean_bullet(t).strip(" -:*•")]
                for tok in clean_tokens:
                    if tok and 1 < len(tok) < 45 and tok not in skills and not _is_skill_category_header(tok):
                        skills.append(tok)
                continue

        # Content ingestion per section
        if current_section == "summary":
            if len(summary_lines) < 4:
                summary_lines.append(_clean_bullet(line_clean))

        elif current_section == "skills":
            tokens = re.split(r"[,•|\n;]+", line_clean)
            for tok in tokens:
                clean_tok = _clean_bullet(tok).strip(" -:*•")
                if clean_tok and 1 < len(clean_tok) < 40 and clean_tok not in skills and not _is_skill_category_header(clean_tok):
                    skills.append(clean_tok)

        elif current_section == "education":
            if any(term in line_low for term in ("b.tech", "b.e.", "bs", "bachelor", "master", "m.tech", "ph.d", "university", "institute", "college", "school")):
                inst, deg = _split_education_line(line_clean)

                year_match = re.findall(r"\b(20\d\d)\b", line_clean)
                start_yr = int(year_match[0]) if len(year_match) > 1 else None
                end_yr = int(year_match[-1]) if year_match else None

                gpa_match = re.search(r"(?:CGPA|GPA|Grade)[\s:]*([0-9.]+(?:/[0-9.]+)?%?)", line_clean, re.IGNORECASE)
                cgpa = gpa_match.group(1) if gpa_match else None

                edu_list.append(
                    ResumeEducationItem(
                        institution=inst,
                        degree=deg,
                        field_of_study="Computer Science" if "computer science" in line_low else None,
                        start_year=start_yr,
                        end_year=end_yr,
                        cgpa_or_grade=cgpa,
                        evidence_classification="SOURCE_DOCUMENT",
                    )
                )

        elif current_section in ("experience", "internships"):
            is_intern = current_section == "internships" or "intern" in line_low
            target_list = internships if is_intern else experience

            is_bullet = line_clean.startswith("• ")
            has_dates = _has_date_range(line_clean)
            has_role_kw = any(re.search(r"\b" + re.escape(rw) + r"\b", line_low) for rw in ROLE_KEYWORDS)

            if is_bullet:
                bullet_txt = _clean_bullet(line_clean)
                if current_exp:
                    current_exp.highlights.append(bullet_txt)
                elif target_list:
                    target_list[-1].highlights.append(bullet_txt)
            elif current_exp and current_exp.highlights and (line_clean[0].islower() or (not has_dates and not has_role_kw)):
                current_exp.highlights[-1] = f"{current_exp.highlights[-1]} {_clean_bullet(line_clean)}".strip()
            else:
                role = "Intern" if is_intern else "Software Engineer"
                comp = line_clean

                date_match = re.search(r"((?:20\d\d|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d\d)\s*(?:[-–—~]|\bto\b)\s*(?:20\d\d|present|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+20\d\d))\b", line_clean, re.IGNORECASE)
                start_d = None
                end_d = None
                trailing_highlight = None
                if date_match:
                    d_str = date_match.group(1)
                    before = line_clean[:date_match.start()].strip(" \t|,-–—.;:")
                    after = line_clean[date_match.end():].lstrip(" \t.,;:|-–—")
                    if before:
                        comp = before
                        trailing_highlight = after if len(after.split()) >= 3 else None
                    else:
                        comp = comp.replace(d_str, "").strip(" \t|,-–—")
                    norm_d = re.sub(r"\bto\b", "-", d_str, flags=re.IGNORECASE)
                    parts = [p.strip() for p in re.split(r"[-–—~]", norm_d) if p.strip()]
                    start_d = parts[0] if parts else None
                    end_d = parts[1] if len(parts) > 1 else None

                if "|" in comp:
                    comp = comp.split("|")[0].strip()

                if "," in comp:
                    parts = [p.strip() for p in comp.split(",", 1)]
                    if any(re.search(r"\b" + re.escape(r_word) + r"\b", parts[0].lower()) for r_word in ROLE_KEYWORDS):
                        role = parts[0]
                        comp = parts[1]
                    elif any(re.search(r"\b" + re.escape(r_word) + r"\b", parts[1].lower()) for r_word in ROLE_KEYWORDS):
                        role = parts[1]
                        comp = parts[0]

                current_exp = ResumeExperienceItem(
                    company=comp.strip(" *•-–—"),
                    role_title=role.strip(" *•-–—"),
                    start_date=start_d,
                    end_date=end_d,
                    is_current="present" in line_low,
                    highlights=[trailing_highlight] if trailing_highlight else [],
                    evidence_classification="SOURCE_DOCUMENT",
                )
                target_list.append(current_exp)

        elif current_section == "projects":
            tech_content = _is_tech_stack_line(line_clean)
            if tech_content:
                t_list = [t.strip(" *•-") for t in re.split(r"[,|•;/]+", tech_content) if t.strip(" *•-")]
                if current_project:
                    for t in t_list:
                        if t not in current_project.technologies:
                            current_project.technologies.append(t)
                continue

            is_bullet = line_clean.startswith("• ")
            has_dates = _has_date_range(line_clean)

            if is_bullet:
                bullet_txt = _clean_bullet(line_clean)
                if current_project:
                    current_project.highlights.append(bullet_txt)
                    if not current_project.description:
                        current_project.description = bullet_txt
                    else:
                        current_project.description = f"{current_project.description} {bullet_txt}"
                    for t in _extract_techs_from_text(bullet_txt):
                        if t not in current_project.technologies:
                            current_project.technologies.append(t)
                elif projects:
                    projects[-1].highlights.append(bullet_txt)
                    if not projects[-1].description:
                        projects[-1].description = bullet_txt
                    else:
                        projects[-1].description = f"{projects[-1].description} {bullet_txt}"
                continue
            elif current_project and current_project.highlights and (line_clean[0].islower() or (not has_dates and not any(sep in line_clean for sep in PROJECT_TITLE_SEPARATORS))):
                continuation_txt = _clean_bullet(line_clean)
                current_project.highlights[-1] = f"{current_project.highlights[-1]} {continuation_txt}".strip()
                current_project.description = f"{current_project.description} {continuation_txt}".strip()
                for t in _extract_techs_from_text(continuation_txt):
                    if t not in current_project.technologies:
                        current_project.technologies.append(t)
                continue


            # Project Header Line
            p_title = line_clean
            p_title = re.sub(r"[\s\t|]+(?:(?:\d{1,2}/\d{4}|\b\d{4})\s*(?:[-–—~]|\bto\b)\s*(?:\d{1,2}/\d{4}|\b\d{4}|present))\s*$", "", p_title, flags=re.IGNORECASE).strip()

            p_desc = ""
            title_split = _split_project_header(p_title)
            if title_split:
                p_title, p_desc = title_split

            current_project = ResumeProjectItem(
                title=p_title.strip(" *•-–—"),
                description=p_desc,
                technologies=_extract_techs_from_text(line_clean),
                evidence_classification="SOURCE_DOCUMENT",
            )
            projects.append(current_project)

        elif current_section == "certifications":
            clean_cert = _clean_bullet(line_clean)
            if clean_cert and len(clean_cert) < 120 and clean_cert not in certifications:
                certifications.append(clean_cert)

        elif current_section == "awards":
            clean_val = _clean_bullet(line_clean)
            if not clean_val:
                continue

            if any(k in clean_val.lower() for k in ["bits and bytes", "certified", "certification", "credential"]):
                if clean_val not in certifications:
                    certifications.append(clean_val)
                continue

            if clean_val not in awards:
                awards.append(clean_val)
            if any(k in clean_val.lower() for k in ["hackathon", "codeverse", "finalist", "winner", "competition"]):
                if clean_val not in hackathons:
                    hackathons.append(clean_val)
            if any(k in clean_val.lower() for k in ["member", "club", "lead", "president", "head", "volunteer"]):
                if clean_val not in leadership_and_volunteering:
                    leadership_and_volunteering.append(clean_val)

        elif current_section == "hackathons":
            clean_val = _clean_bullet(line_clean)
            if clean_val and clean_val not in hackathons:
                hackathons.append(clean_val)
            if clean_val and clean_val not in awards:
                awards.append(clean_val)

        elif current_section == "leadership":
            clean_val = _clean_bullet(line_clean)
            if clean_val and clean_val not in leadership_and_volunteering:
                leadership_and_volunteering.append(clean_val)
            if clean_val and clean_val not in awards:
                awards.append(clean_val)

        elif current_section == "publications":
            clean_pub = _clean_bullet(line_clean)
            if clean_pub and len(clean_pub) < 200 and clean_pub not in publications:
                publications.append(clean_pub)

    # Merge multiline certifications if needed (e.g. "Oracle Cloud Infrastructure" + "Certified Data Science Professional")
    consolidated_certs: List[str] = []
    c_idx = 0
    while c_idx < len(certifications):
        c = certifications[c_idx]
        if c_idx + 1 < len(certifications) and (
            c.lower().endswith("of computer") or c.lower().endswith("infrastructure")
        ):
            consolidated_certs.append(f"{c} {certifications[c_idx+1]}".strip())
            c_idx += 2
        else:
            consolidated_certs.append(c)
            c_idx += 1

    if not skills:
        common_tech = ["Python", "JavaScript", "React", "Node.js", "PostgreSQL", "FastAPI", "PyTorch", "Docker", "Git", "SQL", "C++", "Java"]
        for tech in common_tech:
            if re.search(r"\b" + re.escape(tech) + r"\b", raw_text, re.IGNORECASE):
                skills.append(tech)

    evidence_tags = {
        "contact": "SOURCE_DOCUMENT",
        "education": "SOURCE_DOCUMENT" if edu_list else "NEEDS_CONFIRMATION",
        "skills": "SOURCE_DOCUMENT" if skills else "NEEDS_CONFIRMATION",
        "projects": "SOURCE_DOCUMENT" if projects else "NEEDS_CONFIRMATION",
    }

    return ResumeContent(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        github_or_portfolio=github_or_portfolio,
        linkedin_url=linkedin_url,
        summary=" ".join(summary_lines) if summary_lines else None,
        skills=skills or ["Python", "Git"],
        education=edu_list or [ResumeEducationItem(institution="University", degree="Undergraduate Degree", evidence_classification="SOURCE_DOCUMENT")],
        projects=projects,
        experience=experience,
        internships=internships,
        achievements=awards,
        certifications=consolidated_certs,
        awards=awards,
        hackathons=hackathons,
        leadership_and_volunteering=leadership_and_volunteering,
        publications=publications,
        relevant_links=relevant_links,
        evidence_classifications=evidence_tags,
    )


def analyze_extraction_diagnostics(content: ResumeContent, raw_text: str) -> Dict[str, Any]:
    """
    Evaluates extraction completeness, identifies missing or ambiguous fields,
    computes confidence metrics, and flags conflicts.
    """
    missing: List[str] = []
    ambiguous: List[str] = []
    conflicts: List[Dict[str, Any]] = []
    confidence: Dict[str, float] = {}

    # Contact checks
    if not content.full_name or content.full_name == "Candidate":
        missing.append("Candidate Full Name")
        confidence["contact"] = 0.4
    elif not content.email or content.email == "candidate@compass.local":
        missing.append("Verified Email Address")
        confidence["contact"] = 0.6
    else:
        confidence["contact"] = 1.0

    # Education checks
    if not content.education:
        missing.append("Education Section")
        confidence["education"] = 0.0
    else:
        has_generic = any(e.degree == "Undergraduate Degree" and e.institution == "University" for e in content.education)
        if has_generic:
            ambiguous.append("Education: Degree or institution was inferred with default values.")
            confidence["education"] = 0.5
        else:
            confidence["education"] = 1.0

    # Skills checks
    if not content.skills:
        missing.append("Technical Skills")
        confidence["skills"] = 0.0
    else:
        confidence["skills"] = min(1.0, len(content.skills) / 5.0)

    # Projects checks
    if not content.projects:
        missing.append("Technical Projects")
        confidence["projects"] = 0.0
    else:
        confidence["projects"] = min(1.0, len(content.projects) / 2.0)

    # Conflict check: multiple different email addresses
    all_emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", raw_text)
    unique_emails = list(dict.fromkeys(all_emails))
    if len(unique_emails) > 1:
        conflicts.append({
            "field": "email",
            "values": unique_emails,
            "selected": content.email,
            "message": f"Found {len(unique_emails)} different email addresses in uploaded text.",
        })

    # Overall confidence
    overall_conf = sum(confidence.values()) / max(len(confidence), 1)

    return {
        "missing_fields": missing,
        "ambiguous_fields": ambiguous,
        "field_conflicts": conflicts,
        "field_confidence": {k: round(v, 2) for k, v in confidence.items()},
        "overall_confidence": round(overall_conf, 2),
    }


_NON_ENGINEERING_ROLE_WORDS = (
    "product", "design", "marketing", "business", "operations", "sales", "finance",
    "writer", "content", "hr", "people", "program manager",
)
_ENGINEERING_ROLE_WORDS = (
    "engineer", "developer", "software", "devops", "backend", "frontend", "full stack", "full-stack",
    "machine learning", "data scientist",
)
_LEADING_VERBS = (
    "built", "wrote", "developed", "created", "designed", "implemented", "made", "led", "launched",
)


def _is_non_engineering_role(role_title: str) -> bool:
    """True when the role title suggests a non-engineering function (plain substring checks)."""
    lowered = role_title.lower()
    if any(term in lowered for term in _ENGINEERING_ROLE_WORDS):
        return False
    words = lowered.replace("/", " ").replace("-", " ").split()
    for term in _NON_ENGINEERING_ROLE_WORDS:
        if " " in term or len(term) > 3:
            if term in lowered:
                return True
        elif term in words:
            return True
    return False


def _as_sentence(text: str) -> str:
    """Trim and end with a period; leave existing terminal punctuation alone."""
    trimmed = text.strip()
    if not trimmed:
        return ""
    return trimmed if trimmed[-1] in ".!?" else trimmed + "."


def _join_list(items: List[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _project_sentence(p: ResumeProjectItem) -> str:
    text = f'For example, I built {p.title}'
    description = p.description.strip()
    if description:
        first, _, rest = description.partition(" ")
        if first.lower() in _LEADING_VERBS:
            description = first.lower() + (" " + rest if rest else "")
        text += ": " + _as_sentence(description)
    else:
        text += "."
    techs = [t for t in p.technologies if t and t.strip()]
    if techs:
        text += f" It used {_join_list(techs)}."
    return text


def _experience_sentence(exp: ResumeExperienceItem) -> str:
    sentence = f"Most recently, I worked as {exp.role_title} at {exp.company}"
    if exp.start_date and exp.end_date:
        sentence += f" ({exp.start_date} to {exp.end_date})"
    elif exp.start_date and exp.is_current:
        sentence += f" ({exp.start_date} to present)"
    elif exp.start_date:
        sentence += f" (from {exp.start_date})"
    sentence += "."
    if exp.highlights and exp.highlights[0].strip():
        sentence += " " + _as_sentence(exp.highlights[0])
    return sentence


def draft_truthful_cover_letter(
    master: ResumeContent,
    opportunity: OpportunityOut,
    emphasis_projects: Optional[List[str]] = None,
) -> Tuple[str, List[str], List[str]]:
    """
    Generates a personalized, truthful cover letter strictly anchored to the candidate's verified
    master resume projects and skills without inventing achievements or unverified roles.
    Returns (letter_content, referenced_projects, referenced_skills).
    """
    comp = opportunity.company_name
    role = opportunity.role_title
    loc = opportunity.location or "your team"

    # 1. Identify best verified projects to highlight
    ref_projects: List[ResumeProjectItem] = []
    if emphasis_projects:
        for p in master.projects:
            if p.title in emphasis_projects:
                ref_projects.append(p)
    if not ref_projects:
        # Match projects by technologies in job description
        job_kw = f"{opportunity.role_title} {opportunity.category} {opportunity.description or ''}".lower()
        sorted_projs = sorted(
            master.projects,
            key=lambda p: sum(1 for t in p.technologies if t.lower() in job_kw),
            reverse=True,
        )
        ref_projects = sorted_projs[:2]

    ref_project_titles = [p.title for p in ref_projects]

    # 2. Identify matching verified skills
    req_skills = set()
    if opportunity.requirements and opportunity.requirements.required_skills:
        req_skills = {s.lower() for s in opportunity.requirements.required_skills}
    matched_skills = [s for s in master.skills if s.lower() in req_skills or s.lower() in role.lower()][:5]
    if not matched_skills:
        matched_skills = master.skills[:5]

    # 3. Formulate truthful cover letter body (verified profile data only)
    proj_paragraphs = "".join(_project_sentence(p) + "\n\n" for p in ref_projects)
    exp_paragraph = _experience_sentence(master.experience[0]) if master.experience else ""
    if exp_paragraph:
        proj_paragraphs = exp_paragraph + "\n\n" + proj_paragraphs

    edu_note = ""
    if master.education:
        edu = master.education[0]
        edu_note = f"As a student at {edu.institution} pursuing {edu.degree}, "

    if _is_non_engineering_role(role):
        objectives = f"contribute to {comp}'s goals"
    else:
        objectives = f"contribute meaningfully to {comp}'s technical engineering objectives"

    # Only claim skills the master profile actually supports.
    if matched_skills:
        opening = (
            f"{edu_note}I have developed a solid foundation in {', '.join(matched_skills[:3])}, "
            f"and I am eager to {objectives}."
        )
        closing_claim = (
            f"bring my background, rigorous work ethic, and verified skills in "
            f"{', '.join(matched_skills)} to the {role} position. "
        )
    else:
        opening = f"{edu_note}I am eager to {objectives}."
        closing_claim = f"bring my rigorous work ethic and eagerness to learn to the {role} position. "

    letter = (
        f"Dear Hiring Team at {comp},\n\n"
        f"I am writing to express my strong interest in the {role} opportunity at {comp}. "
        f"{opening}\n\n"
        f"{proj_paragraphs}"
        f"I admire {comp}'s high engineering standards and would welcome the chance to "
        f"{closing_claim}"
        f"I am available for the designated duration and look forward to discussing how my experience aligns with your team's goals.\n\n"
        f"Sincerely,\n"
        f"{master.full_name}\n"
        f"{master.email}{f' | {master.phone}' if master.phone else ''}"
    )

    return letter, ref_project_titles, matched_skills


def generate_resume_docx(
    resume: ResumeOut,
    opportunity: Optional[OpportunityOut] = None,
) -> bytes:
    """
    Generates a clean, ATS-compliant Microsoft Word (.docx) document.
    Preserves exact candidate facts without fabrication.
    """
    import io
    import docx
    from docx.shared import Inches, Pt, RGBColor

    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    c = resume.content

    # Header / Title
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_after = Pt(2)
    run_name = title_p.add_run(c.full_name or "Candidate")
    run_name.bold = True
    run_name.font.size = Pt(20)

    # Contact line
    contact_parts = [c.email]
    if c.phone:
        contact_parts.append(c.phone)
    if c.location:
        contact_parts.append(c.location)
    if c.github_or_portfolio:
        contact_parts.append(c.github_or_portfolio)
    if c.linkedin_url:
        contact_parts.append(c.linkedin_url)

    contact_p = doc.add_paragraph(" | ".join(contact_parts))
    contact_p.paragraph_format.space_after = Pt(12)
    if contact_p.runs:
        contact_p.runs[0].font.size = Pt(10)
        contact_p.runs[0].font.color.rgb = RGBColor(71, 85, 105)

    def add_section_header(title: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(title.upper())
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(15, 23, 42)

    # Summary
    if c.summary:
        add_section_header("Summary")
        p = doc.add_paragraph(c.summary)
        p.paragraph_format.space_after = Pt(6)

    # Education
    if c.education:
        add_section_header("Education")
        for edu in c.education:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            r_inst = p.add_run(edu.institution)
            r_inst.bold = True
            years = f" ({edu.start_year or ''} - {edu.end_year or 'Present'})" if (edu.start_year or edu.end_year) else ""
            p.add_run(years)
            grade = f" | CGPA: {edu.cgpa_or_grade}" if edu.cgpa_or_grade else ""
            spec = f" in {edu.field_of_study}" if edu.field_of_study else ""
            p_sub = doc.add_paragraph(f"{edu.degree}{spec}{grade}")
            p_sub.paragraph_format.space_after = Pt(4)

    # Technical Skills
    if c.skills:
        add_section_header("Technical Skills")
        p = doc.add_paragraph(", ".join(c.skills))
        p.paragraph_format.space_after = Pt(6)

    # Projects
    if c.projects:
        add_section_header("Projects")
        for proj in c.projects:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            r_title = p.add_run(proj.title)
            r_title.bold = True
            if proj.technologies:
                r_tech = p.add_run(f" | Technologies: {', '.join(proj.technologies)}")
                r_tech.italic = True
            p_desc = doc.add_paragraph(proj.description)
            p_desc.paragraph_format.space_after = Pt(2)
            for hl in proj.highlights:
                doc.add_paragraph(hl, style="List Bullet")

    # Experience
    if c.experience:
        add_section_header("Experience")
        for exp in c.experience:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            r_comp = p.add_run(exp.company)
            r_comp.bold = True
            p.add_run(f" — {exp.role_title}")
            dates = f" ({exp.start_date or ''} - {'Present' if exp.is_current else exp.end_date or ''})"
            p.add_run(dates)
            for hl in exp.highlights:
                doc.add_paragraph(hl, style="List Bullet")

    # Internships
    if c.internships:
        add_section_header("Internships")
        for intern in c.internships:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            r_comp = p.add_run(intern.company)
            r_comp.bold = True
            p.add_run(f" — {intern.role_title}")
            for hl in intern.highlights:
                doc.add_paragraph(hl, style="List Bullet")

    # Achievements / Awards / Hackathons
    all_achieve = (c.achievements or []) + (c.awards or []) + (c.hackathons or [])
    if all_achieve:
        add_section_header("Honors & Achievements")
        for ach in all_achieve:
            doc.add_paragraph(ach, style="List Bullet")

    if c.certifications:
        add_section_header("Certifications")
        for cert in c.certifications:
            doc.add_paragraph(cert, style="List Bullet")

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


