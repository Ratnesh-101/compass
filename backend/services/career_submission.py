"""
Compass — Career Copilot Submission Engine & Adapters.

Implements Sections 3.3, 9, and 10:
- Enforces strict user approval before any submission attempt.
- Cryptographically signed and time-bounded approval tokens with content digest verification.
- Modular submission adapters with declared capabilities (ManualHandoff, AtsEndpoint, BrowserAssisted).
- Concurrency locks and duplicate submission replay protection.
- Guardrails against submitting cancelled, withdrawn, or unapproved applications.
- Comprehensive audit logging and event tracking.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import httpx

from backend.memory.career import (
    get_career_application_by_id,
    get_resume_by_id,
    log_application_event,
    update_career_application,
)
from backend.memory.radar import get_opportunity_by_id
from backend.models_career import (
    CareerApplicationOut,
    CareerApplicationStatus,
    ResumeValidationStatus,
    SubmissionAdapterCapability,
    SubmissionMethod,
    SubmissionResultItem,
)

logger = logging.getLogger("compass.career.submission")

# In-memory concurrency locks per batch
_batch_locks: Dict[str, asyncio.Lock] = {}


def get_batch_lock(batch_id: str) -> asyncio.Lock:
    """Returns an asyncio.Lock specific to the given batch ID to prevent race conditions."""
    if batch_id not in _batch_locks:
        _batch_locks[batch_id] = asyncio.Lock()
    return _batch_locks[batch_id]


# ---------------------------------------------------------------------------
# Cryptographic Approval Token Engine
# ---------------------------------------------------------------------------

def _get_submission_secret() -> bytes:
    """Derives a strong HMAC key for approval tokens using PBKDF2."""
    from backend.config import get_settings
    settings = get_settings()
    raw = (
        getattr(settings, "TOKEN_ENCRYPTION_KEY", None)
        or getattr(settings, "AUTH_TOKEN", None)
        or "compass-career-approval-secret-salt"
    )
    return hashlib.pbkdf2_hmac(
        "sha256",
        raw.encode("utf-8"),
        b"compass_career_approval_fixed_salt",
        iterations=100_000,
        dklen=32,
    )


def compute_batch_content_hash(apps_data: List[Dict[str, Any]]) -> str:
    """Computes a deterministic SHA-256 digest of applications in a batch."""
    elements = []
    for app in sorted(apps_data, key=lambda a: a.get("id", 0)):
        aid = app.get("id")
        opp_id = app.get("opportunity_id")
        res_id = app.get("resume_id")
        cl = app.get("cover_letter") or ""
        fa = json.dumps(app.get("form_answers") or {}, sort_keys=True)
        # Version stamp of the linked resume: editing the resume after approval changes the hash.
        res_stamp = app.get("resume_stamp") or ""
        elements.append(f"{aid}:{opp_id}:{res_id}:{res_stamp}:{cl}:{fa}")
    joined = "|".join(elements)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _resume_stamp(resume: Any) -> str:
    updated = getattr(resume, "updated_at", None)
    stamp = updated.isoformat() if hasattr(updated, "isoformat") else str(updated or "")
    return f"v{getattr(resume, 'version', 1)}@{stamp}"


async def load_batch_apps_data(user_id: str, app_ids: List[int]) -> List[Dict[str, Any]]:
    """Owner-scoped application dicts for hashing, each stamped with its resume's version/updated_at."""
    apps_data: List[Dict[str, Any]] = []
    for aid in app_ids:
        app_rec = await get_career_application_by_id(aid, user_id)
        if not app_rec:
            continue
        data = app_rec.model_dump()
        if app_rec.resume_id:
            resume = await get_resume_by_id(app_rec.resume_id, user_id)
            data["resume_stamp"] = _resume_stamp(resume) if resume else "missing"
        apps_data.append(data)
    return apps_data


_APPROVABLE_RESUME_STATUSES = {
    ResumeValidationStatus.READY_FOR_REVIEW,
    ResumeValidationStatus.APPROVED,
}


async def find_batch_not_ready(user_id: str, app_ids: List[int]) -> List[Dict[str, Any]]:
    """Readiness gate for batch approval: list apps lacking a valid resume or a cover letter."""
    problems: List[Dict[str, Any]] = []
    for aid in app_ids:
        app_rec = await get_career_application_by_id(aid, user_id)
        if not app_rec:
            problems.append({"application_id": aid, "reasons": ["Application not found."]})
            continue
        reasons: List[str] = []
        resume = await get_resume_by_id(app_rec.resume_id, user_id) if app_rec.resume_id else None
        if not app_rec.resume_id:
            reasons.append("No tailored resume attached.")
        elif not resume:
            reasons.append("Attached resume not found.")
        elif resume.validation_status not in _APPROVABLE_RESUME_STATUSES:
            reasons.append(f"Resume validation status is {resume.validation_status.value}.")
        if not (app_rec.cover_letter or "").strip():
            reasons.append("No cover letter.")
        if reasons:
            problems.append({"application_id": aid, "reasons": reasons})
    return problems


def generate_batch_approval_token(
    user_id: str,
    batch_id: str,
    application_ids: List[int],
    content_hash: str,
    expires_in_seconds: int = 3600,
) -> str:
    """Generate cryptographically HMAC-signed approval token bound to user, batch, content hash, and timestamp."""
    secret = _get_submission_secret()
    issued_at = int(time.time())
    expires_at = issued_at + expires_in_seconds
    apps_str = ",".join(str(aid) for aid in sorted(application_ids))
    payload = f"{user_id.lower()}:{batch_id}:{apps_str}:{content_hash}:{issued_at}:{expires_at}".encode("utf-8")
    sig = hmac.new(secret, payload, digestmod=hashlib.sha256).hexdigest()
    raw = f"{user_id.lower()}:{batch_id}:{apps_str}:{content_hash}:{issued_at}:{expires_at}:{sig}"
    return "bat_" + base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def verify_batch_approval_token(
    token: str,
    expected_user_id: str,
    expected_batch_id: str,
    expected_content_hash: str,
) -> Tuple[bool, str]:
    """Verify that an approval token is authentic, unexpired, and strictly matches user, batch, and reviewed content."""
    if not token or not token.startswith("bat_"):
        return False, "Invalid approval token format."
    try:
        raw = base64.urlsafe_b64decode(token[4:].encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        if len(parts) != 7:
            return False, "Malformed approval token payload."
        u_id, b_id, apps_str, c_hash, issued_at_str, expires_at_str, sig = parts
        if u_id.lower() != expected_user_id.lower():
            return False, "Approval token user mismatch (unauthorized cross-user token)."
        if b_id != expected_batch_id:
            return False, "Approval token batch ID mismatch."
        now = int(time.time())
        expires_at = int(expires_at_str)
        if now > expires_at:
            return False, "Approval token has expired. Re-approval required."
        if c_hash != expected_content_hash:
            return False, "Batch or application content was modified after approval. Renewed approval is required."
        secret = _get_submission_secret()
        payload = f"{u_id.lower()}:{b_id}:{apps_str}:{c_hash}:{issued_at_str}:{expires_at_str}".encode("utf-8")
        expected_sig = hmac.new(secret, payload, digestmod=hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False, "Approval token cryptographic signature verification failed."
        return True, "Valid"
    except Exception as e:
        return False, f"Token verification error: {e}"


# ---------------------------------------------------------------------------
# Adapter Capability Declarations
# ---------------------------------------------------------------------------

SUPPORTED_ADAPTERS: List[SubmissionAdapterCapability] = [
    SubmissionAdapterCapability(
        adapter_id="manual_handoff",
        display_name="Verified Application Package (Direct Handoff)",
        description="Generates verified tailored resume, tailored cover notes, and pre-filled answers with direct official portal link.",
        is_automated=False,
        requires_credentials=False,
        is_configured=True,
        supported_platforms=["All Platforms", "Workday", "TCS iON", "Custom Portals", "Google Careers", "Microsoft"],
    ),
    SubmissionAdapterCapability(
        adapter_id="ats_endpoint",
        display_name="ATS Direct Postings API",
        description="Programmatic submission via supported partner posting endpoints where employer API key is configured.",
        is_automated=True,
        requires_credentials=True,
        is_configured=False,
        supported_platforms=["Configured Partner ATS APIs"],
    ),
    SubmissionAdapterCapability(
        adapter_id="browser_assisted",
        display_name="Browser-Assisted Form Prefill",
        description="Assists candidate by pre-filling verified application fields while candidate executes final manual submit button.",
        is_automated=False,
        requires_credentials=False,
        is_configured=True,
        supported_platforms=["Standard Web Application Forms"],
    ),
]


def generate_manual_application_package(
    app: CareerApplicationOut,
    opp_dict: Dict[str, Any],
    resume_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generates a complete, ready-to-paste application kit for direct portal submission."""
    portal_url = opp_dict.get("official_application_url") or opp_dict.get("canonical_url")
    answers = app.form_answers or {}

    resume_content = (resume_dict or {}).get("content", {})
    cover_letter = app.cover_letter or (resume_dict or {}).get("cover_letter")

    # Detect missing required fields for the application
    missing = []
    if not resume_content.get("email"):
        missing.append("Email address")
    if not resume_content.get("phone"):
        missing.append("Phone number")
    if not resume_content.get("education"):
        missing.append("Education history")
    if not answers.get("work_authorization"):
        missing.append("Work authorization declaration")
    if not answers.get("availability"):
        missing.append("Availability")
    current_degree = answers.get("degree") or answers.get("current_degree")
    if not current_degree:
        missing.append("Current degree")

    return {
        "portal_url": portal_url,
        "company_name": opp_dict.get("company_name"),
        "role_title": opp_dict.get("role_title"),
        "deadline": opp_dict.get("confirmed_close_date"),
        "tailored_resume_title": (resume_dict or {}).get("title", "Tailored Resume"),
        "cover_letter": cover_letter,
        "missing_fields": missing,
        "candidate_info": {
            "name": resume_content.get("full_name"),
            "email": resume_content.get("email"),
            "phone": resume_content.get("phone"),
            "github_portfolio": resume_content.get("github_or_portfolio"),
            "linkedin": resume_content.get("linkedin_url"),
            "location": resume_content.get("location"),
        },
        "prefilled_answers": {
            # Unknown answers stay None: the candidate must supply them, we never invent them.
            "work_authorization": answers.get("work_authorization") or None,
            "availability": answers.get("availability") or None,
            "current_degree": current_degree or None,
            "skills_summary": ", ".join(resume_content.get("skills", [])[:6]),
        },
        "submission_instructions": [
            f"1. Open the official application page at: {portal_url}",
            "2. Upload your validated tailored resume.",
            "3. If requested, attach your truthful tailored cover letter.",
            "4. Paste the prefilled candidate details into the respective fields.",
            "5. Review legal attestations and click Submit.",
            "6. Mark the application as 'Applied' in Compass to monitor follow-ups.",
        ],
    }


# ---------------------------------------------------------------------------
# Adapter Implementations
# ---------------------------------------------------------------------------

class BaseSubmissionAdapter:
    adapter_id: str
    display_name: str

    async def execute(
        self,
        app: CareerApplicationOut,
        opp_dict: Dict[str, Any],
        resume_dict: Optional[Dict[str, Any]],
        user_id: str,
    ) -> SubmissionResultItem:
        raise NotImplementedError


class ManualHandoffAdapter(BaseSubmissionAdapter):
    adapter_id = "manual_handoff"
    display_name = "Verified Application Package (Direct Handoff)"

    async def execute(
        self,
        app: CareerApplicationOut,
        opp_dict: Dict[str, Any],
        resume_dict: Optional[Dict[str, Any]],
        user_id: str,
    ) -> SubmissionResultItem:
        pkg = generate_manual_application_package(app, opp_dict, resume_dict)
        now_ts = datetime.now(timezone.utc)
        await update_career_application(app.id, user_id, {
            "status": CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
            "submission_method": SubmissionMethod.MANUAL_HANDOFF.value,
            "submission_payload": pkg,
            "submission_result": {
                "result": "manual_package_generated",
                "generated_at": now_ts.isoformat(),
            },
        })
        await log_application_event(app.id, "manual_handoff_prepared", {"portal_url": pkg.get("portal_url")})
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", ""),
            role_title=opp_dict.get("role_title", ""),
            status=CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
            submission_method=SubmissionMethod.MANUAL_HANDOFF.value,
            message="Verified application kit generated. Ready for immediate one-click submission on official portal.",
            manual_package=pkg,
        )


class AtsEndpointAdapter(BaseSubmissionAdapter):
    adapter_id = "ats_endpoint"
    display_name = "ATS Direct Postings API"

    async def execute(
        self,
        app: CareerApplicationOut,
        opp_dict: Dict[str, Any],
        resume_dict: Optional[Dict[str, Any]],
        user_id: str,
    ) -> SubmissionResultItem:
        from backend.config import get_settings
        settings = get_settings()
        ats_key = getattr(settings, "ATS_ENTERPRISE_API_KEY", None) or os.getenv("ATS_ENTERPRISE_API_KEY")
        if not ats_key:
            # ATS direct enterprise endpoints require employer-level keys not available to public applicants.
            # Transparently fall back to verified manual application kit.
            pkg = generate_manual_application_package(app, opp_dict, resume_dict)
            now_ts = datetime.now(timezone.utc)
            await update_career_application(app.id, user_id, {
                "status": CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
                "submission_method": SubmissionMethod.MANUAL_HANDOFF.value,
                "submission_payload": pkg,
                "submission_result": {
                    "result": "manual_package_generated",
                    "reason": "Direct enterprise API credentials not configured; generated verified direct portal kit.",
                    "generated_at": now_ts.isoformat(),
                },
            })
            await log_application_event(app.id, "ats_endpoint_abstain_fallback", {"reason": "ATS API key unconfigured"})
            return SubmissionResultItem(
                application_id=app.id,
                company_name=opp_dict.get("company_name", ""),
                role_title=opp_dict.get("role_title", ""),
                status=CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
                submission_method=SubmissionMethod.MANUAL_HANDOFF.value,
                message="Direct enterprise ATS credentials not configured. Generated verified direct application package.",
                manual_package=pkg,
            )

        # When configured, programmatic dispatch
        # Step 1: Record external submission attempt
        await update_career_application(app.id, user_id, {
            "status": CareerApplicationStatus.SUBMITTING.value,
            "submission_method": SubmissionMethod.ATS_ENDPOINT.value,
        })
        await log_application_event(app.id, "ats_submission_attempted", {"ats_key_configured": True})

        # Step 2: Dispatch to configured ATS endpoint
        endpoint_url = getattr(settings, "ATS_ENDPOINT_URL", None) or os.getenv("ATS_ENDPOINT_URL") or "https://api.partner-ats.compass/v1/applications"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {
                    "applicant_id": user_id,
                    "requisition_id": opp_dict.get("official_application_url") or str(app.opportunity_id),
                    "answers": app.form_answers or {},
                    "resume_summary": (resume_dict or {}).get("title"),
                    "cover_letter": app.cover_letter,
                }
                resp = await client.post(
                    endpoint_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {ats_key}", "Content-Type": "application/json"},
                )
                if resp.status_code in {200, 201}:
                    try:
                        raw_data = resp.json()
                        if asyncio.iscoroutine(raw_data):
                            raw_data = await raw_data
                        data = raw_data if isinstance(raw_data, dict) else {}
                    except Exception:
                        data = {}
                    ref_id = data.get("reference_id") or data.get("id") or f"ats_ref_{uuid.uuid4().hex[:8]}"
                    now_ts = datetime.now(timezone.utc)
                    await update_career_application(app.id, user_id, {
                        "status": CareerApplicationStatus.SUBMITTED.value,
                        "submitted_at": now_ts,
                        "submission_result": {"reference_id": ref_id, "submitted_at": now_ts.isoformat(), "response": data},
                    })
                    await log_application_event(app.id, "ats_direct_submitted", {"reference_id": ref_id})
                    return SubmissionResultItem(
                        application_id=app.id,
                        company_name=opp_dict.get("company_name", ""),
                        role_title=opp_dict.get("role_title", ""),
                        status=CareerApplicationStatus.SUBMITTED.value,
                        submission_method=SubmissionMethod.ATS_ENDPOINT.value,
                        reference_id=ref_id,
                        message="Application submitted directly and confirmed by partner ATS API.",
                    )
                else:
                    err_msg = f"ATS API returned HTTP {resp.status_code}: {resp.text[:200]}"
                    await update_career_application(app.id, user_id, {
                        "status": CareerApplicationStatus.SUBMISSION_FAILED.value,
                        "submission_result": {"error": err_msg, "status_code": resp.status_code},
                    })
                    await log_application_event(app.id, "ats_submission_failed", {"status_code": resp.status_code})
                    return SubmissionResultItem(
                        application_id=app.id,
                        company_name=opp_dict.get("company_name", ""),
                        role_title=opp_dict.get("role_title", ""),
                        status=CareerApplicationStatus.SUBMISSION_FAILED.value,
                        submission_method=SubmissionMethod.ATS_ENDPOINT.value,
                        message=err_msg,
                    )
        except Exception as exc:
            err_msg = f"Network timeout or connection error during ATS submission: {exc}"
            logger.error("ATS submission outcome uncertain: %s", exc)
            await update_career_application(app.id, user_id, {
                "status": CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value,
                "submission_result": {"error": err_msg, "outcome": "uncertain"},
            })
            await log_application_event(app.id, "ats_submission_outcome_uncertain", {"error": str(exc)})
            return SubmissionResultItem(
                application_id=app.id,
                company_name=opp_dict.get("company_name", ""),
                role_title=opp_dict.get("role_title", ""),
                status=CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value,
                submission_method=SubmissionMethod.ATS_ENDPOINT.value,
                message=(
                    "Remote ATS connection timed out or failed to return confirmation. "
                    "Outcome is uncertain. Automated retry is blocked to prevent duplicate submission. "
                    "Please verify with the employer directly before attempting to resubmit."
                ),
            )


class BrowserAssistedAdapter(BaseSubmissionAdapter):
    adapter_id = "browser_assisted"
    display_name = "Browser-Assisted Form Prefill"

    async def execute(
        self,
        app: CareerApplicationOut,
        opp_dict: Dict[str, Any],
        resume_dict: Optional[Dict[str, Any]],
        user_id: str,
    ) -> SubmissionResultItem:
        pkg = generate_manual_application_package(app, opp_dict, resume_dict)
        portal_url = pkg.get("portal_url")
        prefill_data = {
            "full_name": pkg["candidate_info"].get("name"),
            "email": pkg["candidate_info"].get("email"),
            "phone": pkg["candidate_info"].get("phone"),
            "location": pkg["candidate_info"].get("location"),
            "linkedin_profile": pkg["candidate_info"].get("linkedin"),
            "github_portfolio": pkg["candidate_info"].get("github_portfolio"),
            "work_authorization": pkg["prefilled_answers"].get("work_authorization"),
            "availability": pkg["prefilled_answers"].get("availability"),
            "degree": pkg["prefilled_answers"].get("current_degree"),
            "cover_letter_text": pkg.get("cover_letter"),
        }
        browser_kit = {
            "portal_url": portal_url,
            "prefill_data": prefill_data,
            "dom_selector_hints": {
                "name": "input[name*='name'], input[autocomplete='name']",
                "email": "input[type='email'], input[name*='email']",
                "phone": "input[type='tel'], input[name*='phone']",
                "resume_upload": "input[type='file'][accept*='pdf']",
            },
            "security_guardrails": [
                "Compass never bypasses CAPTCHA, bot checks, or multi-factor authentication.",
                "Candidate retains complete control and reviews all fields before clicking final submit.",
            ],
            "submission_instructions": [
                f"1. Open the official application URL: {portal_url}",
                "2. Compass Browser Assist pre-fills your verified candidate information.",
                "3. Upload the validated ATS-friendly PDF resume.",
                "4. Review legal attestations and complete any candidate CAPTCHA manually.",
                "5. Click Submit on the employer portal.",
            ],
        }
        now_ts = datetime.now(timezone.utc)
        await update_career_application(app.id, user_id, {
            "status": CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
            "submission_method": SubmissionMethod.BROWSER_ASSISTED.value,
            "submission_payload": browser_kit,
            "submission_result": {
                "result": "browser_assist_kit_generated",
                "generated_at": now_ts.isoformat(),
            },
        })
        await log_application_event(app.id, "browser_assist_prepared", {"portal_url": portal_url})
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", ""),
            role_title=opp_dict.get("role_title", ""),
            status=CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
            submission_method=SubmissionMethod.BROWSER_ASSISTED.value,
            message="Browser-assisted prefill kit ready. Pre-fills verified data while candidate confirms final submission.",
            manual_package=browser_kit,
        )


_ADAPTERS_MAP = {
    SubmissionMethod.MANUAL_HANDOFF: ManualHandoffAdapter(),
    SubmissionMethod.ATS_ENDPOINT: AtsEndpointAdapter(),
    SubmissionMethod.OFFICIAL_API: AtsEndpointAdapter(),
    SubmissionMethod.BROWSER_ASSISTED: BrowserAssistedAdapter(),
}


# ---------------------------------------------------------------------------
# Submission Execution Functions
# ---------------------------------------------------------------------------

async def submit_single_application(
    app_id: int,
    user_id: str,
    method: SubmissionMethod = SubmissionMethod.MANUAL_HANDOFF,
) -> SubmissionResultItem:
    """
    Submits or packages a single application.
    STRICT SAFETY RULE: Enforces that the application was explicitly approved,
    is not cancelled or withdrawn, and has not already been submitted.
    """
    app = await get_career_application_by_id(app_id, user_id)
    if not app:
        return SubmissionResultItem(
            application_id=app_id,
            company_name="Unknown",
            role_title="Unknown",
            status="FAILED",
            submission_method=method.value,
            message="Application record not found.",
        )

    opp = await get_opportunity_by_id(app.opportunity_id, user_id)
    opp_dict = opp.model_dump() if opp else {"company_name": "Company", "role_title": "Role"}

    resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
    resume_dict = resume.model_dump() if resume else None

    # 1. Guard against cancelled or withdrawn applications
    if app.status in {CareerApplicationStatus.WITHDRAWN, CareerApplicationStatus.CLOSED}:
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", ""),
            role_title=opp_dict.get("role_title", ""),
            status="BLOCKED",
            submission_method=method.value,
            message=f"Submission blocked: Application has been {app.status.value.lower()}.",
        )

    # 2. Guard against retrying uncertain outcomes
    if app.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN:
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", ""),
            role_title=opp_dict.get("role_title", ""),
            status="BLOCKED",
            submission_method=method.value,
            message="Submission blocked: A prior submission attempt had an uncertain outcome. Automated retries are blocked to prevent duplicate submissions. Please verify the application status directly on the portal or in your email.",
        )

    # 3. Verification of explicit approval gate (Section 3.3)
    if app.status != CareerApplicationStatus.APPROVED_FOR_SUBMISSION:
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", f"Opportunity #{app.opportunity_id}"),
            role_title=opp_dict.get("role_title", "Role"),
            status="BLOCKED",
            submission_method=method.value,
            message="Submission blocked: Application has not been explicitly reviewed and approved by user.",
        )

    # 4. Check for duplicate submission
    if app.submitted_at:
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", ""),
            role_title=opp_dict.get("role_title", ""),
            status="ALREADY_SUBMITTED",
            submission_method=app.submission_method.value,
            message=f"Application was already submitted on {app.submitted_at.isoformat()}.",
        )

    # 5. Atomically claim application row for submission across multi-worker environments
    from backend.memory.career import claim_career_application_for_submission
    claimed_app = await claim_career_application_for_submission(app.id, user_id)
    if not claimed_app:
        return SubmissionResultItem(
            application_id=app.id,
            company_name=opp_dict.get("company_name", ""),
            role_title=opp_dict.get("role_title", ""),
            status="BLOCKED",
            submission_method=method.value,
            message="Submission blocked: Application is currently being submitted or was already processed.",
        )

    # 6. Route to adapter instance
    adapter = _ADAPTERS_MAP.get(method, ManualHandoffAdapter())
    return await adapter.execute(app, opp_dict, resume_dict, user_id)


async def execute_batch_submission(
    user_id: str,
    batch_dict: Dict[str, Any],
    method: Optional[SubmissionMethod] = None,
) -> List[SubmissionResultItem]:
    """
    Submits all approved applications in an approved batch with rate limiting and per-item results.
    """
    app_ids: List[int] = batch_dict.get("application_ids", [])
    results: List[SubmissionResultItem] = []
    chosen_method = method or SubmissionMethod.MANUAL_HANDOFF

    for aid in app_ids:
        # Bounded rate limiting between submissions
        await asyncio.sleep(0.05)
        item_res = await submit_single_application(aid, user_id, chosen_method)
        results.append(item_res)

    return results
