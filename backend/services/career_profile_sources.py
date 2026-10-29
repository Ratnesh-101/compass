"""
Compass — Career Copilot Profile Sources Ingestion Service.

Parses explicitly user-provided external profile information (pasted LinkedIn sections,
LinkedIn data archives, and portfolio URLs) without unauthorized web scraping.
Guarantees source attribution and anti-hallucination compliance.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from backend.models_career import (
    ExternalProfileImportRequest,
    ExternalProfileSource,
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
    safe_http_url,
)

logger = logging.getLogger("compass.services.career_profile_sources")


_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_DATE_OR_DURATION_RE = re.compile(
    rf"\b{_MONTHS}\s+(?:19|20)\d\d\b|\b(?:19|20)\d\d\s*[-–—]\s*(?:(?:19|20)\d\d|present)\b"
    r"|\b\d+\s*(?:yrs?|mos?|years?|months?)\b",
    re.IGNORECASE,
)


def _is_date_or_duration_line(line: str) -> bool:
    """True for LinkedIn date-range/duration lines like 'Jan 2020 - Present · 3 yrs 5 mos'."""
    return bool(_DATE_OR_DURATION_RE.search(line))


_ABOUT_HEADERS = {"about", "summary"}
_EXPERIENCE_HEADERS = {"experience", "work experience"}
_EDUCATION_HEADERS = {"education", "academics"}
_SKILLS_HEADERS = {"skills", "top skills", "licenses & certifications"}
_SECTION_HEADERS: Dict[str, str] = {
    **{h: "about" for h in _ABOUT_HEADERS},
    **{h: "experience" for h in _EXPERIENCE_HEADERS},
    **{h: "education" for h in _EDUCATION_HEADERS},
    **{h: "skills" for h in _SKILLS_HEADERS},
}
_EMPLOYMENT_TYPES = {"full-time", "part-time", "internship", "contract", "freelance", "self-employed"}
_ROLE_COMPANY_SEPARATORS = (" - ", " – ", " — ", " | ", " at ", " @ ", " · ")
_INSTITUTION_WORDS = {"university", "college", "institute", "school", "academy", "iit"}
_DEGREE_WORDS = {
    "bachelor", "bachelors", "bachelor's", "master", "masters", "master's", "degree", "bs", "ms",
    "b.tech", "m.tech", "btech", "mtech", "b.sc", "m.sc", "bsc", "msc", "mba", "phd", "diploma", "b.e", "m.e",
}
_MAX_NAME_LENGTH = 40
_MAX_NAME_WORDS = 5
_MAX_ABOUT_LINES = 4
_MAX_TITLE_LENGTH = 60
_MAX_SKILL_LENGTH = 35


def _section_for_line(line: str) -> Tuple[Optional[str], str]:
    """Return (section, remainder) when the whole line is a section header (optionally 'Skills: a, b')."""
    head, sep, tail = line.partition(":")
    key = head.strip().lower()
    section = _SECTION_HEADERS.get(key)
    if section is None:
        return None, ""
    return section, tail.strip() if sep else ""


def _words(line: str) -> Set[str]:
    return {w.strip(".,;:()[]") for w in line.lower().replace("/", " ").split()}


def _split_skill_tokens(text: str) -> List[str]:
    cleaned = [tok.strip(" -:*•") for tok in re.split(r"[,•|]+", text)]
    return [c for c in cleaned if c and 1 < len(c) < _MAX_SKILL_LENGTH]


def _split_role_company(line: str) -> Tuple[str, str]:
    """Split on the earliest explicit role/company separator; hyphens inside words are untouched."""
    lowered = line.lower()
    best = -1
    best_sep = ""
    for sep in _ROLE_COMPANY_SEPARATORS:
        idx = lowered.find(sep)
        if idx > 0 and (best < 0 or idx < best):
            best, best_sep = idx, sep
    if best < 0:
        return line.strip(), ""
    return line[:best].strip(), line[best + len(best_sep):].strip()


def _looks_like_name(line: str) -> bool:
    if len(line) > _MAX_NAME_LENGTH or len(line.split()) > _MAX_NAME_WORDS:
        return False
    return not any(ch.isdigit() or ch in "@|:·" for ch in line)


def _parse_experience_line(line: str, lines: List[str], idx: int, experience: List[ResumeExperienceItem]) -> None:
    if _is_date_or_duration_line(line):
        return
    last = experience[-1] if experience else None
    role_part, company_part = _split_role_company(line)
    first_company_token = company_part.split("·")[0].strip().lower()
    if company_part and first_company_token in _EMPLOYMENT_TYPES:
        # LinkedIn layout: previous line is the title, this one is "Company · Full-time".
        if last is not None and not last.company:
            last.company = role_part
        else:
            experience.append(ResumeExperienceItem(company=role_part, role_title=""))
        return
    if company_part:
        experience.append(ResumeExperienceItem(company=company_part, role_title=role_part))
        return
    next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
    precedes_company = "·" in next_line or _is_date_or_duration_line(next_line)
    is_bullet = line.startswith(("-", "•", "*"))
    if last is not None and last.company and (is_bullet or not precedes_company):
        last.highlights.append(line.lstrip("-•* ").strip())
    elif last is not None and not last.company and not is_bullet and not precedes_company:
        last.company = line
    elif not is_bullet and len(line) < _MAX_TITLE_LENGTH:
        experience.append(ResumeExperienceItem(company="", role_title=line))


def _parse_education_line(line: str, education: List[ResumeEducationItem]) -> None:
    words = _words(line)
    has_institution = bool(words & _INSTITUTION_WORDS)
    has_degree = bool(words & _DEGREE_WORDS)
    if not has_institution and not has_degree:
        return
    last = education[-1] if education else None
    if has_degree and not has_institution and last is not None and not last.degree:
        last.degree = line
        return
    inst, deg = _split_role_company(line)
    if not deg and has_degree and not has_institution:
        inst, deg = "", line
    education.append(ResumeEducationItem(institution=inst, degree=deg))


def parse_pasted_linkedin_text(raw_text: str) -> Tuple[ResumeContent, List[str]]:
    """
    Parses candidate-pasted LinkedIn profile sections without web scraping.
    Extracts structured Experience, Education, Skills, and Summary. Only what the text states is
    returned; unknown fields stay empty. Items carry no evidence tag until the candidate confirms
    them through the commit endpoint.
    """
    notes: List[str] = ["Source: User-pasted LinkedIn profile data"]
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

    full_name = ""
    summary_lines: List[str] = []
    skills: List[str] = []
    education: List[ResumeEducationItem] = []
    experience: List[ResumeExperienceItem] = []
    current_section: Optional[str] = None

    for idx, line in enumerate(lines):
        section, remainder = _section_for_line(line)
        if section is not None:
            current_section = section
            if section == "skills":
                skills.extend(s for s in _split_skill_tokens(remainder) if s not in skills)
            continue
        if idx == 0 and _looks_like_name(line):
            full_name = line
            continue

        if current_section == "about":
            if len(summary_lines) < _MAX_ABOUT_LINES:
                summary_lines.append(line)
        elif current_section == "skills":
            skills.extend(s for s in _split_skill_tokens(line) if s not in skills)
        elif current_section == "education":
            _parse_education_line(line, education)
        elif current_section == "experience":
            _parse_experience_line(line, lines, idx, experience)

    content = ResumeContent(
        full_name=full_name,
        summary=" ".join(summary_lines) if summary_lines else None,
        skills=skills,
        education=education,
        experience=experience,
        evidence_classifications={"source": ExternalProfileSource.LINKEDIN_PASTED_TEXT.value},
    )
    return content, notes


_SKILL_CSV_HEADERS = {"name", "skill", "skills"}
_MAX_EXPORT_SKILLS = 20


def _cell(row: List[str], index: int) -> str:
    return row[index].strip() if 0 <= index < len(row) else ""


def _parse_linkedin_export_csv(raw_content: str) -> ResumeContent:
    """Parse a LinkedIn archive CSV (Skills, Positions or Education); other files yield nothing."""
    rows = [r for r in csv.reader(io.StringIO(raw_content)) if any(c.strip() for c in r)]
    skills: List[str] = []
    experience: List[ResumeExperienceItem] = []
    education: List[ResumeEducationItem] = []
    if rows:
        header = [c.strip().lower() for c in rows[0]]
        body = rows[1:]
        if len(header) == 1 and header[0] in _SKILL_CSV_HEADERS:
            skills = [r[0].strip() for r in body if len(r[0].strip()) > 1][:_MAX_EXPORT_SKILLS]
        elif "company name" in header and "title" in header:
            ci, ti = header.index("company name"), header.index("title")
            di = header.index("description") if "description" in header else -1
            for r in body:
                company, title, desc = _cell(r, ci), _cell(r, ti), _cell(r, di)
                if company or title:
                    experience.append(
                        ResumeExperienceItem(company=company, role_title=title, highlights=[desc] if desc else [])
                    )
        elif "school name" in header:
            si = header.index("school name")
            gi = header.index("degree name") if "degree name" in header else -1
            for r in body:
                school = _cell(r, si)
                if school:
                    education.append(ResumeEducationItem(institution=school, degree=_cell(r, gi)))
    return ResumeContent(
        skills=skills,
        experience=experience,
        education=education,
        evidence_classifications={"source": ExternalProfileSource.LINKEDIN_DATA_EXPORT.value},
    )


def ingest_external_profile(request: ExternalProfileImportRequest) -> Tuple[ResumeContent, List[str]]:
    """
    Safely routes external profile ingestion according to user-selected source type.
    Never engages in automated web scraping of LinkedIn.
    """
    if request.source_type == ExternalProfileSource.LINKEDIN_PASTED_TEXT:
        return parse_pasted_linkedin_text(request.raw_content)
    elif request.source_type == ExternalProfileSource.LINKEDIN_DATA_EXPORT:
        try:
            return _parse_linkedin_export_csv(request.raw_content), ["Parsed LinkedIn data archive export."]
        except csv.Error:
            return parse_pasted_linkedin_text(request.raw_content)
    elif request.source_type == ExternalProfileSource.PORTFOLIO_SITE:
        found = re.findall(r"https?://[^\s]+", request.raw_content)
        urls = [u for u in (safe_http_url(f) for f in found) if u]
        content = ResumeContent(
            github_or_portfolio=safe_http_url(request.source_url) or (urls[0] if urls else None),
            relevant_links=urls,
            evidence_classifications={"source": ExternalProfileSource.PORTFOLIO_SITE.value},
        )
        return content, [f"Extracted portfolio references from {request.source_url or 'user input'}."]
    else:
        return parse_pasted_linkedin_text(request.raw_content)
