"""
Compass — Career Copilot Profile Archive & CSV Import Service.

Parses official LinkedIn data export ZIP archives and standalone/concatenated
LinkedIn CSV exports (profile.csv, positions.csv, education.csv, skills.csv, etc.)
with strict boundary checks, decompression limits, and safe attribute mapping.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.models_career import (
    ExternalProfileSource,
    ResumeContent,
    ResumeEducationItem,
    ResumeExperienceItem,
    ResumeProjectItem,
    safe_http_url,
)

try:
    from backend.services.career_github import sanitize_external_text
except ImportError:
    def sanitize_external_text(text: Optional[str], max_len: int = 2500) -> str:
        if not text:
            return ""
        clean = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text[:200000])
        return clean[:max_len].strip()

logger = logging.getLogger("compass.services.career_profile_archive")

_YEAR_RANGE_RE = re.compile(r"\b(19\d\d|20\d\d)\b(?:[ \t]{0,5}[-–—][ \t]{0,5}\b(19\d\d|20\d\d)\b)?", re.IGNORECASE)
_WEBSITE_ITEM_RE = re.compile(r"\[([A-Za-z0-9_ -]{1,50}):([^\]\r\n]{1,1000})\]")
_MAX_SKILLS = 40
_ALLOWED_ARCHIVE_BASENAMES = {
    "profile.csv", "positions.csv", "education.csv", "skills.csv", "certifications.csv",
    "projects.csv", "honors.csv", "publications.csv", "volunteering.csv",
    "email addresses.csv", "phonenumbers.csv",
}
_MAX_ARCHIVE_ENTRIES = 500
_MAX_MEMBER_UNCOMPRESSED_BYTES = 5 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 20 * 1024 * 1024


def _route_experience_item(
    item: ResumeExperienceItem,
    experience: List[ResumeExperienceItem],
    internships: List[ResumeExperienceItem],
) -> None:
    t = (item.role_title or "").lower()
    if "intern" in t or "internship" in t:
        internships.append(item)
    else:
        experience.append(item)


def _build_import_summary(content: ResumeContent) -> str:
    parts: List[str] = []
    for f in ("full_name", "email", "phone", "location"):
        if getattr(content, f):
            parts.append(f.replace("full_name", "name"))
    counts = [
        ("role", "roles", len(content.experience)),
        ("internship", "internships", len(content.internships)),
        ("education entry", "education entries", len(content.education)),
        ("skill", "skills", len(content.skills)),
        ("certification", "certifications", len(content.certifications)),
        ("project", "projects", len(content.projects)),
        ("award", "awards", len(content.awards)),
        ("publication", "publications", len(content.publications)),
        ("volunteering entry", "volunteering entries", len(content.leadership_and_volunteering)),
    ]
    for singular, plural, count in counts:
        if count > 0:
            parts.append(f"{count} {singular if count == 1 else plural}")
    return f"Found: {', '.join(parts)}." if parts else "Found: no structured profile entries."


def _read_csv_dict_rows(text: str, expected_col_keywords: List[str]) -> List[Dict[str, str]]:
    text = text[:200000]
    lines = [line[:2000] for line in text.splitlines()]
    header_idx = -1
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in expected_col_keywords):
            header_idx = i
            break
    if header_idx == -1:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    rows: List[Dict[str, str]] = []
    for raw in reader:
        cleaned = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def _populate_content_from_csv(bname: str, text: str, content: ResumeContent) -> None:
    text = text[:200000]
    if bname == "profile.csv":
        rows = _read_csv_dict_rows(text, ["first name", "headline", "summary"])
        if rows:
            r = rows[0]
            first_name, last_name = r.get("first name", ""), r.get("last name", "")
            if first_name or last_name:
                content.full_name = f"{first_name} {last_name}".strip()
            hl, sm = r.get("headline", ""), r.get("summary", "")
            content.summary = f"{hl.rstrip('.')}. {sm}" if hl and sm else (hl or sm or content.summary)
            if r.get("geo location", ""):
                content.location = r.get("geo location", "")
            websites_raw = (r.get("websites", "") or "")[:5000]
            items = _WEBSITE_ITEM_RE.findall(websites_raw)
            first_portfolio = None
            first_github = None
            if items:
                for label_raw, url_raw in items:
                    safe = safe_http_url(url_raw)
                    if not safe:
                        continue
                    if safe not in content.relevant_links:
                        content.relevant_links.append(safe)
                    lbl = label_raw.strip().upper()
                    if lbl in {"PORTFOLIO", "PERSONAL", "BLOG", "OTHER"}:
                        if first_portfolio is None:
                            first_portfolio = safe
                    elif "github.com" in safe.lower():
                        if first_github is None:
                            first_github = safe
            else:
                for u in re.findall(r"https?://[^\s,;\]]+", websites_raw):
                    safe = safe_http_url(u)
                    if not safe:
                        continue
                    if safe not in content.relevant_links:
                        content.relevant_links.append(safe)
                    if ("portfolio" in safe.lower() or "personal" in safe.lower() or "blog" in safe.lower()) and first_portfolio is None:
                        first_portfolio = safe
                    elif "github.com" in safe.lower() and first_github is None:
                        first_github = safe

            chosen_site = first_portfolio or first_github
            if chosen_site and not content.github_or_portfolio:
                content.github_or_portfolio = chosen_site
    elif bname == "positions.csv":
        for r in _read_csv_dict_rows(text, ["company name", "title"]):
            st, fin, d = r.get("started on", ""), r.get("finished on", ""), r.get("description", "")
            ic = not fin or "present" in fin.lower()
            _route_experience_item(ResumeExperienceItem(
                company=sanitize_external_text(r.get("company name", "")),
                role_title=sanitize_external_text(r.get("title", "")),
                start_date=st or None, end_date=fin or ("Present" if ic and st else None),
                is_current=ic, highlights=[sanitize_external_text(d)] if d else [],
            ), content.experience, content.internships)
    elif bname == "education.csv":
        for r in _read_csv_dict_rows(text, ["school name", "degree name"]):
            deg, field = r.get("degree name", ""), None
            if deg and "," in deg:
                deg, _, field = deg.partition(",")
            st_date = (r.get("start date", "") or "")[:2000]
            end_date = (r.get("end date", "") or "")[:2000]
            ym_s, ym_e = _YEAR_RANGE_RE.search(st_date), _YEAR_RANGE_RE.search(end_date)
            content.education.append(ResumeEducationItem(
                institution=sanitize_external_text(r.get("school name", "")), degree=sanitize_external_text(deg.strip()),
                field_of_study=sanitize_external_text(field.strip()) if field else None,
                start_year=int(ym_s.group(1)) if ym_s else None, end_year=int(ym_e.group(1)) if ym_e else None,
            ))
    elif bname in {"skills.csv", "certifications.csv", "honors.csv", "publications.csv"}:
        simple_maps = {
            "skills.csv": (["name", "skill"], content.skills, lambda r: r.get("name", "") or r.get("skill", "")),
            "certifications.csv": (["name", "authority", "url"], content.certifications, lambda r: r.get("name", "")),
            "honors.csv": (["title", "description"], content.awards, lambda r: f"{r.get('title', '')}: {r.get('description', '')}" if r.get('description') else r.get('title', '')),
            "publications.csv": (["name", "url"], content.publications, lambda r: r.get("name", "")),
        }
        cols, dest, extractor = simple_maps[bname]
        for r in _read_csv_dict_rows(text, cols):
            val = sanitize_external_text(extractor(r))
            if val and val not in dest and (bname != "skills.csv" or len(dest) < _MAX_SKILLS):
                dest.append(val)
            url = safe_http_url(r.get("url", ""))
            if url and url not in content.relevant_links:
                content.relevant_links.append(url)
    elif bname == "projects.csv":
        for r in _read_csv_dict_rows(text, ["title", "description"]):
            if r.get("title", ""):
                content.projects.append(ResumeProjectItem(
                    title=sanitize_external_text(r.get("title", "")),
                    description=sanitize_external_text(r.get("description", "")),
                    project_url=safe_http_url(r.get("url", "")),
                ))
    elif bname == "volunteering.csv":
        for r in _read_csv_dict_rows(text, ["company name", "role", "cause"]):
            c, ro, ca = r.get("company name", ""), r.get("role", ""), r.get("cause", "")
            entry = f"{ro} at {c}" if c and ro else (ro or c)
            if ca:
                entry += f" ({ca})"
            if entry and entry not in content.leadership_and_volunteering:
                content.leadership_and_volunteering.append(sanitize_external_text(entry))
    elif bname == "email addresses.csv":
        p_em, c_em, a_em = "", "", ""
        for r in _read_csv_dict_rows(text, ["email address", "confirmed", "primary"]):
            addr = r.get("email address", "")
            if addr:
                if r.get("primary", "").lower() in ("yes", "true", "1") and not p_em:
                    p_em = addr
                elif r.get("confirmed", "").lower() in ("yes", "true", "1") and not c_em:
                    c_em = addr
                elif not a_em:
                    a_em = addr
        best = p_em or c_em or a_em
        if best and not content.email:
            content.email = best
    elif bname == "phonenumbers.csv":
        for r in _read_csv_dict_rows(text, ["number"]):
            if r.get("number", "") and not content.phone:
                content.phone = r.get("number", "")
                break


def parse_linkedin_archive_zip(data: bytes) -> Tuple[ResumeContent, List[str]]:
    """Safely opens and parses an official LinkedIn data download ZIP file."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        raise ValueError(f"Malformed or corrupted ZIP archive: {e}")
    if len(zf.infolist()) > _MAX_ARCHIVE_ENTRIES:
        raise ValueError("Archive contains more than 500 entries.")
    content, total_bytes = ResumeContent(evidence_classifications={"source": ExternalProfileSource.LINKEDIN_DATA_EXPORT.value}), 0
    for info in zf.infolist():
        fname, bname = info.filename, Path(info.filename).name.lower()
        if ".." in fname or fname.startswith(("/", "\\")) or ":" in fname or bname not in _ALLOWED_ARCHIVE_BASENAMES:
            continue
        if info.file_size > _MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise ValueError(f"Archive entry '{bname}' exceeds 5 MB uncompressed limit.")
        total_bytes += info.file_size
        if total_bytes > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("Archive total uncompressed size exceeds 20 MB.")
        try:
            _populate_content_from_csv(bname, zf.read(info).decode("utf-8-sig", errors="replace"), content)
        except Exception as read_err:
            logger.warning("Error reading archive member %s: %s", fname, read_err)
    summary_note = _build_import_summary(content)
    content.evidence_notes["import_summary"] = summary_note
    return content, ["Parsed LinkedIn data archive export.", summary_note]


def _detect_csv_type(header_line: str) -> Optional[str]:
    header_line = header_line[:2000]
    h = header_line.lower().replace('"', '').replace("'", "")
    for kw, fname in (
        ("company name", "positions.csv"), ("school name", "education.csv"),
        ("geo location", "profile.csv"), ("headline", "profile.csv"), ("first name", "profile.csv"),
        ("email address", "email addresses.csv"), ("extension", "phonenumbers.csv"),
        ("authority", "certifications.csv"), ("cause", "volunteering.csv"),
        ("publication", "publications.csv"), ("honor", "honors.csv"), ("project", "projects.csv"),
    ):
        if kw in h:
            return fname
    tokens = [t.strip() for t in h.split(",")]
    if len(tokens) <= 2 and any(t in ("name", "skill", "skills") for t in tokens):
        return "skills.csv"
    return None


def _parse_linkedin_export_csv(raw_content: str) -> ResumeContent:
    """Parse a single or multi-part concatenated LinkedIn CSV export."""
    raw_content = raw_content[:200000]
    content = ResumeContent(evidence_classifications={"source": ExternalProfileSource.LINKEDIN_DATA_EXPORT.value})
    lines = raw_content.splitlines()
    header_indices: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        clean = line.strip()
        if clean:
            detected = _detect_csv_type(clean)
            if detected:
                header_indices.append((i, detected))

    if not header_indices:
        rows = [r for r in csv.reader(io.StringIO(raw_content)) if any(c.strip() for c in r)]
        if rows:
            header = [c.strip().lower() for c in rows[0]]
            body = rows[1:]
            if len(header) == 1 and header[0] in {"name", "skill", "skills"}:
                content.skills = [r[0].strip() for r in body if len(r[0].strip()) > 1][:_MAX_SKILLS]
        return content

    for idx, (start_idx, bname) in enumerate(header_indices):
        end_idx = header_indices[idx + 1][0] if idx + 1 < len(header_indices) else len(lines)
        _populate_content_from_csv(bname, "\n".join(lines[start_idx:end_idx]), content)

    return content
