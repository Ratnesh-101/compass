"""
Compass — Internship Radar Domain Models.

Strongly typed Pydantic schemas for opportunities, provenance sources,
eligibility requirements, historical recruitment cycles, user profiles, and application tracking.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums and Constants
# ---------------------------------------------------------------------------

class OpportunityStatus:
    DISCOVERED = "DISCOVERED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    ANNOUNCED = "ANNOUNCED"
    UPCOMING_CONFIRMED = "UPCOMING_CONFIRMED"
    OPEN_CONFIRMED = "OPEN_CONFIRMED"
    CLOSED_CONFIRMED = "CLOSED_CONFIRMED"
    CANCELLED_CONFIRMED = "CANCELLED_CONFIRMED"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"

    ALL = {
        DISCOVERED,
        NEEDS_VERIFICATION,
        ANNOUNCED,
        UPCOMING_CONFIRMED,
        OPEN_CONFIRMED,
        CLOSED_CONFIRMED,
        CANCELLED_CONFIRMED,
        STATUS_UNKNOWN,
    }


class EmployerType:
    STARTUP = "startup"
    RESEARCH = "research"
    GOVERNMENT = "government"
    SME = "sme"
    OPEN_SOURCE = "open_source"
    ENTERPRISE = "enterprise"

    ALL = {
        STARTUP,
        RESEARCH,
        GOVERNMENT,
        SME,
        OPEN_SOURCE,
        ENTERPRISE,
    }


class ApplicationStatus:
    INTERESTED = "interested"
    PREPARING = "preparing"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"
    ASSESSMENT_PENDING = "assessment_pending"
    INTERVIEWING = "interviewing"
    OFFER_RECEIVED = "offer_received"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CLOSED_WITHOUT_APPLYING = "closed_without_applying"

    ALL = {
        INTERESTED,
        PREPARING,
        READY_TO_APPLY,
        APPLIED,
        ASSESSMENT_PENDING,
        INTERVIEWING,
        OFFER_RECEIVED,
        REJECTED,
        WITHDRAWN,
        CLOSED_WITHOUT_APPLYING,
    }


class EligibilityClassification:
    ELIGIBLE = "ELIGIBLE"
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    POTENTIALLY_ELIGIBLE = "POTENTIAL_MATCH"  # Canonical alias for compatibility
    INELIGIBLE = "INELIGIBLE"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"


class ConfidenceLevel:
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    UNKNOWN = "Unknown"


# ---------------------------------------------------------------------------
# Opportunity Models
# ---------------------------------------------------------------------------

class OpportunityRequirementsOut(BaseModel):
    eligible_degree_types: List[str] = Field(default_factory=list)
    eligible_academic_years: List[int] = Field(default_factory=list)
    eligible_graduation_years: List[int] = Field(default_factory=list)
    eligible_countries: List[str] = Field(default_factory=list)
    work_auth_required: Optional[bool] = None
    sponsorship_available: Optional[bool] = None
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    min_gpa: Optional[float] = None
    gpa_scale: Optional[float] = 10.0
    no_active_backlogs: Optional[bool] = None
    has_conflicting_requirements: bool = False
    other_mandatory_requirements: Optional[str] = None
    unknown_requirements: List[str] = Field(default_factory=list)


class OpportunityCycleOut(BaseModel):
    id: Optional[int] = None
    cycle_year: int
    observed_open_date: Optional[date] = None
    observed_close_date: Optional[date] = None
    date_precision: str = "day"
    verification_status: str = "verified"
    observation_type: str = "confirmed"
    notes: Optional[str] = None


class OpportunityPredictionOut(BaseModel):
    estimated_open_window: Optional[str] = None
    estimated_open_month: Optional[str] = None
    confidence: str = ConfidenceLevel.UNKNOWN
    evidence_basis: str
    verified_cycles_count: int = 0
    last_observed_cycle: Optional[int] = None


class OpportunitySourceOut(BaseModel):
    id: Optional[int] = None
    source_name: str
    source_type: str
    source_url: str
    source_authority: str = "tier_2"
    discovered_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    verification_result: Optional[str] = None
    is_official_source: bool = False


class OpportunityOut(BaseModel):
    id: int
    company_name: str
    normalized_company: str
    role_title: str
    employer_type: Optional[str] = None  # startup, research, government, sme, open_source, enterprise, or None if unverified
    opportunity_type: str = "internship"  # internship, fellowship, research, externship, co-op
    category: Optional[str] = None  # ai_ml, swe, backend, data, research, cloud, open_source, general
    location: Optional[str] = None
    work_arrangement: Optional[str] = None  # remote, onsite, hybrid, unknown
    country: str = "India"
    is_india_eligible: bool = True
    compensation: Optional[str] = None
    duration: Optional[str] = None
    official_application_url: Optional[str] = None
    canonical_url: str
    current_status: str
    confirmed_open_date: Optional[date] = None
    confirmed_close_date: Optional[date] = None
    description: Optional[str] = None
    last_verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator(
        "location",
        "compensation",
        "duration",
        "work_arrangement",
        "category",
        "official_application_url",
        "description",
        "employer_type",
        "verification_evidence",
        mode="before",
    )
    @classmethod
    def sanitize_optional_strings(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        v_str = str(v).strip()
        if not v_str or v_str.lower() in ("nan", "none", "null", "undefined", "n/a"):
            return None
        return v_str

    @field_validator("company_name", "role_title", mode="before")
    @classmethod
    def sanitize_required_strings(cls, v: Any) -> str:
        if v is None:
            return ""
        v_str = str(v).strip()
        if v_str.lower() in ("nan", "none", "null", "undefined"):
            return ""
        return v_str

    # Evidence-based verification metadata
    verification_evidence: Optional[str] = None
    employer_identity_verified: bool = False
    official_source_confirmed: bool = False
    application_url_checked: bool = False
    posted_at: Optional[datetime] = None
    posted_at_precision: Optional[str] = None
    is_verified_within_24h: bool = False

    # Nested related domain data
    requirements: Optional[OpportunityRequirementsOut] = None
    sources: List[OpportunitySourceOut] = Field(default_factory=list)
    cycles: List[OpportunityCycleOut] = Field(default_factory=list)
    prediction: Optional[OpportunityPredictionOut] = None

    # User-specific contextual state (if authenticated/tracked)
    is_saved: bool = False
    is_dismissed: bool = False
    application_status: Optional[str] = None
    application_date: Optional[date] = None
    personal_deadline: Optional[date] = None
    private_notes: Optional[str] = None
    eligibility_classification: str = EligibilityClassification.INSUFFICIENT_INFORMATION
    eligibility_explanation: Optional[str] = None
    eligibility_reasons: List[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# User Profile & Tracking Models
# ---------------------------------------------------------------------------

class UserOpportunityProfileIn(BaseModel):
    degree: Optional[str] = None
    degree_specialization: Optional[str] = None
    university: Optional[str] = None
    academic_year: Optional[int] = Field(None, ge=1, le=5)  # 1..5
    grad_month: Optional[int] = Field(6, ge=1, le=12)
    grad_year: Optional[int] = None
    cgpa: Optional[float] = Field(None, ge=0.0, le=100.0)
    cgpa_scale: Optional[float] = Field(10.0, ge=4.0, le=100.0)
    active_backlogs: Optional[int] = Field(0, ge=0)
    work_authorization: Optional[str] = Field("India", description="Jurisdictions authorized to work without sponsorship")
    requires_sponsorship: Optional[bool] = False
    country_of_study: str = "India"
    country_of_residence: str = "India"
    preferred_locations: List[str] = Field(default_factory=lambda: ["India", "Remote"])
    preferred_work_arrangements: List[str] = Field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    preferred_roles: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    min_compensation: Optional[str] = None
    resume_url: Optional[str] = None


class UserOpportunityProfileOut(UserOpportunityProfileIn):
    user_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    missing_fields_limiting_eligibility: List[str] = Field(default_factory=list)


class UpdateApplicationStatusIn(BaseModel):
    application_status: str
    application_date: Optional[date] = None
    personal_deadline: Optional[date] = None
    interview_date: Optional[date] = None
    follow_up_date: Optional[date] = None
    private_notes: Optional[str] = None


class OpportunityOverviewStats(BaseModel):
    verified_open_count: int = 0
    strong_matches_count: int = 0
    opening_soon_count: int = 0
    upcoming_deadlines_count: int = 0
    saved_count: int = 0
    applications_in_progress_count: int = 0
    last_sync_at: Optional[datetime] = None
    total_tracked_opportunities: int = 0
    # Employer Category Counts
    startups_count: int = 0
    research_count: int = 0
    government_count: int = 0
    open_source_count: int = 0
    enterprise_count: int = 0


class OpportunitiesListResponse(BaseModel):
    opportunities: List[OpportunityOut]
    total: int
    page: int
    page_size: int
    has_more: bool
