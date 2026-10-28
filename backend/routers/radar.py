"""
Compass — Internship Radar API Router.

Provides authenticated endpoints for opportunity discovery, eligibility matching,
watchlist monitoring, application pipeline tracking, and source synchronization.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.dependencies import Identity, _get_or_create_user_id, _get_current_identity, rate_limit, require_identity
from backend.memory.radar import (
    add_status_history,
    delete_user_saved_opportunity,
    get_all_opportunities,
    get_last_sync_run,
    get_opportunity_by_id,
    get_radar_overview_stats,
    get_user_application_tracking,
    get_user_opportunity_profile,
    get_user_saved_opportunities,
    update_opportunity_status,
    upsert_user_application_status,
    upsert_user_opportunity_profile,
    upsert_user_saved_opportunity,
)
from backend.models_radar import (
    EligibilityClassification,
    OpportunitiesListResponse,
    OpportunityOut,
    OpportunityOverviewStats,
    OpportunityStatus,
    UpdateApplicationStatusIn,
    UserOpportunityProfileIn,
    UserOpportunityProfileOut,
)
from backend.services.radar_eligibility import evaluate_eligibility
from backend.services.radar_inventory import get_source_inventory
from backend.services.radar_prediction import estimate_recruitment_cycle
from backend.services.radar_sync import run_radar_sync
from backend.services.radar_verifier import verify_opportunity_status

logger = logging.getLogger("compass.routers.radar")

router = APIRouter(prefix="/api/opportunities", tags=["internship_radar"])


def compute_is_verified_within_24h(
    posted_at: Optional[datetime],
    precision: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> bool:
    """Compute is_verified_within_24h at read time:
    precision == 'exact' AND 0 <= (now - posted_at) <= 24h.
    Future timestamps and date_only/unknown precision are NEVER verified.
    """
    if not posted_at or precision != "exact":
        return False
    now = now_utc or datetime.now(timezone.utc)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    age = now - posted_at
    return 0 <= age.total_seconds() <= 86400


def _enrich_opportunity(opp: OpportunityOut, profile: Optional[UserOpportunityProfileIn]) -> OpportunityOut:
    """Enriches an opportunity with predictive cycle estimates and personal eligibility."""
    # Sanitize malformed values at boundary
    if opp.compensation and any(k in str(opp.compensation).lower() for k in ("nan", "null", "undefined")):
        opp.compensation = None
    if opp.location and str(opp.location).lower() in ("nan", "null", "undefined", "none"):
        opp.location = None
    if opp.description and str(opp.description).lower() in ("nan", "null", "undefined", "none"):
        opp.description = None

    # Compute historical prediction
    opp.prediction = estimate_recruitment_cycle(opp.cycles)

    # Compute personal eligibility
    cls, explanation, reasons = evaluate_eligibility(opp, profile)
    opp.eligibility_classification = cls
    opp.eligibility_explanation = explanation
    opp.eligibility_reasons = reasons

    # Strictly compute 24h recency at read time from posted_at & precision (no string derivation)
    opp.is_verified_within_24h = compute_is_verified_within_24h(opp.posted_at, opp.posted_at_precision)
    return opp


@router.get("", response_model=OpportunitiesListResponse)
async def list_opportunities_endpoint(
    request: Request,
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    employer_type: Optional[str] = Query(None),
    work_arrangement: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    india_only: bool = Query(False),
    verified_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List opportunities with pagination, filtering, employer type selection, and deterministic eligibility assessment."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)

    raw_items, total = await get_all_opportunities(
        user_id=user_id,
        status=status,
        category=category,
        employer_type=employer_type,
        work_arrangement=work_arrangement,
        country=country,
        search=search,
        india_only=india_only,
        verified_only=verified_only,
        page=page,
        page_size=page_size,
    )

    enriched = [_enrich_opportunity(item, profile) for item in raw_items]
    return OpportunitiesListResponse(
        opportunities=enriched,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/recommended", response_model=List[OpportunityOut])
async def get_recommended_opportunities(
    request: Request,
    limit: int = Query(20, ge=1, le=50),
    employer_type: Optional[str] = Query(None),
    eligible_only: bool = Query(False, description="When true, strictly returns only confirmed ELIGIBLE opportunities"),
):
    """
    Return top recommended opportunities tailored to user's profile and preferences.
    Neutral ranking prioritizes verified active status, candidate eligibility, and skill match
    with zero bias toward company size or prestige.
    """
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)

    raw_items, _ = await get_all_opportunities(
        user_id=user_id,
        employer_type=employer_type,
        page=1,
        page_size=200,  # Evaluate broader candidate set for ranking
    )

    enriched = [_enrich_opportunity(item, profile) for item in raw_items]

    # If eligible_only is requested, strictly filter for ELIGIBLE
    if eligible_only:
        enriched = [o for o in enriched if o.eligibility_classification == EligibilityClassification.ELIGIBLE]

    # Neutral Ranking Matrix:
    # 1. Verified and active status: OPEN_CONFIRMED first (0), UPCOMING_CONFIRMED (1), others (2)
    # 2. Personal candidate eligibility: ELIGIBLE (0), POTENTIAL_MATCH (1), INSUFFICIENT_INFO (2), INELIGIBLE (3)
    # 3. User preferred role fit (bonus -1)
    # 4. User skill match overlap (bonus -N)
    # 5. India / Remote eligibility preference
    # 6. Approaching application deadline
    def rank_key(o: OpportunityOut) -> tuple:
        status_weight = 0 if o.current_status == OpportunityStatus.OPEN_CONFIRMED else (
            1 if o.current_status in (OpportunityStatus.UPCOMING_CONFIRMED, OpportunityStatus.ANNOUNCED) else 2
        )
        eligibility_weight = {
            EligibilityClassification.ELIGIBLE: 0,
            EligibilityClassification.POTENTIAL_MATCH: 1,
            EligibilityClassification.INSUFFICIENT_INFORMATION: 2,
            EligibilityClassification.INELIGIBLE: 3,
        }.get(o.eligibility_classification, 2)

        role_bonus = 0
        if profile and profile.preferred_roles:
            pref = [r.lower() for r in profile.preferred_roles]
            if any(p in o.role_title.lower() or p in o.category.lower() for p in pref):
                role_bonus = -1

        skill_bonus = 0
        if profile and profile.skills and o.requirements and o.requirements.required_skills:
            user_s = {s.strip().lower() for s in profile.skills if s.strip()}
            req_s = {s.strip().lower() for s in o.requirements.required_skills if s.strip()}
            overlap = len(user_s.intersection(req_s))
            skill_bonus = -overlap

        india_bonus = 0 if o.is_india_eligible else 1
        deadline_weight = o.confirmed_close_date.toordinal() if o.confirmed_close_date else 9999999

        return (status_weight, eligibility_weight, role_bonus, skill_bonus, india_bonus, deadline_weight)

    enriched.sort(key=rank_key)
    return enriched[:limit]


@router.get("/open", response_model=List[OpportunityOut])
async def get_open_confirmed_opportunities(
    request: Request,
    category: Optional[str] = Query(None),
    employer_type: Optional[str] = Query(None),
    work_arrangement: Optional[str] = Query(None),
    india_only: bool = Query(True),
):
    """Return strictly verified open opportunities across all employer types."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)

    raw_items, _ = await get_all_opportunities(
        user_id=user_id,
        status=OpportunityStatus.OPEN_CONFIRMED,
        category=category,
        employer_type=employer_type,
        work_arrangement=work_arrangement,
        india_only=india_only,
        page=1,
        page_size=100,
    )
    return [_enrich_opportunity(item, profile) for item in raw_items]


@router.get("/upcoming", response_model=List[OpportunityOut])
async def get_upcoming_opportunities(request: Request):
    """Return confirmed future openings and opportunities with reliable recruitment cycle estimates."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)

    raw_items, _ = await get_all_opportunities(user_id=user_id, page=1, page_size=100)
    enriched = [_enrich_opportunity(item, profile) for item in raw_items]

    # Filter items that are either UPCOMING_CONFIRMED or have non-empty prediction
    upcoming = [
        item for item in enriched
        if item.current_status in {OpportunityStatus.UPCOMING_CONFIRMED, OpportunityStatus.ANNOUNCED}
        or (item.prediction and item.prediction.estimated_open_window is not None)
    ]
    return upcoming


@router.get("/analytics", response_model=OpportunityOverviewStats)
async def get_radar_analytics_endpoint(request: Request):
    """Return live dashboard statistics computed from real database records and user profile."""
    user_id = _get_or_create_user_id(request)
    stats_dict = await get_radar_overview_stats(user_id)
    return OpportunityOverviewStats(**stats_dict)


@router.get("/watchlist", response_model=List[OpportunityOut])
async def get_watchlist_endpoint(request: Request):
    """Return opportunities saved to the authenticated user's watchlist."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)
    saved = await get_user_saved_opportunities(user_id)
    return [_enrich_opportunity(item, profile) for item in saved]


@router.post("/{opportunity_id}/save")
async def save_opportunity_endpoint(opportunity_id: int, request: Request):
    """Save an opportunity to user watchlist."""
    user_id = _get_or_create_user_id(request)
    await upsert_user_saved_opportunity(user_id, opportunity_id, is_saved=True)
    return {"status": "ok", "saved": True, "opportunity_id": opportunity_id}


@router.delete("/{opportunity_id}/save")
async def unsave_opportunity_endpoint(opportunity_id: int, request: Request):
    """Remove an opportunity from user watchlist."""
    user_id = _get_or_create_user_id(request)
    await delete_user_saved_opportunity(user_id, opportunity_id)
    return {"status": "ok", "saved": False, "opportunity_id": opportunity_id}


@router.get("/applications", response_model=List[OpportunityOut])
async def get_applications_endpoint(request: Request):
    """List all tracked applications for the authenticated user."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)
    apps = await get_user_application_tracking(user_id)
    return [_enrich_opportunity(item, profile) for item in apps]


@router.post("/{opportunity_id}/application")
@router.patch("/{opportunity_id}/application")
async def update_application_status_endpoint(
    opportunity_id: int,
    body: UpdateApplicationStatusIn,
    request: Request,
):
    """Update application tracking status, deadlines, and private notes."""
    user_id = _get_or_create_user_id(request)
    await upsert_user_application_status(
        user_id=user_id,
        opportunity_id=opportunity_id,
        status=body.application_status,
        app_date=body.application_date,
        personal_deadline=body.personal_deadline,
        notes=body.private_notes,
    )
    return {"status": "ok", "opportunity_id": opportunity_id, "application_status": body.application_status}


@router.get("/profile", response_model=UserOpportunityProfileOut)
async def get_profile_endpoint(request: Request):
    """Retrieve personal opportunity matching profile."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)
    if not profile:
        profile = UserOpportunityProfileIn()

    missing = []
    if profile.academic_year is None:
        missing.append("academic_year")
    if profile.grad_year is None:
        missing.append("grad_year")
    if not profile.degree:
        missing.append("degree")
    if not profile.skills:
        missing.append("skills")

    return UserOpportunityProfileOut(
        user_id=user_id,
        **profile.model_dump(),
        missing_fields_limiting_eligibility=missing,
    )


@router.put("/profile", response_model=UserOpportunityProfileOut)
async def update_profile_endpoint(body: UserOpportunityProfileIn, request: Request):
    """Create or update personal opportunity matching profile."""
    user_id = _get_or_create_user_id(request)
    await upsert_user_opportunity_profile(user_id, body)
    return await get_profile_endpoint(request)


@router.post("/sync")
async def trigger_sync_endpoint(request: Request, source: Optional[str] = Query(None)):
    """Trigger an on-demand source discovery and verification synchronization run.
    Restricted to admin / nightly automation.
    """
    ident = _get_current_identity(request)
    if not (ident and ident.is_admin):
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Admin or nightly automation credentials required to trigger source synchronization.",
        )
    res = await run_radar_sync(source_filter=source)
    return res


@router.get("/sync/status")
async def get_sync_status_endpoint():
    """Check status of last synchronization run."""
    last_run = await get_last_sync_run()
    return {"last_run": last_run}


@router.get("/sources", response_model=List[Dict[str, Any]])
async def list_sources_endpoint():
    """Retrieve the audited source inventory with access methods, permissions, and status."""
    return get_source_inventory()


VERIFY_COOLDOWN_SECONDS = 600


@router.post("/{opportunity_id}/verify", dependencies=[Depends(rate_limit)])
async def recheck_opportunity_status_endpoint(opportunity_id: int, ident: Identity = Depends(require_identity)):
    """Perform real-time official source verification on a single opportunity.

    Requires a signed-in or guest identity and is rate limited. A recently verified opportunity returns
    its stored result instead of spending another Tavily credit and outbound fetch.
    """
    opp = await get_opportunity_by_id(opportunity_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    last_checked = getattr(opp, "last_verified_at", None)
    if last_checked is not None:
        checked_at = last_checked if last_checked.tzinfo else last_checked.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - checked_at).total_seconds() < VERIFY_COOLDOWN_SECONDS:
            return {
                "opportunity_id": opportunity_id,
                "previous_status": opp.current_status,
                "current_status": opp.current_status,
                "evidence": "Verified within the last 10 minutes; showing the stored result.",
                "last_verified_at": checked_at.isoformat(),
                "cached": True,
            }

    target_url = opp.official_application_url or opp.canonical_url
    new_status, evidence, verified_at = await verify_opportunity_status(target_url, opp.current_status)

    if new_status != opp.current_status:
        await update_opportunity_status(opportunity_id, new_status, verified_at)
        await add_status_history(
            opportunity_id=opportunity_id,
            prev_status=opp.current_status,
            new_status=new_status,
            evidence_source=target_url,
            reason=evidence,
        )

    return {
        "opportunity_id": opportunity_id,
        "previous_status": opp.current_status,
        "current_status": new_status,
        "evidence": evidence,
        "last_verified_at": verified_at.isoformat(),
    }


@router.get("/{opportunity_id}", response_model=OpportunityOut)
async def get_opportunity_detail_endpoint(opportunity_id: int, request: Request):
    """Retrieve complete opportunity details with sources, cycles, predictions, and eligibility evidence."""
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(opportunity_id, user_id=user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    profile = await get_user_opportunity_profile(user_id)
    return _enrich_opportunity(opp, profile)
