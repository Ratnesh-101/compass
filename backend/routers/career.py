"""
Compass - Career Copilot API Router.

Provides authenticated endpoints for:
1. Resume Studio: Master resumes, role-specific tailoring, factual validation reports, HTML/PDF export.
2. Application Center: Application tracking, structured answers, batch preparation, explicit approval, submission execution.
3. Submission Adapters: Available capabilities and prerequisites.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse

from backend.services.career_auto_prepare import (
    execute_auto_prepare_for_user,
    get_user_quota_status,
)
from backend.services import winning_features
from backend.services.company_intel_jobs import (
    SCHEMA_VERSION,
    create_job,
    get_active_job_for_opportunity,
    get_job,
    run_intel_refresh_job,
)
from backend.services.rate_limiter import enforce_company_intel_guard
from backend.services.career_file_parser import (
    MAX_RESUME_FILE_SIZE,
    ResumeParseResult,
    extract_resume_from_file_bytes,
)

from backend.dependencies import _get_current_identity, _get_or_create_user_id, rate_limit
from backend.services.resume_merge import merge_resume_content
from backend.memory.career import (
    APPROVABLE_BATCH_STATUSES,
    approve_application_batch,
    create_application_batch,
    create_tailored_resume,
    delete_tailored_resume,
    finish_application_batch,
    get_application_batch,
    get_career_application_by_id,
    get_career_application_by_opportunity,
    get_master_resume,
    get_original_resume_document,
    get_resume_by_id,
    list_application_events,
    list_career_applications,
    list_original_resume_documents,
    list_resumes,
    log_application_event,
    link_resume_if_unlinked,
    save_original_resume_document,
    update_career_application,
    update_resume,
    upsert_master_resume,
)
from backend.memory.radar import get_opportunity_by_id, get_user_opportunity_profile
from backend.models_radar import UserOpportunityProfileIn
from backend.models_career import (
    BatchApproveRequest,
    BatchPrepareRequest,
    BatchReviewOut,
    BatchSubmitRequest,
    BatchSubmitResultOut,
    CareerApplicationOut,
    CareerApplicationStatus,
    CommitExtractedResumeRequest,
    CoverLetterOut,
    DraftCoverLetterRequest,
    ExternalProfileImportRequest,
    GitHubImportRequest,
    GitHubProfileIntelligence,
    HandoffKitOut,
    AddSkillRequest,
    JobAnalysisReport,
    OriginalResumeDocument,
    ResumeContent,
    ResumeOut,
    ResumeParseUploadOut,
    ResumeParseUploadRequest,
    ResumeValidationReport,
    ResumeValidationStatus,
    SaveResumeRequest,
    SetCoverLetterRequest,
    SubmissionAdapterCapability,
    SubmissionMethod,
    TailorResumeRequest,
    UpdateApplicationStatusRequest,
)
from backend.services.career_github import analyze_github_profile
from backend.services.career_job_match import analyze_job_and_match
from backend.services.career_profile_sources import ingest_external_profile
from backend.services.career_resume import (
    build_default_master_from_profile,
    draft_truthful_cover_letter,
    generate_resume_docx,
    generate_resume_html,
    analyze_extraction_diagnostics,
    parse_uploaded_resume_text,
    tailor_resume_for_opportunity,
    validate_resume_against_master,
)
from backend.services.career_submission import (
    SUPPORTED_ADAPTERS,
    compute_batch_content_hash,
    execute_batch_submission,
    find_batch_not_ready,
    generate_batch_approval_token,
    get_batch_lock,
    load_batch_apps_data,
    submit_single_application,
    verify_batch_approval_token,
)

logger = logging.getLogger("compass.routers.career")

router = APIRouter(prefix="/api/career", tags=["career_copilot"])


# ===========================================================================
# 1. Resume Studio Endpoints
# ===========================================================================

def _build_initial_master_content(profile: Optional[UserOpportunityProfileIn], request: Request) -> ResumeContent:
    ident = getattr(request.state, "identity", None) or _get_current_identity(request)
    authed_name = ""
    authed_email = ""
    if ident and not ident.is_guest and ident.user_id:
        if "@" in ident.user_id:
            authed_email = ident.user_id
        else:
            authed_name = ident.user_id
    return build_default_master_from_profile(profile, user_name=authed_name, email=authed_email)


@router.get("/resumes/master", response_model=ResumeOut)
async def get_master_resume_endpoint(request: Request):
    """Retrieve the candidate's master resume, auto-creating a truthful draft from profile if missing."""
    user_id = _get_or_create_user_id(request)
    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id)
        if not profile:
            from backend.models_radar import UserOpportunityProfileIn
            profile = UserOpportunityProfileIn()
        default_content = _build_initial_master_content(profile, request)
        master = await upsert_master_resume(user_id, default_content, "Master Resume")
    return master


@router.put("/resumes/master", response_model=ResumeOut)
async def update_master_resume_endpoint(body: ResumeContent, request: Request):
    """Update master resume content with verified candidate information."""
    user_id = _get_or_create_user_id(request)
    return await upsert_master_resume(user_id, body, "Master Resume")


@router.get("/resumes", response_model=List[ResumeOut])
async def list_resumes_endpoint(request: Request):
    """List all master and tailored resume versions for the user."""
    user_id = _get_or_create_user_id(request)
    return await list_resumes(user_id)


@router.post("/resumes/tailor", response_model=ResumeOut)
async def tailor_resume_endpoint(body: TailorResumeRequest, request: Request):
    """
    Generate a tailored resume variant for a target opportunity.
    Strictly aligns verified master skills and projects without hallucination.
    """
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(body.opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    linked_app = None
    if body.application_id is not None:
        # Owner-scoped lookup: another user's application answers 404, same as a missing one.
        linked_app = await get_career_application_by_id(body.application_id, user_id)
        if not linked_app:
            raise HTTPException(status_code=404, detail="Application not found")
        if linked_app.opportunity_id != opp.id:
            raise HTTPException(status_code=400, detail="Application does not belong to this opportunity")
        if _status_value(linked_app) not in _RESUME_RELINKABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot change the resume of an application in status '{_status_value(linked_app)}'.",
            )

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id)
        if not profile:
            from backend.models_radar import UserOpportunityProfileIn
            profile = UserOpportunityProfileIn()
        default_content = _build_initial_master_content(profile, request)
        master = await upsert_master_resume(user_id, default_content, "Master Resume")

    tailored_content, report, status = tailor_resume_for_opportunity(
        master=master.content,
        opportunity=opp,
        custom_title=body.custom_title,
        skills_emphasis=body.target_skills_emphasis,
    )

    title = body.custom_title or f"{opp.company_name} — {opp.role_title} Tailored"
    tailored = await create_tailored_resume(
        user_id=user_id,
        opportunity_id=opp.id,
        title=title,
        content=tailored_content,
        validation_report=report,
        validation_status=status,
    )
    if linked_app is not None:
        updates: Dict[str, Any] = {"resume_id": tailored.id}
        new_status = _status_for_resume(linked_app, status)
        if new_status:
            updates["status"] = new_status
        await update_career_application(linked_app.id, user_id, updates)
        await log_application_event(linked_app.id, "resume_retailored", {"resume_id": tailored.id})
    return tailored


@router.get("/resumes/original-documents", response_model=List[OriginalResumeDocument])
async def list_original_resume_documents_endpoint(request: Request):
    """Retrieve all preserved original uploaded resume documents for the candidate."""
    user_id = _get_or_create_user_id(request)
    return await list_original_resume_documents(user_id)


@router.get("/resumes/{resume_id}", response_model=ResumeOut)
async def get_resume_endpoint(resume_id: int, request: Request):
    """Retrieve a single resume by ID."""
    user_id = _get_or_create_user_id(request)
    res = await get_resume_by_id(resume_id, user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")
    return res


@router.put("/resumes/{resume_id}", response_model=ResumeOut)
async def update_resume_endpoint(resume_id: int, body: SaveResumeRequest, request: Request):
    """
    Update a specific resume (master or tailored).
    Ensures updates are scoped to the authenticated user and validates against factual integrity.
    """
    user_id = _get_or_create_user_id(request)
    res = await get_resume_by_id(resume_id, user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")

    master = await get_master_resume(user_id)
    master_content = master.content if (master and not res.is_master) else body.content

    opp = None
    if res.opportunity_id:
        opp = await get_opportunity_by_id(res.opportunity_id, user_id)

    report = validate_resume_against_master(body.content, master_content, opp)
    new_status = ResumeValidationStatus.READY_FOR_REVIEW if report.is_valid else ResumeValidationStatus.VALIDATION_FAILED

    updates: Dict[str, Any] = {
        "title": body.title,
        "content": body.content,
        "validation_status": new_status.value,
        "validation_report": report,
    }
    if body.cover_letter is not None:
        updates["cover_letter"] = body.cover_letter

    updated = await update_resume(resume_id, user_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Resume update failed")
    return updated


@router.post("/resumes/{resume_id}/validate", response_model=ResumeValidationReport)
async def validate_resume_endpoint(resume_id: int, request: Request):
    """Run strict factual integrity and completeness audit on a resume."""
    user_id = _get_or_create_user_id(request)
    res = await get_resume_by_id(resume_id, user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")

    master = await get_master_resume(user_id)
    master_content = res.content if res.is_master else (master.content if master else res.content)

    opp = None
    if res.opportunity_id:
        opp = await get_opportunity_by_id(res.opportunity_id, user_id)

    report = validate_resume_against_master(res.content, master_content, opp)
    new_status = ResumeValidationStatus.READY_FOR_REVIEW if report.is_valid else ResumeValidationStatus.VALIDATION_FAILED

    await update_resume(resume_id, user_id, {
        "validation_status": new_status.value,
        "validation_report": report,
    })
    return report


@router.get("/resumes/{resume_id}/export", response_class=HTMLResponse)
@router.get("/resumes/{resume_id}/export/html", response_class=HTMLResponse)
async def export_resume_html_endpoint(
    resume_id: int,
    request: Request,
    template: Optional[str] = Query(None),
):
    """Export clean, ATS-formatted printable HTML for PDF generation."""
    user_id = _get_or_create_user_id(request)
    res = await get_resume_by_id(resume_id, user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Guard against placeholder or empty candidate data before export
    PLACEHOLDER_NAMES = {"compass candidate", "candidate"}
    PLACEHOLDER_EMAILS = {"candidate@compass.local"}
    name = (res.content.full_name or "").strip()
    email = (res.content.email or "").strip()
    missing_fields = []
    if not name or name.lower() in PLACEHOLDER_NAMES:
        missing_fields.append("Candidate Full Name (currently missing or placeholder)")
    if not email or email.lower() in PLACEHOLDER_EMAILS or "@" not in email:
        missing_fields.append("Candidate Email (currently missing or placeholder)")
    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export resume: Please replace placeholder/empty profile fields with your real information before export: {', '.join(missing_fields)}.",
        )

    opp = None
    if res.opportunity_id:
        opp = await get_opportunity_by_id(res.opportunity_id, user_id)

    html = generate_resume_html(res, opp, template=template)
    return HTMLResponse(
        content=html,
        status_code=200,
        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:;"},
    )


@router.get("/resumes/{resume_id}/export/docx")
async def export_resume_docx_endpoint(
    resume_id: int,
    request: Request,
):
    """Export clean, ATS-compliant Microsoft Word (.docx) document."""
    user_id = _get_or_create_user_id(request)
    res = await get_resume_by_id(resume_id, user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Guard against placeholder or empty candidate data before export
    PLACEHOLDER_NAMES = {"compass candidate", "candidate"}
    PLACEHOLDER_EMAILS = {"candidate@compass.local"}
    name = (res.content.full_name or "").strip()
    email = (res.content.email or "").strip()
    missing_fields = []
    if not name or name.lower() in PLACEHOLDER_NAMES:
        missing_fields.append("Candidate Full Name (currently missing or placeholder)")
    if not email or email.lower() in PLACEHOLDER_EMAILS or "@" not in email:
        missing_fields.append("Candidate Email (currently missing or placeholder)")
    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export resume: Please replace placeholder/empty profile fields with your real information before export: {', '.join(missing_fields)}.",
        )

    opp = None
    if res.opportunity_id:
        opp = await get_opportunity_by_id(res.opportunity_id, user_id)

    docx_bytes = generate_resume_docx(res, opp)
    filename = re.sub(r"[^\w\s-]", "", res.title).strip().replace(" ", "_") or "Resume"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}.docx"'},
    )


# ===========================================================================
# Profile Intelligence Endpoints (GitHub, External Sources, Job Matching)
# ===========================================================================

@router.post("/intelligence/github", response_model=GitHubProfileIntelligence)
async def analyze_github_endpoint(body: GitHubImportRequest, request: Request):
    """
    Extracts verifiable engineering evidence from candidate's public GitHub profile.
    Distinguishes owned repos from forks, detects verified tech stack/tests, and applies
    prompt-injection defenses.
    """
    _get_or_create_user_id(request)
    return await analyze_github_profile(
        username_or_url=body.username_or_url,
        token=body.personal_access_token,
        excluded_repos=body.excluded_repos,
    )


@router.post("/intelligence/external-profile", response_model=ResumeContent, dependencies=[Depends(rate_limit)])
async def ingest_external_profile_endpoint(body: ExternalProfileImportRequest, request: Request):
    """
    Ingests candidate-provided external profile information (pasted LinkedIn text or data export).
    Never performs unauthorized scraping. Records provenance and evidence classification.
    """
    _get_or_create_user_id(request)
    content, notes = ingest_external_profile(body)
    return content


@router.get("/opportunities/{opportunity_id}/job-analysis", response_model=JobAnalysisReport)
async def analyze_opportunity_job_endpoint(
    opportunity_id: int,
    request: Request,
    custom_desc: Optional[str] = Query(None, max_length=20000),
):
    """
    Analyzes job description requirements (mandatory, preferred, responsibilities, eligibility)
    and maps supporting evidence from the candidate's verified Master Profile.
    """
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id)
        if not profile:
            from backend.models_radar import UserOpportunityProfileIn
            profile = UserOpportunityProfileIn()
        default_content = _build_initial_master_content(profile, request)
        master = await upsert_master_resume(user_id, default_content, "Master Resume")

    return analyze_job_and_match(
        opportunity=opp,
        master=master.content,
        custom_description=custom_desc,
    )


@router.get(
    "/opportunities/{opportunity_id}/company-intel",
    dependencies=[Depends(enforce_company_intel_guard)],
)
async def get_company_intel_endpoint(
    opportunity_id: int,
    request: Request,
    refresh: bool = Query(default=False),
):
    """
    Generates a strategic intelligence brief for a specific opportunity.
    Used in the Application Workspace to help candidates tailor their application.
    """
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    try:
        brief = await winning_features.generate_company_intel_brief(opp, force_refresh=refresh)
        return brief
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to generate company intel brief for opp %s: %s", opportunity_id, exc, exc_info=True)
        cached = winning_features.get_cached_company_intel(opportunity_id)
        if cached:
            cached_copy = dict(cached)
            cached_copy["refresh_failed"] = True
            cached_copy["showing_older_brief"] = True
            return cached_copy
        return winning_features._build_error_intel(
            opp.company_name,
            opp.role_title,
            error="We couldn't generate company intel right now. Please try again.",
        )


@router.post(
    "/opportunities/{opportunity_id}/company-intel/refresh",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_company_intel_guard)],
)
async def refresh_company_intel_job_endpoint(
    opportunity_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Asynchronously starts a background refresh job for company intelligence.
    Returns 202 Accepted with a job_id for client-side polling.
    """
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    job = await create_job(opp.id, opp.company_name, opp.role_title)
    if job.get("status") in ("queued", "running"):
        background_tasks.add_task(run_intel_refresh_job, job["job_id"], opp.id, user_id)

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "schema_version": SCHEMA_VERSION,
        "opportunity_id": opportunity_id,
        "company": opp.company_name,
    }


@router.get(
    "/opportunities/{opportunity_id}/company-intel/jobs/{job_id}",
    dependencies=[Depends(enforce_company_intel_guard)],
)
async def get_company_intel_job_endpoint(
    opportunity_id: int,
    job_id: str,
    request: Request,
):
    """
    Polls the status of an asynchronous company intelligence job.
    Returns status: queued | running | done | failed.
    """
    _get_or_create_user_id(request)
    job = await get_job(job_id)
    if not job or job.get("opportunity_id") != opportunity_id:
        raise HTTPException(status_code=404, detail="Company intel job not found")

    return job




@router.post("/resumes/parse-upload", response_model=ResumeParseUploadOut, dependencies=[Depends(rate_limit)])
async def parse_resume_upload_endpoint(body: ResumeParseUploadRequest, request: Request):
    """
    Extract structured candidate data from uploaded resume text.
    Strictly preserves factual information without hallucination.
    """
    _get_or_create_user_id(request)
    content = await asyncio.to_thread(parse_uploaded_resume_text, body.raw_text)
    diag = analyze_extraction_diagnostics(content, body.raw_text)
    confidence = dict(diag["field_confidence"])
    confidence["overall"] = diag["overall_confidence"]
    return ResumeParseUploadOut(
        **content.model_dump(),
        missing_fields=diag["missing_fields"],
        ambiguous_fields=diag["ambiguous_fields"],
        field_confidence=confidence,
        overall_confidence=diag["overall_confidence"],
    )


@router.post("/resumes/parse-file", response_model=ResumeParseResult, dependencies=[Depends(rate_limit)])
async def parse_resume_file_endpoint(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Safely extract and parse structured resume data from uploaded PDF, TXT, or MD file.
    Does NOT automatically save or overwrite the master resume.
    Preserves original uploaded resume document separately for provenance audit.
    Returns structured content, diagnostic warnings, and field confidence for review.
    """
    user_id = _get_or_create_user_id(request)
    content = await file.read(MAX_RESUME_FILE_SIZE + 1)
    if len(content) > MAX_RESUME_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File exceeds maximum allowed size of 5 MB.",
        )
    result = await asyncio.to_thread(
        extract_resume_from_file_bytes,
        content,
        filename=file.filename or "uploaded_resume.pdf",
        content_type=file.content_type,
    )
    if not result.success:
        raise HTTPException(
            status_code=400,
            detail=result.error_message or "Failed to extract text from resume file.",
        )

    # Preserve original uploaded file text separately from generated resumes
    if result.full_text or result.raw_text:
        orig_doc = await save_original_resume_document(
            user_id=user_id,
            filename=result.filename,
            file_type=result.file_type,
            raw_text=result.full_text or result.raw_text,
            metadata={"page_count": result.page_count, "confidence": result.field_confidence},
        )
        result.original_document_id = orig_doc.id

    return result


@router.post("/resumes/commit-extracted", response_model=ResumeOut, dependencies=[Depends(rate_limit)])
async def commit_extracted_resume_endpoint(
    body: CommitExtractedResumeRequest,
    request: Request,
):
    """
    Commits user-reviewed and edited extracted resume content to the master resume.
    Marks confirmed sections as USER_CONFIRMED to record explicit candidate audit.
    """
    user_id = _get_or_create_user_id(request)
    reviewed_content = body.content
    reviewed_content.evidence_classifications["user_review_status"] = "USER_CONFIRMED"
    reviewed_content.evidence_notes["review_timestamp"] = "CONFIRMED"

    if body.target == "master":
        existing = await get_master_resume(user_id)
        if existing is not None:
            reviewed_content = merge_resume_content(existing.content, reviewed_content)
        return await upsert_master_resume(user_id, reviewed_content, "Master Resume")
    else:
        report = validate_resume_against_master(reviewed_content, reviewed_content)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        return await create_tailored_resume(
            user_id=user_id,
            opportunity_id=None,
            title=f"Imported Resume Draft ({stamp} UTC)",
            content=reviewed_content,
            validation_report=report,
            validation_status=(
                ResumeValidationStatus.READY_FOR_REVIEW if report.is_valid else ResumeValidationStatus.NEEDS_USER_INPUT
            ),
        )


@router.post("/cover-letters/draft", response_model=CoverLetterOut)
async def draft_cover_letter_endpoint(body: DraftCoverLetterRequest, request: Request):
    """
    Draft a truthful, verified cover letter for a specific opportunity.
    Strictly references verified projects and master skills.
    """
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(body.opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id)
        if not profile:
            from backend.models_radar import UserOpportunityProfileIn
            profile = UserOpportunityProfileIn()
        default_content = _build_initial_master_content(profile, request)
        master = await upsert_master_resume(user_id, default_content, "Master Resume")

    letter_text, verified_projs, verified_skls = draft_truthful_cover_letter(
        master=master.content,
        opportunity=opp,
        emphasis_projects=body.emphasis_projects,
    )

    from datetime import datetime, timezone
    return CoverLetterOut(
        opportunity_id=opp.id,
        company_name=opp.company_name,
        role_title=opp.role_title,
        content=letter_text,
        verified_projects_referenced=verified_projs,
        verified_skills_referenced=verified_skls,
        created_at=datetime.now(timezone.utc),
    )


# ===========================================================================
# 2. Application Center Endpoints
# ===========================================================================

@router.post("/track-external-application", response_model=CareerApplicationOut)
async def track_external_application_endpoint(
    request: Request,
    opportunity_id: int = Query(...),
    source: Optional[str] = Query("external_website"),
):
    """
    Webhook for external websites to notify Compass that an application has been submitted.
    Automatically creates a record if missing and sets status to SUBMITTED.
    """
    user_id = _get_or_create_user_id(request)

    opp = await get_opportunity_by_id(opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    # 1. Ensure the application record exists
    from backend.memory.career import get_or_create_career_application
    app = await get_or_create_career_application(user_id, opportunity_id)

    # 2. Transition status to SUBMITTED and record timestamp (idempotent when already submitted)
    if not _is_already_submitted(app):
        _ensure_can_mark_submitted(app)
        updates = {
            "status": CareerApplicationStatus.SUBMITTED.value,
            "submitted_at": datetime.now(timezone.utc),
            "submission_method": SubmissionMethod.MANUAL_HANDOFF.value, # Default for external
        }
        if app.target_deadline is None:
            updates["target_deadline"] = datetime.now(timezone.utc).date() + timedelta(days=14)
        app = await update_career_application(app.id, user_id, updates)

        # 3. Log the external event
        await log_application_event(app.id, "EXTERNAL_SUBMISSION", {"source": source})

    # 4. Enrich response
    app.opportunity = opp
    resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
    app.resume = resume

    return app


@router.get("/applications", response_model=List[CareerApplicationOut])
async def list_applications_endpoint(request: Request, status: Optional[str] = Query(None)):
    """List tracked applications with opportunities and resumes attached."""
    user_id = _get_or_create_user_id(request)
    apps = await list_career_applications(user_id, status)
    # Enrich with opportunity data
    enriched: List[CareerApplicationOut] = []
    for app in apps:
        opp = await get_opportunity_by_id(app.opportunity_id, user_id)
        resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
        app.opportunity = opp
        app.resume = resume
        enriched.append(app)
    return enriched


@router.get("/applications/prepare", response_model=CareerApplicationOut)
async def get_prepared_application_endpoint(request: Request, opportunity_id: Optional[int] = Query(None)):
    """
    Read-only retrieval of an existing prepared application.
    Does NOT mutate, create, or alter any application or resume records.
    Returns 404 if the application has not yet been prepared.
    """
    user_id = _get_or_create_user_id(request)
    opp_id = opportunity_id
    if opp_id is None:
        q_id = request.query_params.get("opportunity_id")
        if q_id:
            try:
                opp_id = int(q_id)
            except ValueError:
                pass
    if not opp_id:
        raise HTTPException(status_code=400, detail="opportunity_id is required")

    app = await get_career_application_by_opportunity(user_id, opp_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not prepared yet. Use POST /applications/prepare to prepare.")

    opp = await get_opportunity_by_id(opp_id, user_id)
    resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
    app.opportunity = opp
    app.resume = resume
    return app


@router.post("/applications/prepare", response_model=CareerApplicationOut)
async def prepare_application_endpoint(request: Request, opportunity_id: Optional[int] = Query(None)):
    """Prepare an application record with tailored resume, truthful cover letter, and prefilled answers."""
    user_id = _get_or_create_user_id(request)
    opp_id = opportunity_id
    if opp_id is None:
        q_id = request.query_params.get("opportunity_id")
        if q_id:
            try:
                opp_id = int(q_id)
            except ValueError:
                pass
    if not opp_id:
        raise HTTPException(status_code=400, detail="opportunity_id is required")

    opp = await get_opportunity_by_id(opp_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    from backend.memory.career import get_or_create_career_application
    app = await get_or_create_career_application(user_id, opp_id)

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id)
        if not profile:
            from backend.models_radar import UserOpportunityProfileIn
            profile = UserOpportunityProfileIn()
        master = await upsert_master_resume(user_id, _build_initial_master_content(profile, request), "Master Resume")

    # Check or auto-tailor resume if not yet attached
    if not app.resume_id:
        tailored_content, report, val_status = tailor_resume_for_opportunity(master.content, opp)
        tailored = await create_tailored_resume(
            user_id=user_id,
            opportunity_id=opp.id,
            title=f"{opp.company_name} Tailored Resume",
            content=tailored_content,
            validation_report=report,
            validation_status=val_status,
        )
        # Conditional link (resume_id IS NULL): a concurrent prepare that lost the race
        # discards its own resume instead of leaving an orphan next to the winner's.
        linked = await link_resume_if_unlinked(app.id, user_id, tailored.id, _status_for_resume(app, val_status))
        if linked is None:
            await delete_tailored_resume(tailored.id, user_id)
            app = await get_career_application_by_id(app.id, user_id)
            if not app:
                raise HTTPException(status_code=404, detail="Application not found")
        else:
            app = linked
            app.resume = tailored

    # Draft truthful cover letter if not present
    if not app.cover_letter and master:
        letter_text, _, _ = draft_truthful_cover_letter(master.content, opp)
        app = await update_career_application(app.id, user_id, {
            "cover_letter": letter_text,
        })

    app.opportunity = opp
    if app.resume_id and not app.resume:
        app.resume = await get_resume_by_id(app.resume_id, user_id)

    # Compute missing fields
    missing = []
    res_content = app.resume.content if app.resume else master.content
    if not (res_content.full_name or "").strip():
        missing.append("Full name")
    if not res_content.email:
        missing.append("Email address")
    if not res_content.phone:
        missing.append("Phone number")
    if not res_content.education:
        missing.append("Education history")
    app.missing_fields = missing

    await log_application_event(app.id, "prepared", {"opportunity_id": opp.id})
    return app


@router.post("/applications/{opportunity_id:int}", response_model=CareerApplicationOut)
async def prepare_application_by_id_endpoint(opportunity_id: int, request: Request):
    """Path-based shortcut to prepare an application for an integer opportunity ID."""
    return await prepare_application_endpoint(request=request, opportunity_id=opportunity_id)


@router.get("/applications/{app_id}", response_model=CareerApplicationOut)
async def get_application_endpoint(app_id: int, request: Request):
    """Retrieve a single tracked application with opportunity and resume details, scoped to authenticated user."""
    user_id = _get_or_create_user_id(request)
    app = await get_career_application_by_id(app_id, user_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    opp = await get_opportunity_by_id(app.opportunity_id, user_id)
    resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
    app.opportunity = opp
    app.resume = resume
    return app


@router.post("/applications/{app_id}/cover-letter", response_model=CareerApplicationOut)
async def set_application_cover_letter_endpoint(app_id: int, body: SetCoverLetterRequest, request: Request):
    """Attach or update the cover letter for a career application."""
    user_id = _get_or_create_user_id(request)
    cover_letter = body.cover_letter
    app = await update_career_application(app_id, user_id, {"cover_letter": cover_letter})
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    opp = await get_opportunity_by_id(app.opportunity_id, user_id)
    resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
    app.opportunity = opp
    app.resume = resume
    await log_application_event(app.id, "cover_letter_attached", {"length": len(cover_letter)})
    return app


ALLOWED_STATUS_TRANSITIONS: Dict[str, Set[str]] = {
    CareerApplicationStatus.SAVED.value: {
        CareerApplicationStatus.PREPARING.value,
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.READY_FOR_APPROVAL.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    # Resume failed validation (e.g. missing name/email): the user fixes the profile, then moves on.
    CareerApplicationStatus.RESUME_VALIDATION_FAILED.value: {
        CareerApplicationStatus.SAVED.value,
        CareerApplicationStatus.PREPARING.value,
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.PREPARING.value: {
        CareerApplicationStatus.SAVED.value,
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.READY_FOR_APPROVAL.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.READY_FOR_REVIEW.value: {
        CareerApplicationStatus.PREPARING.value,
        CareerApplicationStatus.READY_FOR_APPROVAL.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.READY_FOR_APPROVAL.value: {
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value: {
        CareerApplicationStatus.READY_FOR_APPROVAL.value,
        CareerApplicationStatus.SUBMITTING.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.SUBMITTING.value: {
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.SUBMISSION_FAILED.value,
        CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value: {
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.SUBMISSION_FAILED.value,
        CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.SUBMISSION_FAILED.value: {
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.HANDOFF_KIT_READY.value: {
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value: {
        CareerApplicationStatus.HANDOFF_KIT_READY.value,
        CareerApplicationStatus.READY_FOR_REVIEW.value,
        CareerApplicationStatus.READY_FOR_APPROVAL.value,
        CareerApplicationStatus.SUBMITTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.SUBMITTED.value: {
        CareerApplicationStatus.ASSESSMENT_RECEIVED.value,
        CareerApplicationStatus.INTERVIEW.value,
        CareerApplicationStatus.OFFER_RECEIVED.value,
        CareerApplicationStatus.REJECTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.ASSESSMENT_RECEIVED.value: {
        CareerApplicationStatus.INTERVIEW.value,
        CareerApplicationStatus.OFFER_RECEIVED.value,
        CareerApplicationStatus.REJECTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.INTERVIEW.value: {
        CareerApplicationStatus.OFFER_RECEIVED.value,
        CareerApplicationStatus.REJECTED.value,
        CareerApplicationStatus.WITHDRAWN.value,
    },
    CareerApplicationStatus.OFFER_RECEIVED.value: {
        CareerApplicationStatus.CLOSED.value,
        CareerApplicationStatus.WITHDRAWN.value,
        CareerApplicationStatus.REJECTED.value,
    },
    CareerApplicationStatus.REJECTED.value: {
        CareerApplicationStatus.CLOSED.value,
    },
    CareerApplicationStatus.WITHDRAWN.value: {
        CareerApplicationStatus.CLOSED.value,
        CareerApplicationStatus.SAVED.value,
    },
}


# Statuses from which an application cannot be (re-)marked as submitted: it has already
# progressed beyond submission or been closed out.
_POST_SUBMISSION_STATUSES: Set[str] = {
    CareerApplicationStatus.ASSESSMENT_RECEIVED.value,
    CareerApplicationStatus.INTERVIEW.value,
    CareerApplicationStatus.OFFER_RECEIVED.value,
    CareerApplicationStatus.REJECTED.value,
    CareerApplicationStatus.WITHDRAWN.value,
    CareerApplicationStatus.CLOSED.value,
}


def _status_value(app: CareerApplicationOut) -> str:
    return app.status.value if hasattr(app.status, "value") else str(app.status)


def _is_already_submitted(app: CareerApplicationOut) -> bool:
    return _status_value(app) == CareerApplicationStatus.SUBMITTED.value


def _ensure_can_mark_submitted(app: CareerApplicationOut) -> None:
    """Reject marking SUBMITTED when the transition table forbids it for a progressed application."""
    curr_st = _status_value(app)
    allowed = ALLOWED_STATUS_TRANSITIONS.get(curr_st, set())
    if CareerApplicationStatus.SUBMITTED.value not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot mark application as submitted from status '{curr_st}'.",
        )


# Statuses at or before which a freshly attached resume may move an application to READY_FOR_REVIEW.
_PRE_REVIEW_STATUSES = {
    CareerApplicationStatus.SAVED,
    CareerApplicationStatus.DISCOVERED,
    CareerApplicationStatus.ELIGIBILITY_CHECKED,
    CareerApplicationStatus.PREPARING,
    CareerApplicationStatus.ELIGIBILITY_REVIEW,
    CareerApplicationStatus.NEEDS_INFORMATION,
    CareerApplicationStatus.RESUME_DRAFT,
    CareerApplicationStatus.RESUME_VALIDATION_FAILED,
}


# Statuses where swapping the attached resume is still meaningful (nothing sent yet).
_RESUME_RELINKABLE_STATUSES = {s.value for s in _PRE_REVIEW_STATUSES} | {
    CareerApplicationStatus.READY_FOR_REVIEW.value,
    CareerApplicationStatus.READY_FOR_APPROVAL.value,
    CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value,
    CareerApplicationStatus.HANDOFF_KIT_READY.value,
    CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value,
}


def _status_for_resume(app: CareerApplicationOut, val_status: ResumeValidationStatus) -> Optional[str]:
    """Status to set when a resume is attached to a pre-review application, else None (unchanged).

    A resume that failed validation must not make the application look ready: the existing
    RESUME_VALIDATION_FAILED status is used for it.
    """
    if app.status not in _PRE_REVIEW_STATUSES:
        return None
    if val_status == ResumeValidationStatus.READY_FOR_REVIEW:
        return CareerApplicationStatus.READY_FOR_REVIEW.value
    return CareerApplicationStatus.RESUME_VALIDATION_FAILED.value


@router.patch("/applications/{app_id}", response_model=CareerApplicationOut)
async def update_application_endpoint(app_id: int, body: UpdateApplicationStatusRequest, request: Request):
    """
    Update application status, answers, or private notes.
    Enforces allowed state transition rules and idempotent updates.
    """
    user_id = _get_or_create_user_id(request)
    existing_app = await get_career_application_by_id(app_id, user_id)
    if not existing_app:
        raise HTTPException(status_code=404, detail="Application not found")

    updates: Dict[str, Any] = {}

    if body.status:
        new_st = body.status.value
        curr_st = existing_app.status.value if hasattr(existing_app.status, "value") else str(existing_app.status)
        if new_st != curr_st:
            allowed = ALLOWED_STATUS_TRANSITIONS.get(curr_st, set())
            if new_st not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status transition from '{curr_st}' to '{new_st}'. Allowed transitions: {sorted(list(allowed))}.",
                )
            updates["status"] = new_st
            if (
                curr_st == CareerApplicationStatus.APPROVED_FOR_SUBMISSION.value
                and new_st == CareerApplicationStatus.READY_FOR_APPROVAL.value
            ):
                updates["approved_at"] = None  # approval revoked: clear the stale timestamp

            if new_st == CareerApplicationStatus.SUBMITTED.value:
                updates["submitted_at"] = datetime.now(timezone.utc)
                if (
                    body.target_deadline is None
                    and existing_app.target_deadline is None
                    and not body.clear_target_deadline
                ):
                    # 14-day follow-up reminder
                    updates["target_deadline"] = datetime.now(timezone.utc).date() + timedelta(days=14)

    if body.submission_method:
        updates["submission_method"] = body.submission_method.value
    if body.form_answers is not None:
        updates["form_answers"] = body.form_answers
    if body.clear_target_deadline and body.target_deadline is None:
        updates["target_deadline"] = None
    elif body.target_deadline is not None:
        updates["target_deadline"] = body.target_deadline
    if body.cover_letter is not None:
        updates["cover_letter"] = body.cover_letter
    if body.private_notes is not None:
        updates["private_notes"] = body.private_notes

    # Idempotent: If no updates required, return existing
    if not updates:
        opp = await get_opportunity_by_id(existing_app.opportunity_id, user_id)
        existing_app.opportunity = opp
        return existing_app

    app = await update_career_application(app_id, user_id, updates)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    opp = await get_opportunity_by_id(app.opportunity_id, user_id)
    app.opportunity = opp
    await log_application_event(app.id, "status_changed", updates)
    return app


@router.get("/applications/{app_id}/handoff-kit", response_model=HandoffKitOut)
async def get_application_handoff_kit_endpoint(app_id: int, request: Request):
    """
    Tenant-scoped Handoff Kit for direct portal submission.
    Read-only (never changes the application status).
    Extracts common answers strictly from the master profile (never guessed).
    Verifies tailored resume validity (blocks export if name/email are empty or placeholders).
    """
    user_id = _get_or_create_user_id(request)
    app = await get_career_application_by_id(app_id, user_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    opp = await get_opportunity_by_id(app.opportunity_id, user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    profile = await get_user_opportunity_profile(user_id)
    master = await get_master_resume(user_id)
    master_content = master.content if master else ResumeContent()

    # Read-only: opening the kit (a GET) never changes the application status.
    curr_st = _status_value(app)

    # Export validity of the application's OWN tailored resume (what the export endpoints check)
    is_blocked = False
    block_msg = None
    PLACEHOLDER_NAMES = {"compass candidate", "candidate", ""}
    PLACEHOLDER_EMAILS = {"candidate@compass.local", ""}

    app_resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
    if not app_resume:
        is_blocked = True
        block_msg = "Resume export blocked: no tailored resume is attached to this application yet."
    else:
        name = (app_resume.content.full_name or "").strip()
        email = (app_resume.content.email or "").strip()
        if not name or name.lower() in PLACEHOLDER_NAMES:
            is_blocked = True
            block_msg = "Resume export blocked: Candidate full name is empty or a placeholder. Complete your profile before downloading."
        elif not email or email.lower() in PLACEHOLDER_EMAILS or "@" not in email:
            is_blocked = True
            block_msg = "Resume export blocked: Candidate email is empty or a placeholder. Complete your profile before downloading."

    # Common answers generated strictly from profile (never guessed)
    common_answers: Dict[str, Optional[str]] = {}
    missing_fields: List[str] = []

    # Graduation year
    if profile and profile.grad_year:
        common_answers["graduation_year"] = str(profile.grad_year)
    else:
        common_answers["graduation_year"] = None
        missing_fields.append("graduation_year")

    # Degree
    if profile and profile.degree:
        common_answers["degree"] = profile.degree
    elif master_content.education and master_content.education[0].degree:
        common_answers["degree"] = master_content.education[0].degree
    else:
        common_answers["degree"] = None
        missing_fields.append("degree")

    # Links
    common_answers["linkedin_url"] = master_content.linkedin_url or None
    if not common_answers["linkedin_url"]:
        missing_fields.append("linkedin_url")

    common_answers["github_url"] = master_content.github_or_portfolio or None
    if not common_answers["github_url"]:
        missing_fields.append("github_url")

    common_answers["portfolio_url"] = profile.resume_url if profile and profile.resume_url else None
    if not common_answers["portfolio_url"]:
        missing_fields.append("portfolio_url")

    # Work Authorization
    form_answers = app.form_answers or {}
    declared_auth = str(form_answers.get("work_authorization") or "").strip()
    if declared_auth:
        common_answers["work_authorization"] = declared_auth
    elif profile and profile.work_authorization:
        common_answers["work_authorization"] = profile.work_authorization
    else:
        common_answers["work_authorization"] = None
        missing_fields.append("work_authorization")

    # Notice / Availability: only what the candidate stated; a work-arrangement preference is not availability.
    declared_availability = str(form_answers.get("availability") or form_answers.get("notice_or_availability") or "").strip()
    if declared_availability:
        common_answers["notice_or_availability"] = declared_availability
    else:
        common_answers["notice_or_availability"] = None
        missing_fields.append("notice_or_availability")
    if profile and profile.preferred_work_arrangements:
        common_answers["work_arrangement_preference"] = ", ".join(profile.preferred_work_arrangements)

    # Check for direct listing application email
    opp_desc = opp.description or ""
    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", opp_desc)
    app_email = email_match.group(0) if email_match else None

    events = await list_application_events(app.id)

    return HandoffKitOut(
        application_id=app.id,
        opportunity_id=opp.id,
        company_name=opp.company_name,
        role_title=opp.role_title,
        portal_url=opp.official_application_url or opp.canonical_url,
        application_email=app_email,
        status=app.status.value if hasattr(app.status, "value") else str(app.status),
        tailored_resume_id=app.resume_id,
        export_html_url=f"/api/career/resumes/{app.resume_id}/export/html" if app.resume_id else None,
        export_docx_url=f"/api/career/resumes/{app.resume_id}/export/docx" if app.resume_id else None,
        is_export_blocked=is_blocked,
        block_reason=block_msg,
        cover_letter=app.cover_letter,
        common_answers=common_answers,
        missing_profile_fields=missing_fields,
        checklist={
            "resume_attached": bool(app.resume_id and not is_blocked),
            # Only an explicit user confirmation counts; merely having a draft is not a review.
            "cover_letter_reviewed": bool(form_answers.get("cover_letter_reviewed")),
            "questions_answered": len(missing_fields) == 0,
            "submitted_on_portal": curr_st == CareerApplicationStatus.SUBMITTED.value,
        },
        timeline=[
            {
                "event_type": e.get("event_type", "event"),
                "timestamp": e.get("created_at", datetime.now(timezone.utc)).isoformat() if hasattr(e.get("created_at"), "isoformat") else str(e.get("created_at")),
                "payload": e.get("payload", {}),
            }
            for e in events[:10]
        ],
        follow_up_reminder_days=14,
    )


@router.post("/applications/{app_id}/mark-applied", response_model=CareerApplicationOut)
async def mark_application_applied_endpoint(app_id: int, request: Request):
    """
    Explicit user confirmation that the application was submitted on the external portal.
    NEVER set automatically. Schedules a 14-day follow-up reminder and logs timeline event.
    """
    user_id = _get_or_create_user_id(request)
    app = await get_career_application_by_id(app_id, user_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    opp = await get_opportunity_by_id(app.opportunity_id, user_id)
    if _is_already_submitted(app):
        app.opportunity = opp
        return app
    _ensure_can_mark_submitted(app)

    now = datetime.now(timezone.utc)
    # Keep a deadline the user already set; only fill the follow-up reminder when empty.
    follow_up = app.target_deadline or now.date() + timedelta(days=14)

    updated = await update_career_application(app_id, user_id, {
        "status": CareerApplicationStatus.SUBMITTED.value,
        "submitted_at": now,
        "target_deadline": follow_up,
    })
    await log_application_event(app.id, "applied_confirmed_by_user", {
        "submitted_at": now.isoformat(),
        "follow_up_reminder": str(follow_up),
    })

    updated.opportunity = opp
    return updated


@router.post("/skills/add")
async def add_skill_deliberate_endpoint(body: AddSkillRequest, request: Request):
    """
    Deliberate candidate action to add a skill:
    - If verified: Requires an explicit evidence note or URL.
    - If learning: Added to candidate's learning skills list (never exported on resumes).
    """
    user_id = _get_or_create_user_id(request)
    skill_clean = body.skill.strip()
    if not skill_clean:
        raise HTTPException(status_code=400, detail="Skill name is required.")

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id) or UserOpportunityProfileIn()
        master = await upsert_master_resume(user_id, _build_initial_master_content(profile, request), "Master Resume")

    content = master.content
    existing_skill = next((s for s in content.skills if s.lower() == skill_clean.lower()), None)
    existing_learning = next((s for s in content.learning_skills if s.lower() == skill_clean.lower()), None)
    if body.category == "verified":
        if not (body.evidence_note or "").strip() and not (body.evidence_url or "").strip():
            raise HTTPException(
                status_code=400,
                detail="Verified skills require evidence: please provide an evidence note or link demonstrating implementation.",
            )
        canonical = existing_skill or skill_clean
        changed = existing_skill is None or existing_learning is not None
        if existing_skill is None:
            content.skills.append(canonical)
        if body.evidence_note and body.evidence_note.strip():
            note = body.evidence_note.strip()
            changed = changed or content.evidence_notes.get(canonical) != note
            content.evidence_notes[canonical] = note
        if body.evidence_url and body.evidence_url.strip():
            link = f"{canonical}: {body.evidence_url.strip()}"
            if link not in content.relevant_links:
                content.relevant_links.append(link)
                changed = True
        # Remove from learning list if present (a verified add upgrades it)
        content.learning_skills = [s for s in content.learning_skills if s.lower() != skill_clean.lower()]
        if changed:
            await update_resume(master.id, user_id, {"content": content.model_dump()})
        return {
            "status": "added_verified",
            "skill": skill_clean,
            "category": "verified",
            "message": f"Skill '{skill_clean}' added to verified profile with supporting evidence.",
        }
    else:
        # Category learning: saved separately, never exported to resume
        if existing_learning is None and existing_skill is None:
            content.learning_skills.append(skill_clean)
            await update_resume(master.id, user_id, {"content": content.model_dump()})
        return {
            "status": "added_learning",
            "skill": skill_clean,
            "category": "learning",
            "message": f"Skill '{skill_clean}' added to 'Skills I'm learning'. This is omitted from resume exports.",
        }


@router.post("/auto-prepare")
async def trigger_auto_prepare_endpoint(request: Request):
    """
    Opt-in, cost-guarded auto-prepare endpoint.
    Processes at most 3 watchlisted opportunities with ELIGIBLE status for candidates with complete profiles.
    Returns 429 if daily limit exceeded.
    """
    user_id = _get_or_create_user_id(request)
    result = await execute_auto_prepare_for_user(user_id)
    if result.get("status") == "rate_limited":
        retry_after = result.get("retry_after", 86400)
        raise HTTPException(
            status_code=429,
            detail=result.get("message", "Daily auto-prepare rate limit exceeded."),
            headers={"Retry-After": str(retry_after)},
        )
    return result


@router.get("/auto-prepare/status")
async def get_auto_prepare_status_endpoint(request: Request):
    """Inspect daily auto-prepare quota usage, remaining drafts, and cooldown countdown."""
    user_id = _get_or_create_user_id(request)
    return get_user_quota_status(user_id)



# ===========================================================================
# 3. Batch Review & Explicit Approval
# ===========================================================================

@router.post("/applications/batch/prepare", response_model=BatchReviewOut)
@router.post("/batches/prepare", response_model=BatchReviewOut)
async def prepare_batch_endpoint(body: BatchPrepareRequest, request: Request):
    """Freeze a batch of applications for user review."""
    user_id = _get_or_create_user_id(request)
    if not body.opportunity_ids:
        raise HTTPException(status_code=400, detail="At least one opportunity is required for a batch")

    from backend.memory.career import get_or_create_career_application
    opps_by_id = {}
    for opp_id in body.opportunity_ids:
        found = await get_opportunity_by_id(opp_id, user_id)
        if not found:
            raise HTTPException(status_code=404, detail=f"Opportunity {opp_id} not found")
        opps_by_id[opp_id] = found

    app_ids = []
    apps_list = []
    for opp_id in body.opportunity_ids:
        app = await get_or_create_career_application(user_id, opp_id)
        opp = opps_by_id[opp_id]
        resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
        app.opportunity = opp
        app.resume = resume
        app_ids.append(app.id)
        apps_list.append(app)

    batch_id = await create_application_batch(user_id, app_ids)
    ready = sum(1 for a in apps_list if a.status in {CareerApplicationStatus.READY_FOR_REVIEW, CareerApplicationStatus.READY_FOR_APPROVAL})

    from datetime import datetime, timezone
    return BatchReviewOut(
        batch_id=batch_id,
        applications=apps_list,
        total_count=len(apps_list),
        ready_count=ready,
        blocked_count=len(apps_list) - ready,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/applications/batch/{batch_id}", response_model=BatchReviewOut)
@router.get("/batches/{batch_id}", response_model=BatchReviewOut)
async def get_batch_endpoint(batch_id: str, request: Request):
    """Retrieve frozen batch details."""
    user_id = _get_or_create_user_id(request)
    batch = await get_application_batch(batch_id, user_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    apps_list = []
    for aid in batch.get("application_ids", []):
        app = await get_career_application_by_id(aid, user_id)
        if app:
            opp = await get_opportunity_by_id(app.opportunity_id, user_id)
            resume = await get_resume_by_id(app.resume_id, user_id) if app.resume_id else None
            app.opportunity = opp
            app.resume = resume
            apps_list.append(app)

    ready = sum(1 for a in apps_list if a.status in {CareerApplicationStatus.READY_FOR_REVIEW, CareerApplicationStatus.READY_FOR_APPROVAL, CareerApplicationStatus.APPROVED_FOR_SUBMISSION})
    return BatchReviewOut(
        batch_id=batch_id,
        applications=apps_list,
        total_count=len(apps_list),
        ready_count=ready,
        blocked_count=len(apps_list) - ready,
        status=batch.get("status", "DRAFT"),
        approval_token=batch.get("approval_token"),
        is_persisted=batch.get("is_persisted", True),
        created_at=batch["created_at"],
    )


@router.post("/applications/batch/{batch_id}/approve")
@router.post("/batches/{batch_id}/approve")
async def approve_batch_endpoint(batch_id: str, body: BatchApproveRequest, request: Request):
    """
    Explicit user approval gate.
    Requires confirmed attestations. Generates a signed, content-bound approval token.
    """
    user_id = _get_or_create_user_id(request)
    batch = await get_application_batch(batch_id, user_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found or unauthorized")

    if batch.get("status") not in APPROVABLE_BATCH_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Batch cannot be approved from status '{batch.get('status')}'.",
        )

    if not body.attestation_confirmed or not body.work_auth_confirmed or not body.legal_statements_accepted:
        raise HTTPException(
            status_code=400,
            detail="Explicit user confirmation of accuracy, work authorization, and legal acceptance is strictly required before submission approval.",
        )

    # Readiness gate: every application needs a validated resume and a cover letter.
    not_ready = await find_batch_not_ready(user_id, batch.get("application_ids", []))
    if not_ready:
        raise HTTPException(
            status_code=409,
            # The app-wide handler flattens a dict detail into the response body.
            detail={
                "detail": "Batch cannot be approved; not ready: " + "; ".join(
                    f"application {p['application_id']}: {' '.join(p['reasons'])}" for p in not_ready
                ),
                "not_ready": not_ready,
            },
        )

    # Compute current reviewed content hash (includes each resume's version stamp)
    apps_data = await load_batch_apps_data(user_id, batch.get("application_ids", []))
    content_hash = compute_batch_content_hash(apps_data)

    approval_token = generate_batch_approval_token(
        user_id=user_id,
        batch_id=batch_id,
        application_ids=batch.get("application_ids", []),
        content_hash=content_hash,
        expires_in_seconds=3600,
    )

    ok = await approve_application_batch(batch_id, user_id, approval_token)
    if not ok:
        # Batch existed above; it changed state concurrently and is no longer approvable.
        raise HTTPException(status_code=409, detail="Batch is no longer in an approvable state.")

    return {
        "status": "APPROVED",
        "batch_id": batch_id,
        "approval_token": approval_token,
        "message": "Batch successfully approved for submission.",
    }


@router.post("/applications/batch/{batch_id}/submit", response_model=BatchSubmitResultOut)
@router.post("/batches/{batch_id}/submit", response_model=BatchSubmitResultOut)
async def submit_batch_endpoint(batch_id: str, body: BatchSubmitRequest, request: Request):
    """
    Executes submission across the approved batch using supported adapters.
    Guarantees no unapproved, modified, or duplicate applications are processed.
    """
    user_id = _get_or_create_user_id(request)
    batch = await get_application_batch(batch_id, user_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.get("status") in {"SUBMITTED", "MANUAL_HANDOFF_GENERATED", "COMPLETED"}:
        raise HTTPException(
            status_code=409,
            detail="Duplicate submission rejected: This batch has already been processed.",
        )
    if batch.get("status") == "SUBMITTING":
        raise HTTPException(
            status_code=409,
            detail="Concurrent submission rejected: This batch is currently processing.",
        )
    if batch.get("status") != "APPROVED":
        raise HTTPException(
            status_code=403,
            detail="Batch submission rejected: Batch has not passed explicit user approval or was invalidated by content changes.",
        )

    lock = get_batch_lock(batch_id)
    if lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Concurrent submission rejected: A submission is already running for this batch.",
        )

    async with lock:
        # Atomic database-backed claim across multiple server processes / workers
        from backend.memory.career import (
            claim_application_batch_for_submission,
            release_application_batch_claim,
            update_application_batch_status,
        )
        claimed = await claim_application_batch_for_submission(batch_id, user_id)
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail="Concurrent submission rejected: This batch is currently processing or is no longer in APPROVED status.",
            )

        try:
            # Content integrity and token verification
            apps_data = await load_batch_apps_data(user_id, batch.get("application_ids", []))
            current_content_hash = compute_batch_content_hash(apps_data)

            stored_token = batch.get("approval_token")
            token_to_verify = body.approval_token or stored_token

            if not token_to_verify:
                await release_application_batch_claim(batch_id, user_id, "APPROVED")
                raise HTTPException(
                    status_code=403,
                    detail="Submission blocked: Missing approval token. Batch must be re-approved.",
                )

            is_valid, reason = verify_batch_approval_token(token_to_verify, user_id, batch_id, current_content_hash)
            if not is_valid:
                await release_application_batch_claim(batch_id, user_id, "APPROVED")
                raise HTTPException(
                    status_code=403,
                    detail=f"Submission blocked: {reason}",
                )

            results = await execute_batch_submission(user_id, batch, body.preferred_method)
            await finish_application_batch(batch_id, user_id, [r.model_dump() for r in results])
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Unhandled error executing batch submission %s: %s", batch_id, e)
            await finish_application_batch(batch_id, user_id, [{
                "application_id": 0,
                "status": "FAILED",
                "message": "Submission execution failed unexpectedly.",
            }])
            raise HTTPException(status_code=500, detail="Submission execution failed. Please try again later.")

    success_cnt = sum(1 for r in results if r.status in {"SUBMITTED", "APPROVED"})
    manual_cnt = sum(1 for r in results if r.status == CareerApplicationStatus.MANUAL_SUBMISSION_REQUIRED.value)
    fail_cnt = sum(1 for r in results if r.status in {"FAILED", "BLOCKED", CareerApplicationStatus.SUBMISSION_FAILED.value})
    uncertain_cnt = sum(1 for r in results if r.status == CareerApplicationStatus.SUBMISSION_OUTCOME_UNKNOWN.value)

    return BatchSubmitResultOut(
        batch_id=batch_id,
        total_processed=len(results),
        successful_count=success_cnt,
        manual_count=manual_cnt,
        failed_count=fail_cnt,
        uncertain_count=uncertain_cnt,
        results=results,
    )


# ===========================================================================
# 4. Adapters & Capabilities
# ===========================================================================

@router.get("/adapters", response_model=List[SubmissionAdapterCapability])
async def list_adapters_endpoint():
    """List available submission adapters with their capability declarations."""
    return SUPPORTED_ADAPTERS
