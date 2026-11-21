"""
Compass - Automatic application preparation (WS-D).

One entry point per user intent, so the Career page needs one click each:

- `prepare_application_for_user`: for one listing, fetch the full job page (description, employer
  apply link, deadline), tailor the resume, write and validate a cover letter, run job analysis,
  and put the apply-by date on the Timeline.
- `prepare_from_link`: the same for a pasted job link, creating the listing when it is new.
- `prepare_top_matches`: the same for the best three listings for the candidate's profile.

Fetched job text is untrusted web content. It is stored as data, passed to the model only inside the
fence in `career_cover_letter`, and the apply link is checked with the SSRF filter before it is kept.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import HTTPException

from backend.memory import radar as radar_memory
from backend.memory.career import (
    create_tailored_resume,
    delete_tailored_resume,
    get_career_application_by_id,
    get_career_application_by_opportunity,
    get_master_resume,
    get_or_create_career_application,
    get_resume_by_id,
    link_resume_if_unlinked,
    log_application_event,
    update_career_application,
    upsert_master_resume,
)
from backend.models_career import (
    CareerApplicationOut,
    CareerApplicationStatus,
    ResumeContent,
    ResumeValidationStatus,
)
from backend.models_radar import OpportunityOut, OpportunityStatus, UserOpportunityProfileIn
from backend.services.career_cover_letter import compose_cover_letter
from backend.services.career_resume import tailor_resume_for_opportunity
from backend.services.career_tailor_changes import attach_changes

logger = logging.getLogger("compass.services.career_flow")

DETAILS_TIMEOUT_SECONDS = 20.0
AUTO_DEADLINE_KEY = "auto_deadline"  # form_answers key: the apply-by date Compass set automatically
DEADLINE_CLEARED_KEY = "deadline_cleared_by_user"  # form_answers key: the user emptied the deadline on purpose
DEFAULT_APPLY_WITHIN_DAYS = 7
MAX_LINK_CHARS = 2000
TOP_MATCH_LIMIT = 3

MasterFactory = Callable[[Optional[UserOpportunityProfileIn]], ResumeContent]

_PRE_REVIEW = {
    CareerApplicationStatus.SAVED, CareerApplicationStatus.DISCOVERED, CareerApplicationStatus.ELIGIBILITY_CHECKED,
    CareerApplicationStatus.PREPARING, CareerApplicationStatus.ELIGIBILITY_REVIEW, CareerApplicationStatus.NEEDS_INFORMATION,
    CareerApplicationStatus.RESUME_DRAFT, CareerApplicationStatus.RESUME_VALIDATION_FAILED,
}
_TRACKING_PARAMS = ("utm_", "gh_src", "gclid", "fbclid", "ref", "source", "src")
_ROLE_WORDS = re.compile(
    r"\b(intern|internship|engineer|developer|analyst|scientist|designer|researcher|research|associate|trainee|apprentice|manager|specialist|fellow)\b",
    re.IGNORECASE,
)
_GENERIC_HOST_LABELS = {"www", "careers", "career", "jobs", "job", "apply", "boards", "job-boards", "recruiting", "hire", "work"}
_ATS_PATH_COMPANY_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "jobvite.com")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def apply_by_date(close_date: Optional[date], today: Optional[date] = None) -> Tuple[date, str]:
    """(date, kind) for the Timeline task: the listing's own close date if it is still ahead, else today + 7 days."""
    today = today or date.today()
    if close_date and close_date >= today:
        return close_date, "listing"
    return today + timedelta(days=DEFAULT_APPLY_WITHIN_DAYS), "default"


def normalize_job_url(raw: str) -> str:
    """http(s) URL without fragment and tracking parameters. Raises ValueError for anything else."""
    url = (raw or "").strip()
    if not url or len(url) > MAX_LINK_CHARS:
        raise ValueError("Paste a full job link that starts with https://")
    if "://" not in url:
        # "javascript:...", "data:...", "mailto:..." are not links to a job page ("host:8080/path" is fine).
        if re.match(r"(?i)^[a-z][a-z0-9+.\-]*:(?!\d)", url):
            raise ValueError("Paste a full job link that starts with https://")
        url = "https://" + url
    parsed = urlparse(url)
    try:
        has_port_problem = parsed.port is not None and not (0 < parsed.port < 65536)
    except ValueError:
        has_port_problem = True
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or has_port_problem:
        raise ValueError("Paste a full job link that starts with https://")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False) if not k.lower().startswith(_TRACKING_PARAMS)]
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/") or "/", "", urlencode(query), ""))


def company_from_url(url: str) -> str:
    """Best-effort employer name from a job link; ATS hosts use the company slug in the path or subdomain."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    segments = [s for s in parsed.path.split("/") if s]
    slug = ""
    if any(host.endswith(h) for h in _ATS_PATH_COMPANY_HOSTS) and segments:
        slug = segments[0]
    elif any(host == h or host.endswith("." + h) for h in ("myworkdayjobs.com", "breezy.hr")):
        slug = host.split(".")[0]
    else:
        labels = [p for p in host.split(".") if p and p not in _GENERIC_HOST_LABELS]
        slug = labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")
    slug = re.sub(r"[-_]+", " ", slug).strip()
    return slug.title() if slug else "Company"


def infer_listing_identity(text: str, url: str) -> Tuple[str, str]:
    """(company, role) for a pasted job link, from the page text and the link. Never raises."""
    lines = [re.sub(r"^#+\s*", "", ln).strip() for ln in (text or "").splitlines() if ln.strip()]
    company = company_from_url(url)
    role = ""
    for ln in lines[:12]:
        m = re.match(r"(?i)^job application for (.+?) at (.+)$", ln)
        if m:
            return m.group(2).strip()[:120], m.group(1).strip()[:160]
    candidates = [ln for ln in lines[:12] if 3 <= len(ln) <= 140 and len(ln.split()) <= 16 and not ln.endswith(".")]
    for ln in candidates:
        if _ROLE_WORDS.search(ln):
            role = ln
            break
    role = role or (candidates[0] if candidates else "Role from a pasted link")
    m = re.match(r"^(.*?)\s+(?:at|@)\s+(.+)$", role)
    if m and len(m.group(2)) <= 60:
        role, company = m.group(1).strip(), m.group(2).strip()
    else:
        m = re.match(r"^(.*?)\s+[|\u2013\u2014-]\s+(.+)$", role)
        if m and len(m.group(2)) <= 60:
            role = m.group(1).strip()
            if not _ROLE_WORDS.search(m.group(2)):
                company = m.group(2).strip()
    return company[:120], role[:160]


def resume_status_for(app_status: CareerApplicationStatus, val_status: ResumeValidationStatus) -> Optional[str]:
    """Status to set when a resume is attached to an application that is still before review."""
    if app_status not in _PRE_REVIEW:
        return None
    if val_status == ResumeValidationStatus.READY_FOR_REVIEW:
        return CareerApplicationStatus.READY_FOR_REVIEW.value
    return CareerApplicationStatus.RESUME_VALIDATION_FAILED.value


def missing_profile_fields(content: ResumeContent) -> List[str]:
    missing: List[str] = []
    if not (content.full_name or "").strip():
        missing.append("Full name")
    if not content.email:
        missing.append("Email address")
    if not content.phone:
        missing.append("Phone number")
    if not content.education:
        missing.append("Education history")
    return missing


# ---------------------------------------------------------------------------
# Timeline task
# ---------------------------------------------------------------------------

async def create_deadline_task(user_id: str, opp: OpportunityOut, due: date, kind: str) -> Optional[str]:
    """Create the "Apply" task through the existing task service. Returns the task id or None (best effort)."""
    try:
        from backend.memory.db import get_pool
        from backend.models import CreateTaskRequest
        from backend.services.task_service import handle_create_task

        pool = await get_pool()
        if not pool:
            return None
        note = (
            f"Apply by the listing's closing date. {opp.official_application_url or opp.canonical_url or ''}".strip()
            if kind == "listing"
            else f"The listing shows no closing date, so apply within {DEFAULT_APPLY_WITHIN_DAYS} days. {opp.official_application_url or opp.canonical_url or ''}".strip()
        )
        req = CreateTaskRequest(
            title=f"Apply: {opp.role_title} at {opp.company_name}"[:300],
            domain="general",
            due_date=due.isoformat(),
            priority="high" if (due - date.today()).days <= 3 else "medium",
            notes=note,
            duration_minutes=60,
        )
        async with pool.acquire() as conn:
            task = await handle_create_task(conn, req, user_id)
        return str(task.id)
    except HTTPException as err:
        if err.status_code != 409:  # 409 = this exact task already exists, which is the goal
            logger.info("Apply task not created (%s)", err.status_code)
        return None
    except Exception as err:
        logger.info("Apply task not created (%s)", type(err).__name__)
        return None


# ---------------------------------------------------------------------------
# Prepare one listing
# ---------------------------------------------------------------------------

def _live_fetch_allowed() -> bool:
    """False in the test environment, so the existing suite never reaches out to job sites."""
    from backend.config import get_settings

    return str(getattr(get_settings(), "ENVIRONMENT", "")) != "test"


async def _load_listing_details(opp: OpportunityOut) -> Dict[str, Any]:
    """Fetch and store the full listing text, apply link and deadline. Best effort, never raises."""
    if not _live_fetch_allowed():
        return {"fetched": False, "reason": "Live fetching is off in this environment."}
    try:
        from backend.services.radar_jd import fetch_and_store_listing_details

        return await asyncio.wait_for(
            fetch_and_store_listing_details(opp.id, opportunity=opp), timeout=DETAILS_TIMEOUT_SECONDS
        )
    except Exception as err:
        logger.info("Listing details not loaded (%s)", type(err).__name__)
        return {"fetched": False, "reason": "Could not read the job page right now."}


async def _get_or_create_master(user_id: str, master_factory: MasterFactory):
    master = await get_master_resume(user_id)
    if master:
        return master
    profile = await radar_memory.get_user_opportunity_profile(user_id) or UserOpportunityProfileIn()
    return await upsert_master_resume(user_id, master_factory(profile), "Master Resume")


async def _refresh_failed_resume(
    app: CareerApplicationOut, master: ResumeContent, opp: OpportunityOut, user_id: str
) -> CareerApplicationOut:
    """Re-tailor an application stuck in RESUME_VALIDATION_FAILED once the master has a name and an email.

    The earlier copy is kept (the candidate may have edited it); the application points at the new one.
    """
    if not (master.full_name or "").strip() or "@" not in (master.email or ""):
        return app
    tailored_content, report, val_status = tailor_resume_for_opportunity(master, opp)
    if val_status != ResumeValidationStatus.READY_FOR_REVIEW:
        return app
    attach_changes(report, master, tailored_content, opp)
    tailored = await create_tailored_resume(
        user_id=user_id,
        opportunity_id=opp.id,
        title=f"{opp.company_name} Tailored Resume",
        content=tailored_content,
        validation_report=report,
        validation_status=val_status,
    )
    updated = await update_career_application(
        app.id, user_id, {"resume_id": tailored.id, "status": CareerApplicationStatus.READY_FOR_REVIEW.value}
    )
    if not updated:
        await delete_tailored_resume(tailored.id, user_id)
        return app
    updated.resume = tailored
    return updated


async def prepare_application_for_user(
    user_id: str, opportunity_id: int, master_factory: MasterFactory
) -> CareerApplicationOut:
    """Prepare (or reopen) the application for one listing. Safe to call repeatedly."""
    opp = await radar_memory.get_opportunity_by_id(opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    details = await _load_listing_details(opp)
    if details.get("fetched"):
        opp = await radar_memory.get_opportunity_by_id(opportunity_id, user_id) or opp

    app = await get_or_create_career_application(user_id, opportunity_id)
    master = await _get_or_create_master(user_id, master_factory)

    if not app.resume_id:
        tailored_content, report, val_status = tailor_resume_for_opportunity(master.content, opp)
        attach_changes(report, master.content, tailored_content, opp)
        tailored = await create_tailored_resume(
            user_id=user_id,
            opportunity_id=opp.id,
            title=f"{opp.company_name} Tailored Resume",
            content=tailored_content,
            validation_report=report,
            validation_status=val_status,
        )
        # Conditional link (resume_id IS NULL): a concurrent prepare that lost the race discards its own copy.
        linked = await link_resume_if_unlinked(app.id, user_id, tailored.id, resume_status_for(app.status, val_status))
        if linked is None:
            await delete_tailored_resume(tailored.id, user_id)
            app = await get_career_application_by_id(app.id, user_id)
            if not app:
                raise HTTPException(status_code=404, detail="Application not found")
        else:
            app = linked
            app.resume = tailored
    elif app.status == CareerApplicationStatus.RESUME_VALIDATION_FAILED:
        # The resume check failed earlier. If the candidate has since added the missing details, redo the copy.
        app = await _refresh_failed_resume(app, master.content, opp, user_id)

    letter_source = None
    if not app.cover_letter:
        letter = await compose_cover_letter(master.content, opp)
        letter_source = letter["source"]
        app = await update_career_application(app.id, user_id, {"cover_letter": letter["content"]}) or app

    # A deadline the user cleared on purpose stays cleared: no automatic date and no Timeline task.
    if app.target_deadline is None and not (app.form_answers or {}).get(DEADLINE_CLEARED_KEY):
        due, kind = apply_by_date(opp.confirmed_close_date)
        # Remember that Compass chose this date, so "Mark as applied" can replace it with the follow-up
        # reminder while still keeping a deadline the user set themselves.
        answers = dict(app.form_answers or {})
        answers[AUTO_DEADLINE_KEY] = due.isoformat()
        updated = await update_career_application(app.id, user_id, {"target_deadline": due, "form_answers": answers})
        app = updated or app
        await create_deadline_task(user_id, opp, due, kind)

    match_summary: Dict[str, Any] = {}
    try:
        from backend.services.career_job_match import analyze_job_and_match

        report = analyze_job_and_match(opportunity=opp, master=master.content, custom_description=None)
        match_summary = {"score": report.match_score, "missing": report.missing_skills[:5]}
    except Exception as err:  # analysis is shown on its own tab; a failure here must not block preparing
        logger.info("Job analysis skipped (%s)", type(err).__name__)

    app.opportunity = opp
    if app.resume_id and not app.resume:
        app.resume = await get_resume_by_id(app.resume_id, user_id)
    app.missing_fields = missing_profile_fields(app.resume.content if app.resume else master.content)
    await log_application_event(
        app.id,
        "prepared",
        {"opportunity_id": opp.id, "details": details.get("method"), "letter": letter_source, "match": match_summary},
    )
    return app


# ---------------------------------------------------------------------------
# Pasted job link
# ---------------------------------------------------------------------------

async def find_opportunity_id_by_url(url: str) -> Optional[int]:
    """Existing listing whose link equals `url`, or None."""
    pool = await radar_memory.get_pool()
    if not pool:
        for opp_id, row in radar_memory._in_memory_opportunities.items():
            if url in (row.get("canonical_url"), row.get("official_application_url")):
                return opp_id
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM opportunities WHERE canonical_url = $1 OR official_application_url = $1 LIMIT 1", url
        )
    return int(row["id"]) if row else None


async def prepare_from_link(user_id: str, raw_url: str, master_factory: MasterFactory) -> CareerApplicationOut:
    """Find or create the listing for a pasted job link, then run the whole prepare flow."""
    from backend.services.radar_jd import (
        MAX_DESCRIPTION_CHARS,
        MIN_READABLE_CHARS,
        _fetch_page_text,
        extract_apply_url,
        sanitize,
    )
    from backend.services.radar_deadline import parse_application_deadline
    from backend.services.security import is_safe_url

    try:
        url = normalize_job_url(raw_url)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    safe, _reason = await asyncio.to_thread(is_safe_url, url)
    if not safe:
        raise HTTPException(status_code=422, detail="That link can't be opened from here. Check it and try again.")

    opp_id = await find_opportunity_id_by_url(url)
    if opp_id is None:
        page = await _fetch_page_text(url)
        text = sanitize(page.get("text", ""))
        if len(text) < MIN_READABLE_CHARS:
            raise HTTPException(
                status_code=422,
                detail="We couldn't read that page. It may need a login. Open the job in the Radar list instead, or try the company's own careers link.",
            )
        company, role = infer_listing_identity(text, url)
        description = text[:MAX_DESCRIPTION_CHARS]
        apply_url = extract_apply_url(page.get("raw", "") or text, url)
        if apply_url:
            ok, _ = await asyncio.to_thread(is_safe_url, apply_url)
            apply_url = apply_url if ok else None
        profile = await radar_memory.get_user_opportunity_profile(user_id)
        opp_id = await radar_memory.upsert_opportunity(
            company_name=company,
            role_title=role,
            canonical_url=url,
            official_application_url=apply_url or url,
            current_status=OpportunityStatus.NEEDS_VERIFICATION,
            opportunity_type="internship",
            category="general",
            country=(profile.country_of_study if profile and profile.country_of_study else "India"),
            # Added by one user's link: kept out of everyone else's India-filtered lists.
            is_india_eligible=False,
            confirmed_close_date=parse_application_deadline(description),
            description=description,
        )
        await radar_memory.upsert_user_saved_opportunity(user_id, opp_id, is_saved=True)
    app = await prepare_application_for_user(user_id, opp_id, master_factory)
    await log_application_event(app.id, "prepared_from_link", {"host": urlparse(url).hostname or ""})
    return app


# ---------------------------------------------------------------------------
# Top matches
# ---------------------------------------------------------------------------

async def prepare_top_matches(user_id: str, master_factory: MasterFactory, limit: int = TOP_MATCH_LIMIT) -> Dict[str, Any]:
    """Prepare the best `limit` listings for the candidate. Uses the same result shape as auto-prepare."""
    from backend.models_radar import EligibilityClassification
    from backend.routers.radar import recommended_for_user
    from backend.services.career_auto_prepare import check_and_record_auto_prepare_quota

    master = await get_master_resume(user_id)
    c = master.content if master else None
    if not c or not (c.full_name or "").strip() or "@" not in (c.email or "") or not c.education or not c.skills:
        return {
            "status": "incomplete_profile",
            "message": "Upload your resume first so Compass has your name, email, education and skills.",
            "prepared_count": 0,
            "drafts": [],
        }

    profile = await radar_memory.get_user_opportunity_profile(user_id)
    ranked = [
        o for o in await recommended_for_user(user_id, profile)
        if o.eligibility_classification != EligibilityClassification.INELIGIBLE
    ]
    if not ranked:
        return {"status": "no_eligible_opportunities", "message": "No open internships fit your profile right now.", "prepared_count": 0, "drafts": []}

    results: List[Dict[str, Any]] = []
    for opp in ranked:
        if len(results) >= limit:
            break
        existing = await _existing_application(user_id, opp.id)
        if existing is not None and existing.resume_id:
            continue  # already prepared: not counted, the next match takes its place
        allowed, retry_after = check_and_record_auto_prepare_quota(user_id)
        if not allowed:
            return {
                "status": "rate_limited",
                "message": "Daily limit for automatic preparation reached. Try again tomorrow, or prepare listings one at a time.",
                "retry_after": retry_after,
                "prepared_count": len([r for r in results if r["status"] == "prepared"]),
                "drafts": results,
            }
        try:
            app = await prepare_application_for_user(user_id, opp.id, master_factory)
            results.append({
                "opportunity_id": opp.id, "company_name": opp.company_name, "role_title": opp.role_title,
                "application_id": app.id, "status": "prepared",
                "message": "Resume, cover letter and apply-by reminder are ready for your review.",
            })
        except HTTPException as err:
            results.append({"opportunity_id": opp.id, "company_name": opp.company_name, "role_title": opp.role_title, "status": "failed", "message": str(err.detail)})
    return {
        "status": "completed",
        "prepared_count": len([r for r in results if r["status"] == "prepared"]),
        "drafts": results,
    }


async def _existing_application(user_id: str, opportunity_id: int) -> Optional[CareerApplicationOut]:
    return await get_career_application_by_opportunity(user_id, opportunity_id)


__all__: List[str] = [
    "apply_by_date",
    "normalize_job_url",
    "infer_listing_identity",
    "prepare_application_for_user",
    "prepare_from_link",
    "prepare_top_matches",
]
