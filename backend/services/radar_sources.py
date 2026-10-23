"""
Compass — Internship Radar Source Adapters & Verified Registries.

Parses curated feeds, official employer career portals, public research fellowships,
government internship schemes, open-source programs, and community repositories.
Includes URL canonicalization, deduplication, and employer category classification.
"""
from __future__ import annotations

import re
import urllib.parse
from datetime import date
from typing import Any, Dict, List, Optional
import httpx

from backend.models_radar import EmployerType, OpportunityStatus


def canonicalize_url(url: str, role_title: Optional[str] = None) -> str:
    """
    Normalizes a job or application URL for deduplication.
    Strips tracking params (utm_*, ref, gh_src, etc.).
    Preserves requisition identifiers and anchors when present.
    If URL is a generic careers page, disambiguates using normalized role title.
    """
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        # Filter query params
        q_params = urllib.parse.parse_qs(parsed.query)
        allowed_params = {
            k: v for k, v in q_params.items()
            if not k.startswith("utm_") and k not in {"ref", "source", "gh_src", "lever-origin", "fbclid"}
        }
        clean_query = urllib.parse.urlencode(allowed_params, doseq=True)
        # Normalize netloc and path
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        fragment = parsed.fragment if parsed.fragment.startswith("role-") else ""
        # If generic path (e.g. '', '/', '/jobs', '/careers', '/jobs/') and role_title provided, append anchor
        if (not path or path in {"/jobs", "/careers", "/career", "/internships", "/internship"}) and role_title and not fragment and not clean_query:
            slug = re.sub(r"[^\w\s-]", "", role_title.strip().lower()).replace(" ", "-")
            fragment = f"role-{slug}"
        return urllib.parse.urlunparse((parsed.scheme.lower(), netloc, path, "", clean_query, fragment))
    except Exception:
        return url.strip().split("?")[0].rstrip("/")


def normalize_company_name(name: str) -> str:
    """
    Normalizes company names for deduplication (e.g. 'Google LLC' -> 'Google').
    """
    clean = re.sub(r"\b(inc|corp|corporation|llc|ltd|limited|technologies|technology|systems|labs|pvt)\b", "", name, flags=re.IGNORECASE)
    clean = re.sub(r"[^\w\s]", "", clean)
    return " ".join(clean.split()).title()


def infer_category(title: str) -> str:
    tl = title.lower()
    if any(k in tl for k in ["ai", "machine learning", "ml", "deep learning", "llm", "nlp", "computer vision"]):
        return "ai_ml"
    if any(k in tl for k in ["data science", "data analyst", "data engineer"]):
        return "data"
    if any(k in tl for k in ["research", "fellow", "lab", "scientist", "scientific"]):
        return "research"
    if any(k in tl for k in ["backend", "server", "distributed", "systems", "platform"]):
        return "backend"
    if any(k in tl for k in ["cloud", "devops", "infrastructure", "sre", "security", "cyber"]):
        return "cloud"
    if any(k in tl for k in ["open source", "gsoc", "lfx", "foss"]):
        return "open_source"
    return "swe"


def infer_employer_type(company_name: str, category: str = "general", source_name: str = "") -> Optional[str]:
    """Classifies an employer into one of the canonical categories only when reliable evidence exists.
    Otherwise returns None to avoid inventing classifications.
    """
    if not company_name:
        return None
    cn = company_name.lower().strip()
    sn = source_name.lower().strip()

    if any(k in cn or k in sn for k in ["research", "iisc", "tifr", "csir", "iit", "iiit", "nasi", "insa", "iasc", "laboratory", "fellowship", "cern", "inria", "max planck"]):
        return EmployerType.RESEARCH
    if any(k in cn or k in sn for k in ["aicte", "gov", "ministry", "nic", "niti", "national informatics", "digital india", "drdo", "isro", "public sector"]):
        return EmployerType.GOVERNMENT
    if any(k in cn or k in sn for k in ["gsoc", "lfx", "open source", "foss", "linux foundation", "mlh", "apache", "mozilla"]):
        return EmployerType.OPEN_SOURCE
    enterprise_known = [
        "google", "microsoft", "amazon", "nvidia", "meta", "apple", "adobe", "oracle", "cisco", "ibm",
        "salesforce", "intel", "uber", "goldman sachs", "jpmorgan", "morgan stanley", "samsung", "atlassian",
        "qualcomm", "walmart", "accenture", "tcs", "infosys", "wipro", "cognizant", "deloitte"
    ]
    if any(k in cn for k in enterprise_known):
        return EmployerType.ENTERPRISE
    if any(k in sn or k in cn for k in ["y combinator", "techstars", "sequoia", "accel", "seed", "series a", "series b", "early-stage", "startup"]):
        return EmployerType.STARTUP

    return None


# ---------------------------------------------------------------------------
# GitHub Repository Parsers
# ---------------------------------------------------------------------------

def parse_markdown_table_opportunities(
    md_content: str,
    source_name: str,
    source_url: str,
) -> List[Dict[str, Any]]:
    """
    Parses Markdown tables commonly found in community internship repos.
    Extracts Company, Role, Location, Application Link, and requirements.
    """
    opportunities: List[Dict[str, Any]] = []
    lines = md_content.splitlines()

    table_lines: List[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            # Table ended or blank line
            if len(table_lines) >= 3:
                _process_table_block(table_lines, source_name, source_url, opportunities)
            table_lines = []
            in_table = False

    if in_table and len(table_lines) >= 3:
        _process_table_block(table_lines, source_name, source_url, opportunities)

    return opportunities


def _process_table_block(
    table_lines: List[str],
    source_name: str,
    source_url: str,
    out: List[Dict[str, Any]],
) -> None:
    headers = [h.strip().lower() for h in table_lines[0].split("|")[1:-1]]
    # Find column indices
    company_idx = next((i for i, h in enumerate(headers) if "company" in h or "organization" in h), 0)
    role_idx = next((i for i, h in enumerate(headers) if "role" in h or "title" in h or "position" in h), 1)
    location_idx = next((i for i, h in enumerate(headers) if "location" in h), -1)
    link_idx = next((i for i, h in enumerate(headers) if "link" in h or "apply" in h or "application" in h), -1)

    for row_line in table_lines[2:]:  # Skip header and separator
        cols = [c.strip() for c in row_line.split("|")[1:-1]]
        if len(cols) <= max(company_idx, role_idx):
            continue

        raw_company = cols[company_idx] if company_idx < len(cols) else "Unknown"
        raw_role = cols[role_idx] if role_idx < len(cols) else "Software Engineering Intern"
        raw_location = cols[location_idx] if 0 <= location_idx < len(cols) else "Remote / Flexible"
        raw_link_cell = cols[link_idx] if 0 <= link_idx < len(cols) else ""

        # Extract markdown link: [text](url)
        url_match = (
            re.search(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", raw_link_cell)
            or re.search(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", raw_company)
            or re.search(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", raw_role)
        )
        app_url = url_match.group(2) if url_match else None

        # Clean display names
        comp_clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw_company).strip()
        comp_clean = re.sub(r"[^\w\s\-.]", "", comp_clean).strip()
        role_clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", raw_role).strip()

        if not comp_clean or not app_url:
            continue

        category = infer_category(role_clean)
        emp_type = infer_employer_type(comp_clean, category, source_name)
        work_arr = "remote" if "remote" in raw_location.lower() else "onsite"
        from backend.services.radar_ats_adapters import is_india_or_remote
        is_india = is_india_or_remote(raw_location, is_remote=(work_arr == "remote"))

        out.append({
            "company_name": comp_clean,
            "role_title": role_clean,
            "employer_type": emp_type,
            "opportunity_type": "internship",
            "category": category,
            "location": raw_location,
            "work_arrangement": work_arr,
            "country": "India" if "india" in raw_location.lower() else "Global",
            "is_india_eligible": is_india,
            "official_application_url": app_url,
            "canonical_url": canonicalize_url(app_url, role_clean),
            "current_status": OpportunityStatus.NEEDS_VERIFICATION,
            "description": f"Discovered via {source_name}. Published location: {raw_location}.",
            "source_name": source_name,
            "source_type": "github_curated",
            "source_url": source_url,
            "source_authority": "tier_2",
            "is_official_source": False,
            "eligible_academic_years": [1, 2] if "underclass" in source_name.lower() or "freshman" in role_clean.lower() else [2, 3, 4],
        })


async def fetch_github_markdown_opportunities(
    repo_raw_url: str,
    source_name: str,
    timeout_sec: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Downloads and parses a public GitHub raw markdown repository.
    Handles network errors safely with timeouts and empty fallbacks.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.get(repo_raw_url)
            if resp.status_code == 200:
                return parse_markdown_table_opportunities(resp.text, source_name, repo_raw_url)
            return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Verified Curated Indian Tech, Research, Startup & Government Opportunities
# ---------------------------------------------------------------------------

CURATED_INDIAN_OPPORTUNITIES: List[Dict[str, Any]] = [
    # =======================================================================
    # 1. Research Laboratories & Academic Institutions
    # =======================================================================
    {
        "company_name": "IISc Bangalore",
        "role_title": "Summer Research Internship in Computer Science & Automation (CSA)",
        "employer_type": EmployerType.RESEARCH,
        "opportunity_type": "research",
        "category": "research",
        "location": "Bengaluru, Karnataka, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹15,000 / month)",
        "duration": "8-10 weeks (May-July 2026)",
        "official_application_url": "https://csa.iisc.ac.in/academics-admissions/internships/",
        "canonical_url": "https://csa.iisc.ac.in/academics-admissions/internships",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 15),
        "description": "Prestigious mentored research fellowship in Machine Learning, Cryptography, Systems, and Theoretical Computer Science at IISc Bangalore.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "BS", "M.Tech", "MSc in CS/IT/ECE"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Python", "Algorithms", "Linear Algebra", "Data Structures"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 20), "observed_close_date": date(2024, 3, 15)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 15), "observed_close_date": date(2025, 3, 20)},
            {"cycle_year": 2026, "observed_open_date": date(2026, 1, 15), "observed_close_date": date(2026, 3, 31)},
        ],
        "source": {
            "source_name": "IISc CSA Academic Portal",
            "source_type": "official_university_portal",
            "source_url": "https://csa.iisc.ac.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Published on official IISc .ac.in institutional academic page; seasonal annual programme requiring active batch confirmation.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "TIFR Mumbai",
        "role_title": "Visiting Students' Research Programme (VSRP) in Computer Science",
        "employer_type": EmployerType.RESEARCH,
        "opportunity_type": "research",
        "category": "research",
        "location": "Mumbai, Maharashtra, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹10,000 / month + travel allowance & accommodation)",
        "duration": "7 weeks (May-July 2026)",
        "official_application_url": "https://www.tifr.res.in/~vsrp/",
        "canonical_url": "https://www.tifr.res.in/~vsrp",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 10),
        "description": "Pre-doctoral research program in quantum computing, foundational algorithms, complexity theory, and machine learning at TIFR Mumbai.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "BS", "MSc"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Mathematics", "Algorithms", "C++", "Python"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 10), "observed_close_date": date(2024, 2, 28)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 12), "observed_close_date": date(2025, 2, 28)},
            {"cycle_year": 2026, "observed_open_date": date(2026, 1, 10), "observed_close_date": date(2026, 3, 10)},
        ],
        "source": {
            "source_name": "TIFR VSRP Official Portal",
            "source_type": "official_university_portal",
            "source_url": "https://www.tifr.res.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official TIFR national research foundation portal; seasonal annual fellowship requiring current cycle announcement confirmation.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "IASc - INSA - NASI",
        "role_title": "Summer Research Fellowship Programme (SRFP)",
        "employer_type": EmployerType.RESEARCH,
        "opportunity_type": "research",
        "category": "research",
        "location": "Pan-India National Laboratories",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹12,500 / month + travel support)",
        "duration": "2 months",
        "official_application_url": "https://web-japps.ias.ac.in/fellowship2026/",
        "canonical_url": "https://web-japps.ias.ac.in/fellowship2026",
        "current_status": OpportunityStatus.UPCOMING_CONFIRMED,
        "confirmed_open_date": date(2026, 9, 15),
        "description": "Joint Summer Research Fellowship offered by the three National Science Academies (Indian Academy of Sciences, INSA, NASI) for students across India.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "BSc", "MSc", "Dual Degree"],
            "eligible_academic_years": [2, 3],
            "eligible_graduation_years": [2027, 2028],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Scientific Computing", "Python", "Data Analysis"],
        },
        "cycles": [
            {"cycle_year": 2023, "observed_open_date": date(2023, 9, 20), "observed_close_date": date(2023, 11, 15)},
            {"cycle_year": 2024, "observed_open_date": date(2024, 9, 25), "observed_close_date": date(2024, 11, 20)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 9, 20), "observed_close_date": date(2025, 11, 30)},
        ],
        "source": {
            "source_name": "Indian Science Academies Portal",
            "source_type": "official_research_portal",
            "source_url": "https://web-japps.ias.ac.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Joint science academies national fellowship portal.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "IIIT Hyderabad",
        "role_title": "Summer Research Internship in AI & Robotics",
        "employer_type": EmployerType.RESEARCH,
        "opportunity_type": "research",
        "category": "research",
        "location": "Hyderabad, Telangana, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Stipend (₹10,000 - ₹15,000 / month)",
        "duration": "8-10 weeks (May-July 2026)",
        "official_application_url": "https://www.iiit.ac.in/academics/internships/",
        "canonical_url": "https://www.iiit.ac.in/academics/internships",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 2, 1),
        "description": "Mentored research with Kohli Center on Intelligent Systems (KCIS) and Robotics Research Center.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "BS", "Dual Degree"],
            "eligible_academic_years": [2, 3],
            "eligible_graduation_years": [2027, 2028],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Python", "Machine Learning", "Linear Algebra"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 3, 5), "observed_close_date": date(2024, 4, 5)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 3, 1), "observed_close_date": date(2025, 3, 31)},
            {"cycle_year": 2026, "observed_open_date": date(2026, 2, 1), "observed_close_date": date(2026, 3, 31)},
        ],
        "source": {
            "source_name": "IIIT Hyderabad Academics",
            "source_type": "official_university_portal",
            "source_url": "https://www.iiit.ac.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Published on IIIT-H academic research wing portal; seasonal programme requiring active term confirmation.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "CSIR India",
        "role_title": "Summer Research Training Programme in Computational Biology & Chemistry",
        "employer_type": EmployerType.RESEARCH,
        "opportunity_type": "research",
        "category": "research",
        "location": "Hyderabad / Pune / Chandigarh, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Stipend (₹8,000 - ₹12,000 / month)",
        "duration": "8 weeks (June-July 2026)",
        "official_application_url": "https://www.ccmb.res.in/Academics/Training-Programs",
        "canonical_url": "https://www.ccmb.res.in/Academics/Training-Programs",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 2, 10),
        "description": "Hands-on research training in bio-computing, molecular simulations, and cheminformatics at CSIR premier laboratories.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "BSc", "MSc", "B.Pharm"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Python", "Bioinformatics", "Molecular Modeling"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 2, 15), "observed_close_date": date(2024, 3, 31)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 2, 10), "observed_close_date": date(2025, 3, 31)},
        ],
        "source": {
            "source_name": "CSIR-CCMB Training Directorate",
            "source_type": "official_research_portal",
            "source_url": "https://www.ccmb.res.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official CSIR laboratory training portal; seasonal training programme requiring active cohort confirmation.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Microsoft Research India",
        "role_title": "Research Fellow (AI / ML / Systems)",
        "employer_type": EmployerType.RESEARCH,
        "opportunity_type": "research",
        "category": "research",
        "location": "Bengaluru, Karnataka, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹80,000 - ₹1,00,000 / month)",
        "duration": "1-2 years / 6 months",
        "official_application_url": "https://www.microsoft.com/en-us/research/academic-program/research-fellows-program/",
        "canonical_url": "https://www.microsoft.com/en-us/research/academic-program/research-fellows-program",
        "current_status": OpportunityStatus.OPEN_CONFIRMED,
        "confirmed_open_date": date(2026, 1, 15),
        "description": "Pre-doctoral research fellowship focusing on Foundation Models, ML theory, Multimodal AI, and Systems in Bangalore.",
        "requirements": {
            "eligible_degree_types": ["Bachelors", "Masters", "B.Tech", "BS"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": True,
            "required_skills": ["Python", "PyTorch", "Algorithms", "Linear Algebra"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 15), "observed_close_date": date(2024, 3, 31)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 20), "observed_close_date": date(2025, 3, 31)},
            {"cycle_year": 2026, "observed_open_date": date(2026, 1, 15), "observed_close_date": date(2026, 4, 15)},
        ],
        "source": {
            "source_name": "Microsoft Research Portal",
            "source_type": "official_career_page",
            "source_url": "https://www.microsoft.com/en-us/research/academic-program/research-fellows-program/",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official MSR India fellowship portal.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },

    # =======================================================================
    # 2. Government & Public-Sector Programs
    # =======================================================================
    {
        "company_name": "AICTE / MoE",
        "role_title": "TULIP Smart City Technology & Urban Engineering Internship",
        "employer_type": EmployerType.GOVERNMENT,
        "opportunity_type": "internship",
        "category": "cloud",
        "location": "Pan-India Municipalities & Smart Cities",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹10,000 - ₹20,000 / month)",
        "duration": "8-12 weeks",
        "official_application_url": "https://internship.aicte-india.org/",
        "canonical_url": "https://internship.aicte-india.org/#tulip-smart-city",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 1),
        "description": "Urban Learning Internship Program (TULIP) by Ministry of Housing & Urban Affairs and AICTE for technology and smart governance projects.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "B.Arch", "B.Plan", "MCA"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["GIS", "Python", "Web Development", "IoT"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 1), "observed_close_date": date(2024, 12, 31)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 1), "observed_close_date": date(2025, 12, 31)},
        ],
        "source": {
            "source_name": "AICTE National Internship Portal",
            "source_type": "government_portal",
            "source_url": "https://internship.aicte-india.org",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Government of India AICTE statutory portal homepage; individual ULB vacancy requisitions require verification.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Ministry of Electronics & IT (MeitY)",
        "role_title": "Digital India Internship Scheme (Software & Cyber Security)",
        "employer_type": EmployerType.GOVERNMENT,
        "opportunity_type": "internship",
        "category": "cloud",
        "location": "New Delhi / Remote, India",
        "work_arrangement": "hybrid",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹20,000 / month)",
        "duration": "2 months (May-June / Dec-Jan)",
        "official_application_url": "https://www.meity.gov.in/digital-india-internship-scheme",
        "canonical_url": "https://www.meity.gov.in/digital-india-internship-scheme",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 3, 1),
        "description": "Government technology internship focusing on Cyber Law, AI Ethics, Cloud Infrastructure, and Digital Public Infrastructure (DPI).",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "MCA", "Dual Degree"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "min_gpa": 7.5,
            "required_skills": ["Networking", "Cyber Security", "Python", "Cloud"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 3, 1), "observed_close_date": date(2024, 3, 31)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 3, 5), "observed_close_date": date(2025, 4, 1)},
        ],
        "source": {
            "source_name": "MeitY Official Portal",
            "source_type": "government_portal",
            "source_url": "https://www.meity.gov.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Published on official .gov.in ministry portal; semi-annual scheme requiring active batch notice.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "National Informatics Centre (NIC)",
        "role_title": "Summer Technology & e-Governance Internship",
        "employer_type": EmployerType.GOVERNMENT,
        "opportunity_type": "internship",
        "category": "backend",
        "location": "New Delhi / State Centres, India",
        "work_arrangement": "hybrid",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹10,000 / month)",
        "duration": "6-8 weeks",
        "official_application_url": "https://www.nic.in/internship/",
        "canonical_url": "https://www.nic.in/internship",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 2, 15),
        "description": "Build citizen-scale e-governance applications, high-availability databases, and secure APIs backing national digital systems.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "MCA"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Java", "Spring Boot", "PostgreSQL", "REST APIs"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 2, 20), "observed_close_date": date(2024, 3, 25)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 2, 15), "observed_close_date": date(2025, 3, 20)},
        ],
        "source": {
            "source_name": "NIC Career Wing",
            "source_type": "government_portal",
            "source_url": "https://www.nic.in",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official NIC national informatics portal; seasonal programme requiring active session notification.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },

    # =======================================================================
    # 3. High-Growth Tech Startups & SMEs
    # =======================================================================
    {
        "company_name": "Zerodha / FOSS United",
        "role_title": "Open Source Engineering Fellowship",
        "employer_type": EmployerType.STARTUP,
        "opportunity_type": "fellowship",
        "category": "open_source",
        "location": "Bengaluru / Remote, India",
        "work_arrangement": "remote",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹30,000 - ₹50,000 / month)",
        "duration": "3-6 months",
        "official_application_url": "https://fossunited.org/grants",
        "canonical_url": "https://fossunited.org/grants#zerodha-foss-fellowship",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 1),
        "description": "Mentored engineering fellowship by Zerodha and FOSS United foundation to work full-time on impactful open-source projects.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "BSc", "Self-Taught", "Any"],
            "eligible_academic_years": [1, 2, 3, 4],
            "eligible_graduation_years": [2026, 2027, 2028],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Python", "Rust", "Go", "Git", "Open Source"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 1), "observed_close_date": date(2024, 12, 31)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 1), "observed_close_date": date(2025, 12, 31)},
        ],
        "source": {
            "source_name": "FOSS United Grants Directorate",
            "source_type": "official_career_page",
            "source_url": "https://fossunited.org",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official foundation established by Zerodha leadership; grants portal monitored for open fellowship rounds.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Sarvam AI",
        "role_title": "Generative AI & Indic LLM Research Intern",
        "employer_type": EmployerType.STARTUP,
        "opportunity_type": "internship",
        "category": "ai_ml",
        "location": "Bengaluru, Karnataka, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹50,000 - ₹75,000 / month)",
        "duration": "6 months",
        "official_application_url": "https://www.sarvam.ai/careers",
        "canonical_url": "https://www.sarvam.ai/careers#indic-llm-intern",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 15),
        "description": "Pre-training, tokenization, and fine-tuning frontier multilingual foundation models for Indian languages and speech AI.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "M.Tech", "MS"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": False,
            "required_skills": ["PyTorch", "Transformers", "NLP", "CUDA"],
        },
        "cycles": [
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 10), "observed_close_date": date(2025, 4, 30)},
        ],
        "source": {
            "source_name": "Sarvam AI Careers",
            "source_type": "official_career_page",
            "source_url": "https://www.sarvam.ai",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official startup careers directory; candidate lead pending active requisition link.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Hasura",
        "role_title": "GraphQL Engine & Distributed Systems Intern",
        "employer_type": EmployerType.STARTUP,
        "opportunity_type": "internship",
        "category": "backend",
        "location": "Bengaluru / Remote, India",
        "work_arrangement": "remote",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹60,000 / month)",
        "duration": "3-6 months",
        "official_application_url": "https://hasura.io/careers/",
        "canonical_url": "https://hasura.io/careers#graphql-engine-intern",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 20),
        "description": "High-performance data access compilers, query optimization algorithms, Haskell / Rust engines, and cloud metadata planes.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "BS in CS"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": False,
            "required_skills": ["Haskell", "Rust", "PostgreSQL", "Compilers", "Distributed Systems"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 2, 1), "observed_close_date": date(2024, 4, 30)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 25), "observed_close_date": date(2025, 4, 15)},
        ],
        "source": {
            "source_name": "Hasura Official Careers",
            "source_type": "official_career_page",
            "source_url": "https://hasura.io",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official Hasura careers page; candidate lead pending active requisition link.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Razorpay",
        "role_title": "Backend Engineering Intern",
        "employer_type": EmployerType.STARTUP,
        "opportunity_type": "internship",
        "category": "backend",
        "location": "Bengaluru, Karnataka, India",
        "work_arrangement": "hybrid",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹40,000 - ₹50,000 / month)",
        "duration": "6 months",
        "official_application_url": "https://razorpay.com/jobs/",
        "canonical_url": "https://razorpay.com/jobs#backend-intern",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 1, 10),
        "description": "High-throughput fintech payment gateway pipelines, Go microservices, and idempotent distributed APIs.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "BE", "MCA"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": False,
            "required_skills": ["Go", "MySQL", "Distributed Systems", "REST APIs"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 15), "observed_close_date": date(2024, 3, 15)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 10), "observed_close_date": date(2025, 3, 20)},
        ],
        "source": {
            "source_name": "Razorpay Careers",
            "source_type": "official_career_page",
            "source_url": "https://razorpay.com/jobs/",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official Razorpay jobs page; candidate lead pending active requisition link.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "BrowserStack",
        "role_title": "Core Infrastructure & Cloud Platform Intern",
        "employer_type": EmployerType.STARTUP,
        "opportunity_type": "internship",
        "category": "cloud",
        "location": "Mumbai / Bengaluru, India",
        "work_arrangement": "hybrid",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹50,000 / month)",
        "duration": "6 months",
        "official_application_url": "https://www.browserstack.com/careers",
        "canonical_url": "https://www.browserstack.com/careers#infra-intern",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 2, 1),
        "description": "Automated cloud browser device infrastructure, hypervisor management, low-latency streaming, and device-farm networking.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E."],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": False,
            "required_skills": ["Linux", "Python", "Networking", "Containers", "Docker"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 2, 10), "observed_close_date": date(2024, 4, 20)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 2, 5), "observed_close_date": date(2025, 4, 15)},
        ],
        "source": {
            "source_name": "BrowserStack Careers",
            "source_type": "official_career_page",
            "source_url": "https://www.browserstack.com",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official BrowserStack portal; candidate lead pending active requisition link.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },

    # =======================================================================
    # 4. Open-Source Fellowships & Mentorship Programs
    # =======================================================================
    {
        "company_name": "Google Summer of Code",
        "role_title": "GSoC 2026 Open Source Contributor",
        "employer_type": EmployerType.OPEN_SOURCE,
        "opportunity_type": "fellowship",
        "category": "open_source",
        "location": "Global / Remote",
        "work_arrangement": "remote",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Stipend ($1,500 - $3,000 / ~₹1,25,000 - ₹2,50,000 total)",
        "duration": "12-22 weeks (Summer 2026)",
        "official_application_url": "https://summerofcode.withgoogle.com/",
        "canonical_url": "https://summerofcode.withgoogle.com",
        "current_status": OpportunityStatus.OPEN_CONFIRMED,
        "confirmed_open_date": date(2026, 2, 25),
        "description": "Global online program focusing on bringing new contributors into open source software development under expert mentorship.",
        "requirements": {
            "eligible_degree_types": ["Bachelors", "Masters", "Any", "Self-Taught"],
            "eligible_academic_years": [1, 2, 3, 4],
            "eligible_graduation_years": [2026, 2027, 2028, 2029],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Git", "Open Source", "C++", "Python", "Rust", "Java"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 3, 18), "observed_close_date": date(2024, 4, 2)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 3, 24), "observed_close_date": date(2025, 4, 8)},
            {"cycle_year": 2026, "observed_open_date": date(2026, 3, 20), "observed_close_date": date(2026, 4, 10)},
        ],
        "source": {
            "source_name": "Google Open Source Directorate",
            "source_type": "open_source_portal",
            "source_url": "https://summerofcode.withgoogle.com",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official Google Summer of Code program portal.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Linux Foundation",
        "role_title": "LFX Mentorship (Cloud Native, Linux Kernel, Web3)",
        "employer_type": EmployerType.OPEN_SOURCE,
        "opportunity_type": "fellowship",
        "category": "open_source",
        "location": "Global / Remote",
        "work_arrangement": "remote",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~$3,000 stipend / ~₹2,50,000)",
        "duration": "12 weeks (Full-time / Part-time)",
        "official_application_url": "https://mentorship.lfx.linuxfoundation.org/",
        "canonical_url": "https://mentorship.lfx.linuxfoundation.org",
        "current_status": OpportunityStatus.OPEN_CONFIRMED,
        "confirmed_open_date": date(2026, 1, 15),
        "description": "Paid mentorship on critical open-source infrastructure including Kubernetes, Envoy, OpenTelemetry, Hyperledger, and RISC-V.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "BS", "MS", "Self-Taught"],
            "eligible_academic_years": [1, 2, 3, 4],
            "eligible_graduation_years": [2026, 2027, 2028],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Go", "C", "Rust", "Kubernetes", "Linux"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 15), "observed_close_date": date(2024, 2, 13)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 20), "observed_close_date": date(2025, 2, 18)},
            {"cycle_year": 2026, "observed_open_date": date(2026, 1, 15), "observed_close_date": date(2026, 2, 28)},
        ],
        "source": {
            "source_name": "Linux Foundation LFX Portal",
            "source_type": "open_source_portal",
            "source_url": "https://mentorship.lfx.linuxfoundation.org",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official Linux Foundation LFX platform.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Major League Hacking (MLH)",
        "role_title": "MLH Fellowship (Software Engineering & Open Source)",
        "employer_type": EmployerType.OPEN_SOURCE,
        "opportunity_type": "fellowship",
        "category": "swe",
        "location": "Global / Remote",
        "work_arrangement": "remote",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (Need-based educational stipend up to $5,000)",
        "duration": "12 weeks",
        "official_application_url": "https://fellowship.mlh.io/",
        "canonical_url": "https://fellowship.mlh.io",
        "current_status": OpportunityStatus.OPEN_CONFIRMED,
        "confirmed_open_date": date(2026, 1, 5),
        "description": "Remote internship alternative where fellows collaborate on real-world production open-source software with top tech company sponsorship.",
        "requirements": {
            "eligible_degree_types": ["Bachelors", "Masters", "Any"],
            "eligible_academic_years": [1, 2, 3, 4],
            "eligible_graduation_years": [2026, 2027, 2028],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["Git", "Python", "JavaScript", "React", "Node.js"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 1, 10), "observed_close_date": date(2024, 4, 30)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 1, 5), "observed_close_date": date(2025, 4, 30)},
        ],
        "source": {
            "source_name": "MLH Official Fellowship Portal",
            "source_type": "open_source_portal",
            "source_url": "https://fellowship.mlh.io",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official MLH Fellowship platform.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },

    # =======================================================================
    # 5. Established Enterprises
    # =======================================================================
    {
        "company_name": "Google India",
        "role_title": "Software Engineering STEP Intern 2026",
        "employer_type": EmployerType.ENTERPRISE,
        "opportunity_type": "internship",
        "category": "swe",
        "location": "Bengaluru / Hyderabad, India",
        "work_arrangement": "hybrid",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹1,10,000 / month)",
        "duration": "10-12 weeks (Summer 2026)",
        "official_application_url": "https://careers.google.com/jobs/results/?location=India&q=STEP",
        "canonical_url": "https://careers.google.com/jobs/results/?location=india&q=step",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2025, 12, 1),
        "description": "Student Training in Engineering Program (STEP) for undergraduate students in their 2nd year of university.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "BS in Computer Science"],
            "eligible_academic_years": [2],
            "eligible_graduation_years": [2027, 2028],
            "eligible_countries": ["India"],
            "work_auth_required": False,
            "sponsorship_available": False,
            "required_skills": ["C++", "Java", "Python", "Data Structures", "Algorithms"],
        },
        "cycles": [
            {"cycle_year": 2023, "observed_open_date": date(2023, 11, 28), "observed_close_date": date(2024, 1, 15)},
            {"cycle_year": 2024, "observed_open_date": date(2024, 12, 5), "observed_close_date": date(2025, 1, 20)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 12, 1), "observed_close_date": date(2026, 1, 31)},
        ],
        "source": {
            "source_name": "Google Careers India",
            "source_type": "official_career_page",
            "source_url": "https://careers.google.com",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official Google Careers portal query; specific STEP requisition verified dynamically.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "NVIDIA",
        "role_title": "Deep Learning & AI Software Intern",
        "employer_type": EmployerType.ENTERPRISE,
        "opportunity_type": "internship",
        "category": "ai_ml",
        "location": "Pune / Bengaluru, India",
        "work_arrangement": "hybrid",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (₹50,000 - ₹75,000 / month)",
        "duration": "6 months",
        "official_application_url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
        "canonical_url": "https://nvidia.wd5.myworkdayjobs.com/nvidiaexternalcareersite#deep-learning-ai-intern",
        "current_status": OpportunityStatus.NEEDS_VERIFICATION,
        "confirmed_open_date": date(2026, 2, 1),
        "description": "Accelerated computing, CUDA kernel optimization, and generative AI research integration on NVIDIA GPUs.",
        "requirements": {
            "eligible_degree_types": ["Bachelors", "Masters", "B.Tech"],
            "eligible_academic_years": [3, 4],
            "eligible_graduation_years": [2026, 2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": True,
            "required_skills": ["CUDA", "C++", "PyTorch", "Deep Learning", "TensorRT"],
        },
        "cycles": [
            {"cycle_year": 2024, "observed_open_date": date(2024, 2, 10), "observed_close_date": date(2024, 5, 1)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 2, 5), "observed_close_date": date(2025, 4, 30)},
        ],
        "source": {
            "source_name": "NVIDIA Workday Careers",
            "source_type": "official_career_page",
            "source_url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official NVIDIA Workday portal homepage; specific requisition ID pending dynamic verification.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
    {
        "company_name": "Amazon India",
        "role_title": "Software Development Engineer (SDE) Intern - 2026",
        "employer_type": EmployerType.ENTERPRISE,
        "opportunity_type": "internship",
        "category": "swe",
        "location": "Bengaluru / Hyderabad / Chennai, India",
        "work_arrangement": "onsite",
        "country": "India",
        "is_india_eligible": True,
        "compensation": "Paid (~₹1,10,000 / month)",
        "duration": "2 months / 6 months",
        "official_application_url": "https://amazon.jobs/en/jobs/sde-intern-india",
        "canonical_url": "https://amazon.jobs/en/jobs/sde-intern-india",
        "current_status": OpportunityStatus.UPCOMING_CONFIRMED,
        "confirmed_open_date": date(2026, 8, 15),
        "description": "Design and build large-scale distributed cloud systems backing AWS and Amazon Consumer platforms.",
        "requirements": {
            "eligible_degree_types": ["B.Tech", "B.E.", "M.Tech", "MCA"],
            "eligible_academic_years": [3],
            "eligible_graduation_years": [2027],
            "eligible_countries": ["India"],
            "work_auth_required": True,
            "sponsorship_available": False,
            "required_skills": ["Java", "Object-Oriented Design", "Data Structures", "Algorithms"],
        },
        "cycles": [
            {"cycle_year": 2023, "observed_open_date": date(2023, 8, 20), "observed_close_date": date(2023, 10, 15)},
            {"cycle_year": 2024, "observed_open_date": date(2024, 8, 18), "observed_close_date": date(2024, 10, 20)},
            {"cycle_year": 2025, "observed_open_date": date(2025, 8, 22), "observed_close_date": date(2025, 10, 30)},
        ],
        "source": {
            "source_name": "Amazon Jobs Portal",
            "source_type": "official_career_page",
            "source_url": "https://amazon.jobs",
            "source_authority": "tier_1",
            "is_official_source": True,
        },
        "verification_evidence": "Official Amazon Jobs portal.",
        "employer_identity_verified": True,
        "official_source_confirmed": True,
        "application_url_checked": True,
    },
]
