"""
Compass â€” Career Copilot Job Description Analysis & Requirement Matching Service.

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


_MAX_HEADER_CHARS = 60

_HEADER_PHRASES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("preferred", ("preferred qualifications", "desired qualifications", "preferred", "bonus", "bonus points", "nice to have", "nice-to-have", "nice to haves", "pluses", "a plus")),
    ("mandatory", ("basic qualifications", "minimum qualifications", "required qualifications", "must have", "must haves", "requirements", "minimum requirements", "qualifications")),
    ("responsibilities", ("responsibilities", "what you will do", "what you'll do", "the role", "job description", "key responsibilities")),
    ("skills", ("skills required", "tech stack", "technologies", "required skills")),
)

_PREFERRED_MARKERS = ("plus", "nice to have", "nice-to-have", "bonus", "preferred")


def _section_for_header(line: str) -> Optional[str]:
    """Return the section a line introduces, only for short standalone header lines."""
    if len(line) > _MAX_HEADER_CHARS:
        return None
    has_colon = line.rstrip().endswith(":")
    bare = line.strip().strip("#*_ ").rstrip(":").strip("*_ ").lower()
    for section, phrases in _HEADER_PHRASES:
        for phrase in phrases:
            if bare == phrase or (has_colon and phrase in bare):
                return section
    return None


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def contains_term(text: str, term: str) -> bool:
    """Word-boundary containment (no regex): 'java' does not match 'javascript', 'sql' not 'postgresql'."""
    term = term.strip().lower()
    if not term:
        return False
    hay = text.lower()
    start = 0
    while True:
        idx = hay.find(term, start)
        if idx < 0:
            return False
        end = idx + len(term)
        before_ok = idx == 0 or not _is_word_char(hay[idx - 1])
        after = hay[end] if end < len(hay) else ""
        after_next = hay[end + 1] if end + 1 < len(hay) else ""
        after_ok = not (
            after
            and (_is_word_char(after) or (after in "+#" and not term.endswith(("+", "#"))) or (after == "." and _is_word_char(after_next)))
        )
        if before_ok and after_ok:
            return True
        start = idx + 1


def _dedupe_skills(skills: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for s in skills:
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(s.strip())
    return out


# Alias -> canonical key. Keys are compared after _skill_key() lowercasing/whitespace cleanup.
_SKILL_ALIASES: Dict[str, str] = {
    "js": "javascript", "ecmascript": "javascript",
    "ts": "typescript",
    "py": "python", "python3": "python",
    "cpp": "c++", "cplusplus": "c++", "c plus plus": "c++",
    "csharp": "c#", "c sharp": "c#",
    "golang": "go",
    "node": "node.js", "nodejs": "node.js", "node js": "node.js",
    "react.js": "react", "reactjs": "react",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "open-source": "open source", "opensource": "open source",
    "ml": "machine learning",
}
_NO_SPLIT_SLASH = {"ci/cd", "tcp/ip", "i/o", "ui/ux", "a/b testing"}
_LABEL_MAX_CHARS = 40


def _skill_key(name: str) -> str:
    """Case-insensitive canonical key: lowercased, whitespace collapsed, aliases folded."""
    key = " ".join((name or "").lower().split()).strip(" .;:-*â€¢Â·")
    return _SKILL_ALIASES.get(key, key)


def _skill_variants(key: str) -> Set[str]:
    """All spellings that fold to this canonical key (used for the project-text partial match)."""
    return {key} | {alias for alias, canon in _SKILL_ALIASES.items() if canon == key}


def split_skill_entry(entry: str) -> List[str]:
    """
    Split one saved/required skill entry into individual skill names.
    'Languages: Python, JavaScript, C/C++' -> Python, JavaScript, C/C++, C, C++
    The original combined token (e.g. 'C/C++') is kept alongside its parts.
    """
    text = (entry or "").strip()
    if not text:
        return []
    label, colon, rest = text.partition(":")
    if colon and rest.strip() and "," not in label and len(label) <= _LABEL_MAX_CHARS:
        text = rest  # drop a 'Languages:' / 'Tools:' style prefix
    out: List[str] = []
    for chunk in re.split(r"[,;|â€¢Â·\n]+|\s+&\s+|\s+and\s+", text):
        # 'Python (NumPy, Pandas)' arrives split by the comma; also unwrap simple parentheses
        chunk = chunk.strip().strip("()[]").strip()
        chunk = re.sub(r"\s*\([^)]*\)?\s*$", "", chunk).strip() or chunk
        chunk = chunk.strip(" .:-*")
        if not chunk:
            continue
        out.append(chunk)
        if "/" in chunk and chunk.lower() not in _NO_SPLIT_SLASH:
            out.extend(p.strip() for p in chunk.split("/") if p.strip())
    return out


def build_skill_index(skills: List[str]) -> Dict[str, str]:
    """Canonical skill key -> the saved entry it came from (for evidence text)."""
    index: Dict[str, str] = {}
    for entry in skills or []:
        for part in split_skill_entry(entry):
            index.setdefault(_skill_key(part), entry.strip())
    return index


def skill_in_index(skill: str, index: Dict[str, str]) -> Optional[str]:
    """Saved entry that truly contains `skill` (aliases, case and 'C/C++' parts handled), else None."""
    whole = _skill_key(skill)
    if whole in index:
        return index[whole]
    if "/" in skill and skill.strip().lower() not in _NO_SPLIT_SLASH:
        for part in skill.split("/"):  # 'C/C++' is satisfied by either listed language
            hit = index.get(_skill_key(part))
            if hit:
                return hit
    return None


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
        header = _section_for_header(line)
        if header:
            current_section = header
            continue
        head, colon, tail = line.partition(":")
        if colon and tail.strip():
            inline_header = _section_for_header(head + ":")
            if inline_header:
                # "Skills required: Python, Docker" - header and items on one line
                current_section = inline_header
                line = tail.strip()

        clean_item = line.strip(" -*â€¢Â·")
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
            for tok in re.split(r"[,â€¢|\n]+", clean_item):
                s = tok.strip(" -:*â€¢")
                if s and 1 < len(s) < 35 and s not in skills:
                    skills.append(s)

    return {
        "mandatory": mandatory,
        "preferred": preferred,
        "responsibilities": responsibilities,
        "skills": skills,
    }


_REQ_MARKERS: Tuple[str, ...] = (
    "minimum qualifications", "basic qualifications", "required qualifications", "required skills",
    "skills required", "must have", "must-have", "tech stack", "technologies", "requirements",
    "required", "qualifications",
)
_NICE_MARKERS: Tuple[str, ...] = (
    "preferred qualifications", "preferred skills", "nice to have", "nice-to-have", "good to have",
    "good-to-have", "preferred", "bonus",
)
_OTHER_MARKERS: Tuple[str, ...] = (
    "responsibilities", "key responsibilities", "what you will do", "what you'll do", "about the role",
    "about us", "benefits", "perks", "what we offer",
)
_MARKER_SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("required", _REQ_MARKERS), ("nice", _NICE_MARKERS), ("other", _OTHER_MARKERS),
)
_MAX_WHOLE_LINE_HEADER = 40
_MAX_SKILL_WORDS = 3
_MAX_SKILL_CHARS = 30
_MAX_JOB_SKILLS = 40
_AMBIGUOUS_KEYS = {"go", "r", "c"}
_KNOWN_TECH: Tuple[str, ...] = (
    "Python", "JavaScript", "TypeScript", "React", "Angular", "Vue", "Node.js", "PostgreSQL", "MySQL",
    "MongoDB", "Redis", "FastAPI", "Django", "Flask", "Docker", "Kubernetes", "Git", "SQL", "C++", "C#",
    "Java", "Go", "Rust", "AWS", "Azure", "GCP", "PyTorch", "TensorFlow", "Machine Learning", "Linux",
    "GraphQL", "Kafka", "Terraform", "HTML", "CSS",
)


def _find_headers(line: str) -> List[Tuple[int, int, str]]:
    """Section headers in a line as (start, end, section); 'Requirements:' inline or a bare header line."""
    hay = line.lower()
    found: List[Tuple[int, int, str]] = []
    bare = hay.strip().strip("#*_-: ").strip()
    for section, markers in _MARKER_SECTIONS:
        for marker in markers:
            if bare == marker and len(hay) <= _MAX_WHOLE_LINE_HEADER:
                found.append((0, len(hay), section))
                continue
            start = hay.find(marker)
            while start >= 0:
                end = start + len(marker)
                j = end
                while j < len(hay) and hay[j] == " ":
                    j += 1
                if (start == 0 or not _is_word_char(hay[start - 1])) and j < len(hay) and hay[j] == ":":
                    found.append((start, j + 1, section))
                start = hay.find(marker, start + 1)
    found.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    kept: List[Tuple[int, int, str]] = []
    for item in found:
        if not kept or item[0] >= kept[-1][1]:
            kept.append(item)
    return kept


def _skills_from_chunk(chunk: str) -> List[str]:
    """Skill names from one chunk of a requirements section (short items as written, long bullets by vocabulary)."""
    out: List[str] = []
    for item in split_skill_entry(chunk.replace(". ", ", ")):
        item = item.strip(" .-*â€¢Â·")
        key = _skill_key(item)
        if not key or key[0].isdigit() or "year" in key:
            continue
        if len(item.split()) <= _MAX_SKILL_WORDS and len(item) <= _MAX_SKILL_CHARS:
            out.append(item)
        else:
            out.extend(t for t in _KNOWN_TECH if contains_term(item, t))
    return out


def parse_job_skill_lists(text: str) -> Tuple[List[str], List[str]]:
    """(required, nice_to_have) skills in posting order. Required wins when a skill appears in both."""
    chunks: Dict[str, List[str]] = {"required": [], "nice": []}
    section = "other"
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        pos = 0
        for start, end, new_section in _find_headers(line):
            if section in chunks and start > pos:
                chunks[section].append(line[pos:start])
            section = new_section
            pos = end
        if section in chunks and pos < len(line):
            chunks[section].append(line[pos:])
    required: List[str] = []
    nice: List[str] = []
    seen: Set[str] = set()
    for name, target in (("required", required), ("nice", nice)):
        for chunk in chunks[name]:
            for skill in _skills_from_chunk(chunk):
                key = _skill_key(skill)
                if key not in seen and len(seen) < _MAX_JOB_SKILLS:
                    seen.add(key)
                    target.append(skill)
    return required, nice


def _resume_evidence(skill: str, master: ResumeContent) -> Optional[str]:
    """'project X' / 'experience at Y' when the resume text mentions the skill, else None."""
    key = _skill_key(skill)
    variants = _skill_variants(key)
    ambiguous = key in _AMBIGUOUS_KEYS
    for p in master.projects:
        tech = " ; ".join(p.technologies)
        prose = f"{p.title} {p.description} {' '.join(p.highlights)}"
        if any(contains_term(tech, v) for v in variants) or (
            not ambiguous and any(contains_term(prose, v) for v in variants)
        ):
            return f"project {p.title}"
    for e in list(master.experience) + list(master.internships):
        if not ambiguous and any(contains_term(" ".join(e.highlights), v) for v in variants):
            return f"experience at {e.company}"
    return None


def _join(items: List[str]) -> str:
    return ", ".join(items)


def analyze_job_and_match(
    opportunity: OpportunityOut,
    master: ResumeContent,
    custom_description: Optional[str] = None,
) -> JobAnalysisReport:
    """
    Analyzes an opportunity's requirements and maps evidence from the candidate's master profile.
    Required and nice-to-have skills are extracted separately; every required skill the candidate
    cannot show counts against coverage, so a missing required skill never yields 100%.
    """
    # A blank/whitespace paste falls back to the stored posting text that Company Intel also uses.
    raw_desc = (custom_description or "").strip() or (opportunity.description or "").strip()
    full_text = f"{opportunity.role_title}\n{opportunity.category}\n{raw_desc}"

    sections = extract_job_sections(full_text)
    mandatory = sections["mandatory"]
    preferred = sections["preferred"]
    responsibilities = sections["responsibilities"]

    req_skills, nice_skills = parse_job_skill_lists(full_text)
    if opportunity.requirements and opportunity.requirements.required_skills:
        explicit = [s.strip() for s in opportunity.requirements.required_skills if s.strip()]
        req_skills = _dedupe_skills(explicit + req_skills)
    req_keys = {_skill_key(s) for s in req_skills}
    nice_skills = [s for s in nice_skills if _skill_key(s) not in req_keys]
    skills_list = req_skills
    score_available = bool(skills_list)

    location_info = {
        "location": opportunity.location or "Not specified",
        "is_remote": getattr(opportunity, "work_arrangement", "") == "remote",
        "target_years": getattr(opportunity.requirements, "eligible_graduation_years", []) if opportunity.requirements else [],
    }
    formula = (
        "Skill overlap estimate = required skills you can show / total required skills "
        "(partial = 0.5, matched nice-to-have skills add 0.25 each, never reaching 100% while a required skill is missing)"
    )

    def _gap_action(skill: str) -> Dict[str, Any]:
        return {
            "skill": skill,
            "learning_resource_type": "Official documentation, interactive courses, and hands-on tutorials",
            "project_idea": f"Create a demonstration project showcasing practical {skill} implementation with test suites",
            "evidence_appearance": f"Public GitHub repository with verifiable commits and CI/CD demonstrating {skill}",
        }

    def _report(verdict: str, **kw: Any) -> JobAnalysisReport:
        base: Dict[str, Any] = dict(
            opportunity_id=opportunity.id,
            role_title=opportunity.role_title,
            company_name=opportunity.company_name,
            mandatory_qualifications=mandatory,
            preferred_qualifications=preferred,
            responsibilities=responsibilities,
            required_skills=skills_list,
            location_and_eligibility=location_info,
            summary_verdict=verdict,
            score_available=score_available,
            formula_explanation=formula,
        )
        base.update(kw)
        return JobAnalysisReport(**base)

    if not raw_desc and not skills_list:
        return _report("Paste the job description to analyse it.", score_available=False)

    # Check if candidate profile is complete
    is_empty_profile = (
        not master
        or (not master.skills and not master.projects and not master.education and not (master.full_name or "").strip())
    )

    if is_empty_profile:
        return _report(
            "Complete your profile to view your skill overlap estimate and personalized action plan.",
            missing_critical_skills=skills_list,
            missing_skills=skills_list,
            gap_actions=[_gap_action(s) for s in skills_list],
            has_complete_profile=False,
            profile_missing_message="Complete your profile to view skill overlap analysis. No verified skills found.",
        )

    master_skills_norm = build_skill_index(master.skills)
    learning_skills_norm = build_skill_index(getattr(master, "learning_skills", []))

    matches: List[JobMatchEvidence] = []
    matched_skills: List[str] = []
    partial_skills: List[str] = []
    missing_skills: List[str] = []
    nice_matched: List[str] = []
    nice_missing: List[str] = []
    listed_only: List[str] = []
    shown_notes: List[str] = []
    gap_actions: List[Dict[str, Any]] = []

    for mandatory_flag, group in ((True, skills_list), (False, nice_skills)):
        label = "required" if mandatory_flag else "nice-to-have"
        for skill in group:
            saved_entry = skill_in_index(skill, master_skills_norm)
            learning_entry = skill_in_index(skill, learning_skills_norm)
            shown_in = _resume_evidence(skill, master)
            status, facts, reasoning, conf = "missing_evidence", [], "", 0.9
            if shown_in:
                status, conf = "supported", 1.0
                facts = [f"Shown in your {shown_in}."]
                reasoning = f"{skill} is shown in your {shown_in}."
                if mandatory_flag:
                    shown_notes.append(f"{skill} (shown in your {shown_in})")
            elif saved_entry:
                status, conf = "supported", 0.7
                facts = [f"Listed in your skills: '{saved_entry}'"]
                reasoning = f"You list {skill} in your skills (no project or experience shows it yet)."
                if mandatory_flag:
                    listed_only.append(skill)
            elif learning_entry:
                status, conf = "partial", 0.6
                facts = ["Mentioned in your learning list."]
                reasoning = f"{skill} is on your learning list but not yet a demonstrated skill."
            else:
                reasoning = f"Missing {label}: {skill} is not in your skills, projects or experience."
            if status == "supported":
                (matched_skills if mandatory_flag else nice_matched).append(skill)
            elif status == "partial":
                if mandatory_flag:
                    partial_skills.append(skill)
            else:
                if mandatory_flag:
                    missing_skills.append(skill)
                    gap_actions.append(_gap_action(skill))
                else:
                    nice_missing.append(skill)
            matches.append(
                JobMatchEvidence(
                    requirement=skill,
                    category="technical_skill",
                    is_mandatory=mandatory_flag,
                    match_status=status,
                    supporting_facts=facts,
                    reasoning=reasoning,
                    confidence=conf,
                )
            )

    # Mandatory qualification (degree) checks
    for q in mandatory:
        q_low = q.lower()
        if any(term in q_low for term in ("degree", "bachelor", "b.tech", "computer science")):
            if master.education:
                edu = master.education[0]
                matches.append(JobMatchEvidence(
                    requirement=q, category="qualification", is_mandatory=True, match_status="supported",
                    supporting_facts=[f"Education: {edu.degree} at {edu.institution}"],
                    reasoning="Candidate academic credentials satisfy degree requirements.", confidence=1.0,
                ))
            else:
                matches.append(JobMatchEvidence(
                    requirement=q, category="qualification", is_mandatory=True, match_status="missing_evidence",
                    supporting_facts=[], reasoning="Candidate profile does not contain verified education records.",
                    confidence=0.8,
                ))

    total_req = len(skills_list)
    if total_req:
        score = (len(matched_skills) + 0.5 * len(partial_skills) + 0.25 * len(nice_matched)) / total_req * 100.0
        if missing_skills or partial_skills:
            score = min(score, 99.0)
        skill_overlap = round(min(100.0, score), 1)
    else:
        skill_overlap = 0.0

    if not score_available:
        verdict = (
            "We could not find a requirements list (skills under 'Requirements' or 'Must have') in this posting, "
            "so no skill-match score is shown. Paste the requirements section to analyse it."
        )
    else:
        shown = matched_skills + partial_skills
        parts = [f"Skill overlap estimate: {skill_overlap}% ({len(matched_skills)}/{total_req} required skills shown)."]
        if listed_only:
            parts.append(f"You list {_join(listed_only)} (from your profile).")
        if shown_notes:
            parts.append(f"Shown in your resume: {_join(shown_notes)}.")
        if partial_skills:
            parts.append(f"Partial (learning): {_join(partial_skills)}.")
        parts.append(f"Missing required: {_join(missing_skills)}." if missing_skills else "No required skills missing.")
        if nice_missing:
            parts.append(f"Missing nice-to-have: {_join(nice_missing)}.")
        if not shown and not missing_skills:
            parts = ["No required skills found."]
        verdict = " ".join(parts)

    return _report(
        verdict,
        matches=matches,
        match_score=skill_overlap,
        missing_critical_skills=missing_skills,
        skill_overlap_estimate=skill_overlap,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        partial_skills=partial_skills,
        gap_actions=gap_actions,
        has_complete_profile=True,
        profile_missing_message=None,
    )
