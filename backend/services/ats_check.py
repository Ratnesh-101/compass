"""
Compass - ATS parsing estimate (T-022).

A transparent, rule-based estimate of how a simple applicant tracking system would read a resume:
which sections it can find, which job keywords the text lacks, and what formatting could trip a
parser. It is labelled an estimate everywhere: no real ATS is called and the score is not a
prediction of any employer's result.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

PREVIEW_CHARS = 700
MAX_KEYWORDS = 40
LONG_BULLET_WORDS = 40
LONG_DESCRIPTION_CHARS = 450

# Words that are never useful as a keyword gap.
_STOP = frozenset(
    "and the for with you your our are will have has can using use work team role intern internship "
    "experience skills ability strong good knowledge plus preferred required years year student students".split()
)
_TECH_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,24}")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def flatten_resume_text(content: Any) -> str:
    """The text an ATS would extract, in reading order."""
    if isinstance(content, str):
        return content.strip()
    parts: List[str] = []
    parts.append(" | ".join(x for x in (_get(content, "full_name", ""), _get(content, "email", ""), _get(content, "phone") or "") if x))
    if _get(content, "summary"):
        parts.append(str(_get(content, "summary")))
    for e in _get(content, "education", []) or []:
        parts.append(" ".join(str(x) for x in (_get(e, "institution"), _get(e, "degree"), _get(e, "field_of_study"), _get(e, "start_year"), _get(e, "end_year"), _get(e, "cgpa_or_grade")) if x))
    skills = _get(content, "skills", []) or []
    if skills:
        parts.append("Skills: " + ", ".join(str(s) for s in skills))
    for p in _get(content, "projects", []) or []:
        parts.append(" ".join([str(_get(p, "title", "")), str(_get(p, "description", "")), " ".join(_get(p, "technologies", []) or []), " ".join(_get(p, "highlights", []) or [])]))
    for group in ("experience", "internships"):
        for x in _get(content, group, []) or []:
            parts.append(" ".join([str(_get(x, "role_title", "")), str(_get(x, "company", "")), " ".join(_get(x, "highlights", []) or [])]))
    for group in ("achievements", "certifications", "awards", "hackathons"):
        parts.extend(str(v) for v in (_get(content, group, []) or []))
    return "\n".join(p for p in parts if p and p.strip())


def detect_sections(content: Any) -> List[str]:
    found: List[str] = []
    if _get(content, "full_name") and _get(content, "email"):
        found.append("Contact details")
    if _get(content, "summary"):
        found.append("Summary")
    if _get(content, "education"):
        found.append("Education")
    if _get(content, "skills"):
        found.append("Skills")
    if _get(content, "projects"):
        found.append("Projects")
    if _get(content, "experience") or _get(content, "internships"):
        found.append("Experience")
    if _get(content, "certifications") or _get(content, "achievements") or _get(content, "awards"):
        found.append("Certifications and awards")
    return found


def extract_keywords(required_skills: Optional[Iterable[str]], job_text: str = "") -> List[str]:
    """Keywords to look for: the posting's listed skills first, then capitalised tech-like tokens from its text."""
    keywords: List[str] = []
    seen = set()
    for s in required_skills or []:
        k = str(s).strip()
        if k and k.lower() not in seen:
            keywords.append(k)
            seen.add(k.lower())
    for tok in _TECH_TOKEN_RE.findall(job_text or ""):
        core = tok.strip(".-")
        low = core.lower()
        # Tech-like: has + # or an inner dot (Node.js, C++), or mixed capitals (TypeScript, FastAPI, SQL).
        looks_techy = any(ch in core for ch in "+#.") or (core[:1].isupper() and (any(c.isupper() for c in core[1:]) or core.isupper()))
        if low in seen or low in _STOP or len(low) < 2 or not looks_techy:
            continue
        keywords.append(core)
        seen.add(low)
        if len(keywords) >= MAX_KEYWORDS:
            break
    return keywords[:MAX_KEYWORDS]


def formatting_warnings(content: Any) -> List[str]:
    warnings: List[str] = []
    if not _get(content, "phone"):
        warnings.append("No phone number. Many recruiters and ATS forms expect one.")
    if not (_get(content, "linkedin_url") or _get(content, "github_or_portfolio")):
        warnings.append("No LinkedIn or GitHub link. Add one so a recruiter can see your work.")
    skills = _get(content, "skills", []) or []
    if len(skills) < 5:
        warnings.append("Fewer than 5 skills listed. Keyword matching works better with your full list.")
    if len(skills) > 30:
        warnings.append("More than 30 skills listed. A shorter, targeted list reads better.")
    for e in _get(content, "education", []) or []:
        if not (_get(e, "start_year") or _get(e, "end_year")):
            warnings.append(f"Education entry '{_get(e, 'institution', '')}' has no dates.")
    for p in _get(content, "projects", []) or []:
        if len(str(_get(p, "description", "") or "")) > LONG_DESCRIPTION_CHARS:
            warnings.append(f"Project '{_get(p, 'title', '')}' has a very long description. Shorten it to a few lines.")
        for h in _get(p, "highlights", []) or []:
            if len(str(h).split()) > LONG_BULLET_WORDS:
                warnings.append(f"A bullet in '{_get(p, 'title', '')}' is longer than {LONG_BULLET_WORDS} words.")
                break
    return warnings[:8]


def simulate_ats_check(
    content: Any,
    required_skills: Optional[Iterable[str]] = None,
    job_text: str = "",
) -> Dict[str, Any]:
    """Estimate how a basic ATS reads `content` against an optional job. Pure and deterministic."""
    text = flatten_resume_text(content)
    low = text.lower()
    sections = detect_sections(content)
    keywords = extract_keywords(required_skills, job_text)
    missing = [k for k in keywords if k.lower() not in low]
    warns = formatting_warnings(content)

    core = {"Contact details", "Education", "Skills"}
    section_pts = 15 * len(core & set(sections)) + (10 if ("Projects" in sections or "Experience" in sections) else 0)
    if keywords:
        coverage = (len(keywords) - len(missing)) / len(keywords)
        keyword_pts = round(35 * coverage)
        weights_note = "Score = sections found (55) + job keywords found (35) + formatting (10)."
    else:
        keyword_pts = 35
        weights_note = "No job keywords were available, so the keyword part counts as full. Score = sections (55) + formatting (10) + 35."
    format_pts = max(0, 10 - 2 * len(warns))
    score = max(0, min(100, section_pts + keyword_pts + format_pts))

    return {
        "parsed_text_preview": text[:PREVIEW_CHARS] + ("..." if len(text) > PREVIEW_CHARS else ""),
        "detected_sections": sections,
        "missing_sections": [s for s in ("Contact details", "Education", "Skills", "Projects") if s not in sections and not (s == "Projects" and "Experience" in sections)],
        "keywords_checked": len(keywords),
        "missing_critical_keywords": missing[:15],
        "formatting_warnings": warns,
        "score": float(score),
        "score_explanation": weights_note,
        "is_estimate": True,
        "label": "estimate",
    }
