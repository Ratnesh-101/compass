"""
Compass — Career Copilot Profile Sources Ingestion Service.

Parses explicitly user-provided external profile information (pasted LinkedIn sections,
LinkedIn Save to PDF text, LinkedIn data archives, and portfolio URLs) without unauthorized web scraping.
Guarantees source attribution, anti-hallucination compliance, and strict input validation.
"""
from __future__ import annotations

import csv
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from backend.models_career import (
    ExternalProfileImportRequest, ExternalProfileSource, ResumeContent,
    ResumeEducationItem, ResumeExperienceItem, ResumeProjectItem, safe_http_url,
)
from backend.services.career_profile_archive import (
    _build_import_summary, _detect_csv_type, _parse_linkedin_export_csv,
    _populate_content_from_csv, _read_csv_dict_rows, _route_experience_item, parse_linkedin_archive_zip,
)

try:
    from backend.services.career_github import sanitize_external_text
except ImportError:
    def sanitize_external_text(text: Optional[str], max_len: int = 2500) -> str:
        return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text[:200000])[:max_len].strip() if text else ""

try:
    from backend.services.career_file_parser import extract_resume_from_file_bytes
except ImportError:
    from backend.services.career_resume import extract_resume_from_file_bytes  # type: ignore

try:
    from backend.services.resume_merge import merge_resume_content
except ImportError:
    from backend.services.career_resume import merge_resume_content  # type: ignore

logger = logging.getLogger("compass.services.career_profile_sources")

_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]{0,10}\.?"
_DATE_OR_DURATION_RE = re.compile(
    rf"\b{_MONTHS}[ \t]+(?:19|20)\d\d\b|\b(?:19|20)\d\d[ \t]{{0,5}}[-–—][ \t]{{0,5}}(?:(?:19|20)\d\d|present)\b"
    r"|\b\d{1,4}[ \t]{0,5}(?:yrs?|mos?|years?|months?)\b",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(
    rf"\b({_MONTHS}[ \t]{{1,5}}(?:19|20)\d\d|(?:19|20)\d\d)[ \t]{{0,5}}[-–—][ \t]{{0,5}}({_MONTHS}[ \t]{{1,5}}(?:19|20)\d\d|(?:19|20)\d\d|[Pp]resent)\b",
    re.IGNORECASE,
)
_YEAR_RANGE_RE = re.compile(r"\b(19\d\d|20\d\d)\b(?:[ \t]{0,5}[-–—][ \t]{0,5}\b(19\d\d|20\d\d)\b)?", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,63}\b")
_PHONE_LABEL_RE = re.compile(r"\((?:Mobile|Home|Work|Direct)\)", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?)?\d{3,5}[\s.-]?\d{3,5}(?:[ \t]?\((?:Mobile|Home|Work|Direct)\))?",
    re.IGNORECASE,
)
_LINKEDIN_URL_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9_\-%]{1,100})", re.IGNORECASE)
_GITHUB_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_\-]{1,100})", re.IGNORECASE)
_PORTFOLIO_LABELS_RE = re.compile(r"\((?:Portfolio|Personal Website|Blog|Website)\)", re.IGNORECASE)
_FOOTER_RE = re.compile(r"^(?:page[ \t]{1,5}\d{1,5}[ \t]{1,5}of[ \t]{1,5}\d{1,5}|\d{1,5}[ \t]{0,5}/[ \t]{0,5}\d{1,5})$", re.IGNORECASE)
_LANG_PROFICIENCY_RE = re.compile(r"\((?:Native(?:[ \t]{1,5}or[ \t]{1,5}Bilingual)?|Full Professional|Professional Working|Limited Working|Elementary)\)", re.IGNORECASE)
_PROFICIENCY_WORDS = {"native", "native or bilingual", "full professional", "professional working", "limited working", "elementary", "bilingual", "fluent", "professional"}
_PARTICLES = {"de", "van", "von", "bin", "al", "del", "da", "di", "la", "le", "du"}
_CERT_KEYWORDS = {"practitioner", "certified", "certificate", "certification", "credential", "license"}
_COUNTRY_ENDINGS = ("india", "usa", "united states", "uk", "canada", "germany", "singapore")
_URL_LIKE_RE = re.compile(
    r"(?:https?://|www\.|\b[a-z0-9_\-]{1,63}\.(?:com|org|net|edu|gov|io|ai|co|dev|me|info|app|so|tech)\b|\b[a-z0-9_\-]{1,63}\.[a-z]{2,63}/)",
    re.IGNORECASE,
)

_SECTION_HEADERS: Dict[str, str] = {
    "about": "about", "summary": "about", "professional summary": "about",
    "experience": "experience", "work experience": "experience", "employment": "experience",
    "education": "education", "academics": "education", "skills": "skills", "top skills": "skills",
    "licenses & certifications": "certifications", "certifications": "certifications", "certificates": "certifications",
    "honors-awards": "awards", "honors & awards": "awards", "honors and awards": "awards", "honors": "awards", "awards": "awards",
    "publications": "publications", "projects": "projects", "personal projects": "projects",
    "volunteer experience": "volunteering", "volunteering": "volunteering", "languages": "languages",
    "contact": "contact", "contact information": "contact", "patents": "patents", "patent": "patents",
}
_LEFT_COLUMN_SECTIONS = {
    "contact", "skills", "languages", "certifications", "awards", "publications", "patents",
}
_EMPLOYMENT_TYPES = {"full-time", "part-time", "internship", "contract", "freelance", "self-employed"}
_ROLE_COMPANY_SEPARATORS = (" - ", " – ", " — ", " | ", " at ", " @ ", " · ")
_INSTITUTION_WORDS = {"university", "college", "institute", "school", "academy", "iit", "polytechnic"}
_DEGREE_WORDS = {"bachelor", "bachelors", "bachelor's", "master", "masters", "master's", "degree", "bs", "ms", "b.tech", "m.tech", "btech", "mtech", "b.sc", "m.sc", "bsc", "msc", "mba", "phd", "diploma", "b.e", "m.e"}
_MAX_NAME_LENGTH, _MAX_NAME_WORDS, _MAX_ABOUT_LINES = 40, 5, 10
_MAX_TITLE_LENGTH, _MAX_SKILL_LENGTH, _MAX_SKILLS = 70, 35, 40


def _is_date_or_duration_line(line: str) -> bool:
    line = line[:2000]
    return bool(_DATE_OR_DURATION_RE.search(line))


def _extract_dates_from_line(line: str) -> Tuple[Optional[str], Optional[str], bool]:
    line = line[:2000]
    m = _DATE_RANGE_RE.search(line)
    if m:
        s, e = m.group(1).strip(), m.group(2).strip()
        return s, e, "present" in e.lower()
    return None, None, False


def _section_for_line(line: str) -> Tuple[Optional[str], str]:
    clean = line.strip(" -#*•")
    head, sep, tail = clean.partition(":")
    sec = _SECTION_HEADERS.get(head.strip().lower())
    return (sec, tail.strip() if sep else "") if sec is not None else (None, "")


def _words(line: str) -> Set[str]:
    return {w.strip(".,;:()[]") for w in line.lower().replace("/", " ").split()}


def _split_skill_tokens(text: str) -> List[str]:
    text = text[:2000]
    cleaned = [tok.strip(" -:*•") for tok in re.split(r"[,•|]+", text)]
    return [c for c in cleaned if c and 1 < len(c) < _MAX_SKILL_LENGTH]


def _split_role_company(line: str) -> Tuple[str, str]:
    lowered = line.lower()
    best, best_sep = -1, ""
    for sep in _ROLE_COMPANY_SEPARATORS:
        idx = lowered.find(sep)
        if idx > 0 and (best < 0 or idx < best):
            best, best_sep = idx, sep
    if best < 0:
        return line.strip(), ""
    return line[:best].strip(), line[best + len(best_sep):].strip()


def _is_proficiency_line(line: str) -> bool:
    line = line[:2000]
    clean = line.strip().lower()
    if not clean:
        return False
    if _LANG_PROFICIENCY_RE.search(line):
        return True
    inner = clean.strip("()").strip()
    return inner in _PROFICIENCY_WORDS


def _is_name_candidate(line: str) -> bool:
    clean = line.strip()
    if not clean or len(clean) > _MAX_NAME_LENGTH:
        return False
    if _section_for_line(clean)[0] is not None or clean.lower() in _SECTION_HEADERS:
        return False
    if _is_footer_line(clean) or _is_proficiency_line(clean):
        return False
    if _EMAIL_RE.search(clean) or _URL_LIKE_RE.search(clean):
        return False
    if not all(ch.isalpha() or ch in " '-." for ch in clean):
        return False
    words = clean.split()
    if not (2 <= len(words) <= 4):
        return False
    for w in words:
        w_clean = w.strip("'-.")
        if not w_clean:
            return False
        if w_clean.lower() in _PARTICLES:
            continue
        if not w_clean[0].isupper():
            return False
    if any(w.lower().strip("'-.") in _CERT_KEYWORDS for w in words):
        return False
    return True


def _looks_like_name(line: str) -> bool:
    clean = line.strip()
    words = clean.split()
    if not clean or len(clean) > _MAX_NAME_LENGTH or not (2 <= len(words) <= _MAX_NAME_WORDS):
        return False
    lower = clean.lower()
    if lower in _SECTION_HEADERS or _section_for_line(clean)[0] is not None:
        return False
    if _is_proficiency_line(clean) or _is_footer_line(clean):
        return False
    if _EMAIL_RE.search(clean) or _URL_LIKE_RE.search(clean):
        return False
    if any(ch.isdigit() or ch in "@|:·/\\=" for ch in clean):
        return False
    return True


def _has_preamble(lines: List[str]) -> bool:
    for line in lines[:5]:
        if _is_footer_line(line):
            continue
        sec, _ = _section_for_line(line)
        low = line.strip().lower()
        if sec in ("contact", "languages") or low in ("top skills", "contact", "contact information", "languages"):
            return True
        if sec is not None or _is_name_candidate(line):
            return False
    return False


def _looks_like_location(line: str) -> bool:
    clean = line.strip()
    if not clean or len(clean) > 80:
        return False
    lower = clean.lower()
    if lower in _SECTION_HEADERS or _is_date_or_duration_line(clean) or _is_footer_line(clean):
        return False
    if lower.startswith("location:"):
        return True
    words = clean.split()
    if "," in clean and len(words) >= 2:
        return True
    if any(lower.endswith(c) or lower == c for c in _COUNTRY_ENDINGS):
        return True
    return any(loc in lower for loc in ("area", "remote", "united states", "canada", "kingdom", "germany", "india"))


def _is_footer_line(line: str, full_name: str = "") -> bool:
    line = line[:2000]
    clean = line.strip()
    if not clean or _FOOTER_RE.match(clean):
        return True
    if re.search(r"\bpage[ \t]{1,5}\d{1,5}[ \t]{1,5}(?:of[ \t]{1,5}\d{1,5}|\d{1,5})\b", clean, re.IGNORECASE):
        return True
    if full_name and clean.lower() == full_name.lower():
        return True
    return bool(full_name and re.match(rf"^{re.escape(full_name)}[ \t]{0,5}(?:[-–—|][ \t]{0,5})?page[ \t]{1,5}\d{1,5}", clean, re.IGNORECASE))


def _extract_phone_from_text(text: str) -> Optional[str]:
    text = text[:200000]
    for line in text.splitlines():
        clean = line.strip()[:2000]
        if not clean or _is_date_or_duration_line(clean):
            continue
        m = _PHONE_RE.search(clean)
        if m:
            val = m.group(0).strip()
            num_digits = len(re.sub(r"\D", "", val))
            has_kw = any(kw in clean.lower() for kw in ("(mobile)", "(home)", "(work)", "(direct)", "phone", "tel:")) or clean.startswith(("+", "("))
            if (has_kw and 7 <= num_digits <= 15) or (10 <= num_digits <= 15 and not _YEAR_RANGE_RE.search(val)):
                return _PHONE_LABEL_RE.sub("", val).strip()
    return None


def _extract_linkedin_url_from_text(text: str) -> Optional[str]:
    text = text[:200000]
    m = _LINKEDIN_URL_RE.search(text)
    if m:
        slug = m.group(1).rstrip("/").removesuffix("(LinkedIn)").strip()
        if slug:
            return f"https://www.linkedin.com/in/{slug}"
    return None


def _extract_links_from_text(text: str) -> Tuple[Optional[str], List[str]]:
    text = text[:200000]
    github_or_portfolio: Optional[str] = None
    relevant_links: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()[:2000]
        if not line:
            continue
        gm = _GITHUB_URL_RE.search(line)
        if gm and not github_or_portfolio:
            u = gm.group(1)
            if u.lower() not in ("in", "share", "jobs", "settings", "learning"):
                safe = safe_http_url(f"https://github.com/{u}")
                if safe:
                    github_or_portfolio = safe
        if _PORTFOLIO_LABELS_RE.search(line):
            urls = re.findall(r"https?://[^\s)]+", line)
            if not urls:
                for tok in line.split():
                    if "." in tok and not tok.startswith("("):
                        urls.append("https://" + tok.lstrip("https:/"))
            for u in urls:
                safe = safe_http_url(u)
                if safe and not github_or_portfolio:
                    github_or_portfolio = safe
                    break
        for raw_url in re.findall(r"https?://[^\s)>]+", line):
            safe = safe_http_url(raw_url)
            if safe and "linkedin.com" not in safe.lower() and safe != github_or_portfolio and safe not in relevant_links:
                relevant_links.append(safe)
    return github_or_portfolio, relevant_links


def _parse_education_line(line: str, education: List[ResumeEducationItem]) -> None:
    line = line[:2000]
    if _is_footer_line(line):
        return
    ym = _YEAR_RANGE_RE.search(line)
    start_year, end_year = None, None
    if ym:
        s_y, e_y = ym.group(1), ym.group(2)
        start_year = int(s_y) if s_y else None
        end_year = int(e_y) if e_y else start_year
        if e_y is None and start_year:
            end_year, start_year = start_year, None
    clean = _YEAR_RANGE_RE.sub("", line).strip(" ·()[],")
    if not clean:
        if ym and education and education[-1].end_year is None:
            education[-1].start_year, education[-1].end_year = start_year, end_year
        return
    words = _words(clean)
    has_inst, has_deg = bool(words & _INSTITUTION_WORDS), bool(words & _DEGREE_WORDS)
    if has_deg:
        if " - " in clean:
            deg = clean.split(" - ")[0].strip()
            field = clean.rpartition(",")[2].strip() if "," in clean else None
        elif "," in clean:
            d_p, _, f_p = clean.partition(",")
            deg, field = d_p.strip(), f_p.strip()
        else:
            deg, field = clean.strip(), None
        if education and not education[-1].degree:
            last = education[-1]
            last.degree = sanitize_external_text(deg)
            last.field_of_study = sanitize_external_text(field) if field else None
            if start_year:
                last.start_year = start_year
            if end_year:
                last.end_year = end_year
        else:
            education.append(ResumeEducationItem(
                institution="", degree=sanitize_external_text(deg),
                field_of_study=sanitize_external_text(field) if field else None,
                start_year=start_year, end_year=end_year,
            ))
    elif has_inst:
        education.append(ResumeEducationItem(
            institution=sanitize_external_text(clean), degree="", start_year=start_year, end_year=end_year,
        ))


def parse_pasted_linkedin_text(raw_text: str) -> Tuple[ResumeContent, List[str]]:
    """
    Parses candidate-pasted LinkedIn profile sections or LinkedIn 'Save to PDF' text without web scraping.
    Extracts structured Experience, Internships, Education, Skills, Projects, Certifications,
    Awards, Publications, Volunteering, Summary, Contact details, and URLs.
    """
    raw_text = raw_text[:200000]
    notes: List[str] = ["Source: User-pasted LinkedIn profile data"]
    lines = [line.strip()[:2000] for line in raw_text.splitlines() if line.strip()]
    full_name, headline, location = "", "", ""
    name_line_indices: Set[int] = set()
    summary_lines, skills, certifications, awards, publications, volunteering = [], [], [], [], [], []
    education: List[ResumeEducationItem] = []
    experience: List[ResumeExperienceItem] = []
    internships: List[ResumeExperienceItem] = []
    projects: List[ResumeProjectItem] = []
    current_section: Optional[str] = None
    has_preamble = _has_preamble(lines)
    first_main_sec_idx = next(
        (i for i, ln in enumerate(lines) if _section_for_line(ln)[0] is not None and (not has_preamble or _section_for_line(ln)[0] not in _LEFT_COLUMN_SECTIONS)),
        len(lines),
    )

    # Pass 1: Select full_name, headline, location
    chosen_idx = -1
    for i in range(first_main_sec_idx):
        line = lines[i]
        if not _is_name_candidate(line):
            continue
        has_sec = False
        first_sec_idx: Optional[int] = None
        for k in range(i + 1, min(i + 11, len(lines))):
            sec, _ = _section_for_line(lines[k])
            if sec in ("about", "experience", "education"):
                has_sec = True
                first_sec_idx = k
                break
        has_loc = False
        for j in range(i + 1, min(i + 7, len(lines))):
            if first_sec_idx is not None and j >= first_sec_idx:
                break
            sec, _ = _section_for_line(lines[j])
            if sec is not None:
                break
            if _looks_like_location(lines[j]):
                has_loc = True
                break
        if has_loc and has_sec:
            chosen_idx = i
            break

    # Fallback if none satisfies look-ahead conditions
    if chosen_idx == -1:
        curr_b: Optional[str] = None
        for i in range(first_main_sec_idx):
            line = lines[i]
            sec, _ = _section_for_line(line)
            if sec is not None:
                curr_b = sec
                continue
            if curr_b in ("contact", "skills", "languages"):
                continue
            if _is_name_candidate(line) or (_looks_like_name(line) and not _is_proficiency_line(line)):
                chosen_idx = i
                break

    if chosen_idx != -1:
        full_name = lines[chosen_idx]
        name_line_indices.add(chosen_idx)
        cur = chosen_idx + 1
        while cur < len(lines) and _is_footer_line(lines[cur], full_name):
            cur += 1
        if cur < len(lines):
            c_line = lines[cur]
            sec_h, _ = _section_for_line(c_line)
            if sec_h is None and not _looks_like_location(c_line):
                headline = c_line
                name_line_indices.add(cur)
                cur += 1
        while cur < len(lines):
            c_line = lines[cur]
            if _is_footer_line(c_line, full_name):
                cur += 1
                continue
            sec_h, _ = _section_for_line(c_line)
            if sec_h is not None:
                break
            if _looks_like_location(c_line):
                location = c_line.lstrip("Location:").strip()
                name_line_indices.add(cur)
                break
            cur += 1

    current_exp_item: Optional[ResumeExperienceItem] = None
    pending_exp_lines: List[str] = []
    expecting_exp_location = False
    after_date_range = False

    def _flush_pending_exp() -> None:
        nonlocal current_exp_item
        if not pending_exp_lines:
            return
        if len(pending_exp_lines) == 1:
            rp, cp = _split_role_company(pending_exp_lines[0])
        else:
            p1, p2 = pending_exp_lines[-1], pending_exp_lines[-2]
            cp, rp = (p1.split("·")[0], p2) if " · " in p1 else (_split_role_company(p1)[1], _split_role_company(p1)[0]) if any(s in p1 for s in _ROLE_COMPANY_SEPARATORS) else (p1, p2)
        it = ResumeExperienceItem(company=sanitize_external_text(cp), role_title=sanitize_external_text(rp))
        _route_experience_item(it, experience, internships)
        current_exp_item = it
        pending_exp_lines.clear()

    def _is_new_job_start(idx: int) -> bool:
        cur = lines[idx]
        if _is_footer_line(cur, full_name):
            return False
        if _section_for_line(cur)[0] is not None:
            return True
        if cur.startswith(("-", "•", "*")) or _is_date_or_duration_line(cur):
            return False
        k1 = next((k for k in range(idx + 1, len(lines)) if not _is_footer_line(lines[k], full_name)), None)
        if k1 is None or _section_for_line(lines[k1])[0] is not None:
            return False
        l1 = lines[k1]
        if ((" · " in l1 or " • " in l1) and any(e in l1.lower() for e in _EMPLOYMENT_TYPES)) or (" · " in l1 and len(l1) <= 100 and not l1.startswith(("-", "•", "*"))):
            return True
        if any(sep in cur for sep in _ROLE_COMPANY_SEPARATORS) and _is_date_or_duration_line(l1):
            return True
        k2 = next((k for k in range(k1 + 1, len(lines)) if not _is_footer_line(lines[k], full_name)), None)
        if k2 is not None and _section_for_line(lines[k2])[0] is None:
            l2 = lines[k2]
            if _is_date_or_duration_line(l2) and not _is_date_or_duration_line(l1) and not l1.startswith(("-", "•", "*")) and len(cur) <= 100 and len(l1) <= 100:
                return True
        return False

    # Pass 2: parse sections
    for i, line in enumerate(lines):
        if _is_footer_line(line, full_name):
            continue
        if i in name_line_indices:
            if current_section in _LEFT_COLUMN_SECTIONS:
                current_section = None
            continue
        section, remainder = _section_for_line(line)
        if section is not None:
            if current_section == "experience":
                _flush_pending_exp()
            current_section = section
            expecting_exp_location = False
            after_date_range = False
            if section == "skills" and remainder:
                for tok in _split_skill_tokens(remainder):
                    if not _is_proficiency_line(tok) and tok not in skills and len(skills) < _MAX_SKILLS:
                        skills.append(tok)
            continue

        if not full_name and current_section is None and _looks_like_name(line):
            full_name = line
            name_line_indices.add(i)
            continue

        if current_section == "about":
            if len(summary_lines) < _MAX_ABOUT_LINES:
                summary_lines.append(line)
        elif current_section == "skills":
            if _is_proficiency_line(line):
                continue
            for tok in _split_skill_tokens(line):
                if not _is_proficiency_line(tok) and tok not in skills and len(skills) < _MAX_SKILLS:
                    skills.append(tok)
        elif current_section == "education":
            if not _is_footer_line(line, full_name):
                _parse_education_line(line, education)
        elif current_section == "experience":
            if _is_date_or_duration_line(line):
                sd, ed, ic = _extract_dates_from_line(line)
                if not (sd or ed or ic):
                    continue
                role, company = "", ""
                if pending_exp_lines:
                    prev1 = pending_exp_lines[-1]
                    prev2 = pending_exp_lines[-2] if len(pending_exp_lines) >= 2 else ""
                    if " · " in prev1:
                        company = prev1.split("·")[0].strip()
                        role = prev2.strip()
                    elif any(sep in prev1 for sep in _ROLE_COMPANY_SEPARATORS):
                        role, company = _split_role_company(prev1)
                    else:
                        role = prev2.strip() if prev2 else prev1.strip()
                        company = prev1.strip() if prev2 else ""
                item = ResumeExperienceItem(
                    company=sanitize_external_text(company),
                    role_title=sanitize_external_text(role),
                    start_date=sd,
                    end_date=ed,
                    is_current=ic,
                )
                _route_experience_item(item, experience, internships)
                current_exp_item = item
                pending_exp_lines.clear()
                expecting_exp_location = True
                after_date_range = True
                continue

            if expecting_exp_location:
                expecting_exp_location = False
                if _looks_like_location(line):
                    if hasattr(current_exp_item, "location"):
                        setattr(current_exp_item, "location", sanitize_external_text(line))
                    continue

            if line.startswith(("-", "•", "*")):
                cl = sanitize_external_text(line.lstrip("-•* ").strip())
                if current_exp_item and cl:
                    current_exp_item.highlights.append(cl)
                continue

            if after_date_range and current_exp_item is not None:
                if not _is_new_job_start(i):
                    cl = sanitize_external_text(line)
                    if cl:
                        current_exp_item.highlights.append(cl)
                    continue
                else:
                    after_date_range = False

            pending_exp_lines.append(line)

        elif current_section == "projects":
            if line.startswith(("-", "•", "*")) and projects:
                d = sanitize_external_text(line.lstrip("-•* ").strip())
                projects[-1].description = (projects[-1].description + " " + d).strip()
            else:
                pt, pd = _split_role_company(line)
                projects.append(ResumeProjectItem(title=sanitize_external_text(pt), description=sanitize_external_text(pd)))
        elif current_section in ("certifications", "awards", "publications", "volunteering"):
            if _is_proficiency_line(line):
                continue
            val = sanitize_external_text(line.lstrip("-•* ").strip())
            dest = {"certifications": certifications, "awards": awards, "publications": publications, "volunteering": volunteering}[current_section]
            if val and val not in dest:
                dest.append(val)

    if current_section == "experience":
        _flush_pending_exp()

    about_text = " ".join(summary_lines).strip()
    summary = f"{headline.rstrip('.')}. {about_text}" if headline and about_text else (headline or about_text or None)
    email = _EMAIL_RE.search(raw_text)
    gh, rel_links = _extract_links_from_text(raw_text)

    content = ResumeContent(
        full_name=full_name, email=email.group(0) if email else "", phone=_extract_phone_from_text(raw_text),
        location=location or None, github_or_portfolio=gh, linkedin_url=_extract_linkedin_url_from_text(raw_text),
        summary=sanitize_external_text(summary, max_len=1200) if summary else None, skills=skills,
        education=education, experience=experience, internships=internships, projects=projects,
        certifications=certifications, awards=awards, publications=publications,
        leadership_and_volunteering=volunteering, relevant_links=rel_links,
        evidence_classifications={"source": ExternalProfileSource.LINKEDIN_PASTED_TEXT.value},
    )
    summary_note = _build_import_summary(content)
    content.evidence_notes["import_summary"] = summary_note
    notes.append(summary_note)
    return content, notes


parse_linkedin_profile_text = parse_pasted_linkedin_text


def ingest_external_profile_file(
    data: bytes,
    filename: str,
    content_type: Optional[str] = None,
) -> Tuple[ResumeContent, List[str]]:
    """
    Ingests candidate profile file (LinkedIn archive ZIP, LinkedIn Save to PDF, or CSV export).
    Never writes to disk. Returns structured ResumeContent with source attribution.
    """
    if not data:
        raise ValueError("Uploaded file is empty (0 bytes).")
    if len(data) > 25 * 1024 * 1024:
        raise ValueError(
            "That file is larger than 25 MB. In LinkedIn choose only Profile, Positions, Education, Skills and Certifications when you request your data, or use Save to PDF."
        )

    fn_lower = (filename or "").lower()
    if fn_lower.endswith(".zip") and not data.startswith(b"PK\x03\x04"):
        raise ValueError(
            "That file does not look like a LinkedIn data download (.zip). Request your data from LinkedIn and upload the zip you receive, or use Save to PDF."
        )
    if fn_lower.endswith(".pdf") and not data.startswith(b"%PDF"):
        raise ValueError(
            "That file is not a valid PDF. In LinkedIn open your profile, choose More > Save to PDF and upload that file."
        )

    if data.startswith(b"PK\x03\x04"):
        return parse_linkedin_archive_zip(data)

    if data.startswith(b"%PDF"):
        if extract_resume_from_file_bytes is None:
            raise ValueError("PDF parsing service is unavailable in the environment.")
        result = extract_resume_from_file_bytes(data, filename=filename, content_type=content_type)
        if not result.success:
            raise ValueError(result.error_message or "Failed to extract text from PDF.")

        full_text = result.full_text or result.raw_text
        content, _ = parse_linkedin_profile_text(full_text)
        found_sections = sum(1 for s in [content.experience, content.education, content.skills] if len(s) > 0)
        if found_sections < 2 and result.extracted_content and merge_resume_content:
            content = merge_resume_content(existing=result.extracted_content, incoming=content)

        content.evidence_classifications["source"] = ExternalProfileSource.LINKEDIN_PASTED_TEXT.value
        summary_note = _build_import_summary(content)
        content.evidence_notes["import_summary"] = summary_note
        return content, [summary_note]

    text = data.decode("utf-8", errors="replace")
    first_non_empty = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first_clean = first_non_empty.strip().lower().replace('"', '').replace("'", "")
    is_csv = (
        fn_lower.endswith(".csv")
        or first_clean in ("name", "skill", "skills")
        or ("," in first_non_empty and _detect_csv_type(first_non_empty) is not None)
    )
    if is_csv:
        content = _parse_linkedin_export_csv(text)
        summary_note = _build_import_summary(content)
        content.evidence_notes["import_summary"] = summary_note
        return content, ["Parsed LinkedIn data archive export.", summary_note]

    return parse_linkedin_profile_text(text)


def ingest_external_profile(request: ExternalProfileImportRequest) -> Tuple[ResumeContent, List[str]]:
    """Safely routes external profile ingestion according to user-selected source type."""
    if request.source_type == ExternalProfileSource.LINKEDIN_PASTED_TEXT:
        return parse_pasted_linkedin_text(request.raw_content)
    if request.source_type == ExternalProfileSource.LINKEDIN_DATA_EXPORT:
        try:
            content = _parse_linkedin_export_csv(request.raw_content)
            summary = _build_import_summary(content)
            content.evidence_notes["import_summary"] = summary
            return content, ["Parsed LinkedIn data archive export.", summary]
        except csv.Error:
            return parse_pasted_linkedin_text(request.raw_content)
    if request.source_type == ExternalProfileSource.PORTFOLIO_SITE:
        content_text = (request.raw_content or "")[:200000]
        urls = [u for u in (safe_http_url(f) for f in re.findall(r"https?://[^\s]+", content_text)) if u]
        content = ResumeContent(
            github_or_portfolio=safe_http_url(request.source_url) or (urls[0] if urls else None),
            relevant_links=urls,
            evidence_classifications={"source": ExternalProfileSource.PORTFOLIO_SITE.value},
        )
        return content, [f"Extracted portfolio references from {request.source_url or 'user input'}."]
    return parse_pasted_linkedin_text(request.raw_content)
