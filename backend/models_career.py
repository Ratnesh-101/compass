"""
Compass — Career Copilot Domain Models.

Defines schemas for Resume Studio (master resumes, tailored variants, factual validation)
and Application Center (application states, batch review, explicit approval, submission results).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator

from backend.models_radar import OpportunityOut


class ResumeValidationStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"


class CareerApplicationStatus(str, Enum):
    SAVED = "SAVED"
    DISCOVERED = "DISCOVERED"
    ELIGIBILITY_CHECKED = "ELIGIBILITY_CHECKED"
    PREPARING = "PREPARING"
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    RESUME_DRAFT = "RESUME_DRAFT"
    RESUME_VALIDATION_FAILED = "RESUME_VALIDATION_FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED_FOR_SUBMISSION = "APPROVED_FOR_SUBMISSION"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    SUBMISSION_FAILED = "SUBMISSION_FAILED"
    SUBMISSION_OUTCOME_UNKNOWN = "SUBMISSION_OUTCOME_UNKNOWN"
    MANUAL_SUBMISSION_REQUIRED = "MANUAL_SUBMISSION_REQUIRED"
    HANDOFF_KIT_READY = "HANDOFF_KIT_READY"
    ASSESSMENT_RECEIVED = "ASSESSMENT_RECEIVED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class SubmissionMethod(str, Enum):
    OFFICIAL_API = "official_api"
    ATS_ENDPOINT = "ats_endpoint"
    BROWSER_ASSISTED = "browser_assisted"
    MANUAL_HANDOFF = "manual_handoff"


class EvidenceClassification(str, Enum):
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    REPOSITORY_EVIDENCE = "REPOSITORY_EVIDENCE"
    OFFICIAL_API_DATA = "OFFICIAL_API_DATA"
    USER_CONFIRMED = "USER_CONFIRMED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    CONFLICTING_INFORMATION = "CONFLICTING_INFORMATION"


class ResumeEducationItem(BaseModel):
    institution: str
    degree: str
    field_of_study: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    cgpa_or_grade: Optional[str] = None
    evidence_classification: Optional[EvidenceClassification] = None


class ResumeProjectItem(BaseModel):
    title: str
    description: str
    technologies: List[str] = Field(default_factory=list)
    project_url: Optional[str] = None
    repo_url: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)
    evidence_classification: Optional[EvidenceClassification] = None
    evidence_details: Optional[Dict[str, Any]] = None


class ResumeExperienceItem(BaseModel):
    company: str
    role_title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: bool = False
    highlights: List[str] = Field(default_factory=list)
    evidence_classification: Optional[EvidenceClassification] = None


class ResumeContent(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: Optional[str] = None
    location: Optional[str] = None
    github_or_portfolio: Optional[str] = None
    linkedin_url: Optional[str] = None
    summary: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    education: List[ResumeEducationItem] = Field(default_factory=list)
    projects: List[ResumeProjectItem] = Field(default_factory=list)
    experience: List[ResumeExperienceItem] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    # Expanded Phase 1 sections
    internships: List[ResumeExperienceItem] = Field(default_factory=list)
    awards: List[str] = Field(default_factory=list)
    hackathons: List[str] = Field(default_factory=list)
    leadership_and_volunteering: List[str] = Field(default_factory=list)
    publications: List[str] = Field(default_factory=list)
    relevant_links: List[str] = Field(default_factory=list)
    evidence_classifications: Dict[str, str] = Field(default_factory=dict)
    evidence_notes: Dict[str, str] = Field(default_factory=dict)
    learning_skills: List[str] = Field(default_factory=list)


class OriginalResumeDocument(BaseModel):
    id: str
    user_id: str
    filename: str
    file_type: str
    raw_text: str
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResumeValidationReport(BaseModel):
    is_valid: bool = True
    status: str = "CONSISTENT WITH MASTER"
    passed_checks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    tailored_alignments: List[str] = Field(default_factory=list)
    diff_summary: Dict[str, Any] = Field(default_factory=dict)


class ResumeOut(BaseModel):
    id: int
    user_id: str
    opportunity_id: Optional[int] = None
    is_master: bool = False
    title: str
    version: int = 1
    content: ResumeContent
    cover_letter: Optional[str] = None
    validation_status: ResumeValidationStatus = ResumeValidationStatus.DRAFT
    validation_report: ResumeValidationReport = Field(default_factory=ResumeValidationReport)
    is_persisted: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TailorResumeRequest(BaseModel):
    opportunity_id: int
    custom_title: Optional[str] = None
    target_skills_emphasis: Optional[List[str]] = None
    # When set, the new tailored resume is also linked to this (owner-scoped) application.
    application_id: Optional[int] = None


class SaveResumeRequest(BaseModel):
    title: str
    content: ResumeContent
    cover_letter: Optional[str] = None
    opportunity_id: Optional[int] = None
    is_master: bool = False


class ResumeParseUploadRequest(BaseModel):
    raw_text: str = Field(max_length=200000)


class ResumeParseUploadOut(ResumeContent):
    """Parsed resume content plus additive extraction diagnostics."""
    missing_fields: List[str] = Field(default_factory=list)
    ambiguous_fields: List[str] = Field(default_factory=list)
    field_confidence: Dict[str, float] = Field(default_factory=dict)
    overall_confidence: Optional[float] = None


class CoverLetterOut(BaseModel):
    id: Optional[int] = None
    opportunity_id: int
    company_name: str
    role_title: str
    content: str
    verified_projects_referenced: List[str] = Field(default_factory=list)
    verified_skills_referenced: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class DraftCoverLetterRequest(BaseModel):
    opportunity_id: int
    emphasis_projects: Optional[List[str]] = None
    tone: Optional[str] = "professional"


class CareerApplicationOut(BaseModel):
    id: int
    user_id: str
    opportunity_id: int
    opportunity: Optional[OpportunityOut] = None
    resume_id: Optional[int] = None
    resume: Optional[ResumeOut] = None
    cover_letter: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    status: CareerApplicationStatus = CareerApplicationStatus.SAVED
    submission_method: SubmissionMethod = SubmissionMethod.MANUAL_HANDOFF
    form_answers: Dict[str, Any] = Field(default_factory=dict)
    submission_payload: Dict[str, Any] = Field(default_factory=dict)
    submission_result: Dict[str, Any] = Field(default_factory=dict)
    batch_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    target_deadline: Optional[date] = None
    private_notes: Optional[str] = None
    is_persisted: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UpdateApplicationStatusRequest(BaseModel):
    status: Optional[CareerApplicationStatus] = None
    submission_method: Optional[SubmissionMethod] = None
    form_answers: Optional[Dict[str, Any]] = None
    cover_letter: Optional[str] = Field(default=None, max_length=50000)
    target_deadline: Optional[date] = None
    # Explicitly clear the deadline (omitting target_deadline leaves it unchanged).
    clear_target_deadline: bool = False
    private_notes: Optional[str] = Field(default=None, max_length=20000)

    @field_validator("form_answers")
    @classmethod
    def cap_form_answers(cls, v: Any) -> Any:
        if v is not None and len(json.dumps(v, default=str)) > 100000:
            raise ValueError("form_answers is too large")
        return v

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> Any:
        if isinstance(v, str):
            val_upper = v.upper()
            try:
                return CareerApplicationStatus(val_upper)
            except ValueError:
                return v
        return v


MAX_BATCH_OPPORTUNITIES = 50
MAX_COVER_LETTER_CHARS = 20000


class BatchPrepareRequest(BaseModel):
    opportunity_ids: List[int] = Field(max_length=MAX_BATCH_OPPORTUNITIES)

    @field_validator("opportunity_ids")
    @classmethod
    def _dedupe_opportunity_ids(cls, v: List[int]) -> List[int]:
        return list(dict.fromkeys(v))


class SetCoverLetterRequest(BaseModel):
    cover_letter: str = Field(max_length=MAX_COVER_LETTER_CHARS)


class BatchReviewOut(BaseModel):
    batch_id: str
    applications: List[CareerApplicationOut]
    total_count: int
    ready_count: int
    blocked_count: int
    status: str = "DRAFT"
    approval_token: Optional[str] = None
    is_persisted: bool = True
    created_at: datetime


class BatchApproveRequest(BaseModel):
    batch_id: str
    attestation_confirmed: bool = False
    work_auth_confirmed: bool = False
    legal_statements_accepted: bool = False


class BatchSubmitRequest(BaseModel):
    batch_id: str
    preferred_method: Optional[SubmissionMethod] = None
    approval_token: Optional[str] = None


class SubmissionResultItem(BaseModel):
    application_id: int
    company_name: str
    role_title: str
    status: str
    submission_method: str
    reference_id: Optional[str] = None
    message: str
    manual_package: Optional[Dict[str, Any]] = None


class BatchSubmitResultOut(BaseModel):
    batch_id: str
    total_processed: int
    successful_count: int
    manual_count: int
    failed_count: int
    uncertain_count: int = 0
    results: List[SubmissionResultItem]


class SubmissionAdapterCapability(BaseModel):
    adapter_id: str
    display_name: str
    description: str
    is_automated: bool
    requires_credentials: bool
    is_configured: bool
    supported_platforms: List[str]


# ===========================================================================
# GitHub Profile Intelligence Models (Phase 2)
# ===========================================================================

class GitHubRepoEvidence(BaseModel):
    repo_name: str
    repo_url: str
    owner: str
    is_fork: bool
    is_owned: bool
    description: Optional[str] = None
    primary_language: Optional[str] = None
    detected_technologies: List[str] = Field(default_factory=list)
    # None means unknown (the check could not be completed, e.g. rate limited or fork)
    has_tests: Optional[bool] = False
    has_ci_cd: Optional[bool] = False
    has_documentation: bool = False
    commit_count_estimate: Optional[int] = None
    analysis_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    limitations: List[str] = Field(default_factory=list)
    implementation_evidence: List[str] = Field(default_factory=list)


class GitHubProfileIntelligence(BaseModel):
    username: str
    profile_url: str
    total_public_repos: int
    analyzed_repos: List[GitHubRepoEvidence] = Field(default_factory=list)
    detected_skills: List[str] = Field(default_factory=list)
    evidence_summary: str = ""
    warnings: List[str] = Field(default_factory=list)
    # "ok" | "partial" | "failed" (additive; failed means nothing could be analyzed)
    status: str = "ok"


class GitHubImportRequest(BaseModel):
    username_or_url: str
    personal_access_token: Optional[str] = None
    excluded_repos: List[str] = Field(default_factory=list)


# ===========================================================================
# LinkedIn and External Profile Models (Phase 3)
# ===========================================================================

class ExternalProfileSource(str, Enum):
    LINKEDIN_DATA_EXPORT = "LINKEDIN_DATA_EXPORT"
    LINKEDIN_PASTED_TEXT = "LINKEDIN_PASTED_TEXT"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    PORTFOLIO_SITE = "PORTFOLIO_SITE"
    OFFICIAL_API = "OFFICIAL_API"


def safe_http_url(value: Optional[str]) -> Optional[str]:
    """Return the stripped URL when it is a well-formed http(s) URL with a host, else None."""
    if not value:
        return None
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None
    return candidate


class ExternalProfileImportRequest(BaseModel):
    source_type: ExternalProfileSource
    raw_content: str = Field(max_length=200000)
    source_url: Optional[str] = None

    @field_validator("source_url")
    @classmethod
    def _source_url_must_be_http(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        safe = safe_http_url(value)
        if safe is None:
            raise ValueError("source_url must be a valid http:// or https:// URL")
        return safe


# ===========================================================================
# Job Description Analysis & Matching Models (Phase 5)
# ===========================================================================

class JobMatchEvidence(BaseModel):
    requirement: str
    category: str = "skill"  # skill, qualification, responsibility, eligibility
    is_mandatory: bool = True
    match_status: str = "supported"  # supported, partial, missing_evidence, gap
    supporting_facts: List[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: float = 1.0


class JobAnalysisRequest(BaseModel):
    custom_description: Optional[str] = Field(None, max_length=20000)


class JobAnalysisReport(BaseModel):
    opportunity_id: int
    role_title: str
    company_name: str
    mandatory_qualifications: List[str] = Field(default_factory=list)
    preferred_qualifications: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    location_and_eligibility: Dict[str, Any] = Field(default_factory=dict)
    matches: List[JobMatchEvidence] = Field(default_factory=list)
    match_score: float = 0.0
    summary_verdict: str = ""
    missing_critical_skills: List[str] = Field(default_factory=list)
    # Honest Gap Analysis ("Path to 100%") fields
    skill_overlap_estimate: float = 0.0
    matched_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    partial_skills: List[str] = Field(default_factory=list)
    gap_actions: List[Dict[str, Any]] = Field(default_factory=list)
    has_complete_profile: bool = True
    # False when the posting lists no recognisable skills (match_score is then not meaningful)
    score_available: bool = True
    profile_missing_message: Optional[str] = None
    formula_explanation: str = "Skill overlap estimate = (matched + 0.5 * partial) / total required skills"


class CommitExtractedResumeRequest(BaseModel):
    content: ResumeContent
    original_document_id: Optional[str] = None
    resolved_conflicts: Optional[Dict[str, Any]] = None
    target: str = "master"  # "master" or "new_draft"


class HandoffKitOut(BaseModel):
    application_id: int
    opportunity_id: int
    company_name: str
    role_title: str
    portal_url: Optional[str] = None
    application_email: Optional[str] = None
    status: str
    tailored_resume_id: Optional[int] = None
    export_html_url: Optional[str] = None
    export_docx_url: Optional[str] = None
    is_export_blocked: bool = False
    block_reason: Optional[str] = None
    cover_letter: Optional[str] = None
    common_answers: Dict[str, Optional[str]] = Field(default_factory=dict)
    missing_profile_fields: List[str] = Field(default_factory=list)
    checklist: Dict[str, bool] = Field(default_factory=dict)
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
    follow_up_reminder_days: int = 14


class AddSkillRequest(BaseModel):
    skill: str = Field(max_length=200)
    category: str = Field(default="verified", max_length=20)  # "verified" or "learning"
    evidence_note: Optional[str] = Field(default=None, max_length=5000)
    evidence_url: Optional[str] = Field(default=None, max_length=2000)


