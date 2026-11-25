"""
Compass — Internship Radar API Router.

Provides authenticated endpoints for opportunity discovery, eligibility matching,
watchlist monitoring, application pipeline tracking, and source synchronization.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.dependencies import Identity, _get_or_create_user_id, _get_current_identity, rate_limit, require_identity
from backend.memory.radar import (
    add_status_history,
    delete_user_saved_opportunity,
    get_all_opportunities,
    get_last_sync_run,
    OPENING_SOON_STATUSES,
    get_opportunity_by_id,
    get_recommendation_candidates,
    get_radar_overview_stats,
    list_open_opportunities,
    get_user_application_tracking,
    get_user_opportunity_profile,
    get_user_saved_opportunities,
    update_opportunity_status,
    upsert_user_application_status,
    upsert_user_opportunity_profile,
    upsert_user_saved_opportunity,
)
from backend.models_radar import (
    ApplicationStatus,
    EligibilityClassification,
    OpportunitiesListResponse,
    OpportunityOut,
    OpportunityOverviewStats,
    OpportunityStatus,
    UpdateApplicationStatusIn,
    UserOpportunityProfileIn,
    UserOpportunityProfileOut,
    UserOpportunityProfileUpdate,
)
from backend.services.radar_eligibility import evaluate_eligibility
from backend.services.radar_freshness import needs_recheck, verification_age_days
from backend.services.radar_inventory import get_source_inventory
from backend.services.radar_jd import fetch_and_store_listing_details
from backend.services.radar_prediction import estimate_recruitment_cycle
from backend.services.radar_quality import (
    dedupe_opportunities,
    profile_country_of,
    recommendation_rank_key,
    refine_listings,
)
from backend.services.radar_sync import run_radar_sync
from backend.services.radar_verifier import is_fetch_failure, should_demote_after_failure, verify_opportunity_status

logger = logging.getLogger("compass.routers.radar")

router = APIRouter(prefix="/api/opportunities", tags=["internship_radar"])


def compute_is_verified_within_24h(
    posted_at: Optional[Any],
    precision: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> bool:
    """Compute is_verified_within_24h at read time:
    precision in ('exact', 'exact_timestamp') AND 0 <= (now - posted_at) <= 24h.
    Future timestamps and date_only/unknown precision are NEVER verified.
    Safely handles ISO strings.
    """
    if not posted_at or (precision or "").strip().lower() not in ("exact", "exact_timestamp"):
        return False
    if isinstance(posted_at, str):
        try:
            posted_at = datetime.fromisoformat(posted_at)
        except Exception:
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

    # Truthful status transition: listings with passed deadlines are CLOSED_CONFIRMED, never open
    today = datetime.now(timezone.utc).date()  # UTC, like every stored timestamp
    if opp.confirmed_close_date and opp.confirmed_close_date < today:
        if opp.current_status in (
            OpportunityStatus.OPEN_CONFIRMED,
            OpportunityStatus.UPCOMING_CONFIRMED,
            OpportunityStatus.ANNOUNCED,
            OpportunityStatus.DISCOVERED,
            OpportunityStatus.NEEDS_VERIFICATION,
        ):
            opp.current_status = OpportunityStatus.CLOSED_CONFIRMED
            if not opp.verification_evidence or "closed" not in opp.verification_evidence.lower():
                opp.verification_evidence = f"Application deadline closed on {opp.confirmed_close_date.isoformat()}."

    # Compute historical prediction
    opp.prediction = estimate_recruitment_cycle(opp.cycles)

    # Compute personal eligibility
    cls, explanation, reasons = evaluate_eligibility(opp, profile)
    opp.eligibility_classification = cls
    opp.eligibility_explanation = explanation
    opp.eligibility_reasons = reasons

    # Strictly compute 24h recency at read time from posted_at & precision (no string derivation)
    opp.is_verified_within_24h = compute_is_verified_within_24h(opp.posted_at, opp.posted_at_precision)

    # Truthful freshness and recheck metadata
    opp.verification_age_days = verification_age_days(opp, today=today)
    opp.needs_recheck = needs_recheck(opp, today=today)
    return opp


async def _require_opportunity(opportunity_id: int) -> None:
    if await get_opportunity_by_id(opportunity_id) is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")


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
    recent_24h: bool = Query(False, description="Filter for opportunities verified posted in the last 24 hours"),
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
        recent_24h=recent_24h,
        page=page,
        page_size=page_size,
    )

    # Same rules as the recommendations: merged duplicates, no senior or clearance-only roles, and with the
    # India filter on, no listings from other countries. The tab must never contradict its own heading.
    visible = refine_listings(raw_items, profile_country_of(profile), country_filter=india_only)
    enriched = [_enrich_opportunity(item, profile) for item in visible]
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
    limit: int = Query(30, ge=1, le=300),
    employer_type: Optional[str] = Query(None),
    eligible_only: bool = Query(False, description="When true, strictly returns only confirmed ELIGIBLE opportunities"),
    india_only: bool = Query(True),
):
    """
    Return top recommended opportunities tailored to user's profile and preferences.
    Neutral ranking prioritizes verified active status, candidate eligibility, and skill match
    with zero bias toward company size or prestige.
    """
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)
    items = await recommended_for_user(
        user_id, profile, employer_type=employer_type, eligible_only=eligible_only, india_only=india_only
    )
    return items[:limit]


async def recommended_for_user(
    user_id: str,
    profile: Optional[UserOpportunityProfileIn],
    employer_type: Optional[str] = None,
    eligible_only: bool = False,
    india_only: bool = True,
) -> List[OpportunityOut]:
    """The one recommendation query: Career page, chat, and the heading counters all use it.

    Same candidate set as the ELIGIBLE MATCHES stat (open / upcoming / announced), then deduped,
    stripped of senior, clearance and out-of-country listings, enriched, and ranked with the
    candidate's own country first.
    """
    raw_items = await get_recommendation_candidates(user_id, employer_type=employer_type, india_only=india_only)
    profile_country = profile_country_of(profile)
    refined = refine_listings(raw_items, profile_country, country_filter=india_only)
    enriched = [_enrich_opportunity(item, profile) for item in refined]

    # Recommendations never include listings the candidate is definitively ineligible for.
    enriched = [o for o in enriched if o.eligibility_classification != EligibilityClassification.INELIGIBLE]

    if eligible_only:
        enriched = [o for o in enriched if o.eligibility_classification == EligibilityClassification.ELIGIBLE]

    enriched.sort(key=lambda o: recommendation_rank_key(o, profile, profile_country))
    return enriched


@router.get("/open", response_model=List[OpportunityOut])
async def get_open_confirmed_opportunities(
    request: Request,
    limit: int = Query(300, ge=1, le=500),
    category: Optional[str] = Query(None),
    employer_type: Optional[str] = Query(None),
    work_arrangement: Optional[str] = Query(None),
    india_only: bool = Query(True),
):
    """Return strictly verified open opportunities across all employer types."""
    user_id = _get_or_create_user_id(request)
    return await list_open_opportunities(
        user_id=user_id,
        category=category,
        employer_type=employer_type,
        work_arrangement=work_arrangement,
        india_only=india_only,
        limit=limit,
    )


@router.get("/upcoming", response_model=List[OpportunityOut])
async def get_upcoming_opportunities(request: Request):
    """Return confirmed future openings (same status filter as the Opening Soon stat)."""
    user_id = _get_or_create_user_id(request)
    profile = await get_user_opportunity_profile(user_id)

    raw_items, _ = await get_all_opportunities(
        user_id=user_id, statuses=OPENING_SOON_STATUSES, page=1, page_size=100
    )
    return [_enrich_opportunity(item, profile) for item in raw_items]


@router.get("/analytics", response_model=OpportunityOverviewStats)
async def get_radar_analytics_endpoint(request: Request, india_only: bool = Query(False)):
    """Return live dashboard statistics computed from real database records and user profile."""
    user_id = _get_or_create_user_id(request)
    stats_dict = await get_radar_overview_stats(user_id, india_only=india_only)
    try:
        # Retain DB-wide verified_open_count and stale_open_count from get_radar_overview_stats,
        # but compute strong_matches_count personalized to the user's recommended list.
        profile = await get_user_opportunity_profile(user_id)
        shown = await recommended_for_user(user_id, profile, india_only=india_only)
        stats_dict["strong_matches_count"] = sum(
            1 for o in shown if o.eligibility_classification == EligibilityClassification.ELIGIBLE
        )
    except Exception:
        logger.warning("Could not align radar counters with the recommendation list", exc_info=True)
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
    await _require_opportunity(opportunity_id)
    await upsert_user_saved_opportunity(user_id, opportunity_id, is_saved=True)
    return {"status": "ok", "saved": True, "opportunity_id": opportunity_id}


@router.delete("/{opportunity_id}/save")
async def unsave_opportunity_endpoint(opportunity_id: int, request: Request):
    """Remove an opportunity from user watchlist."""
    user_id = _get_or_create_user_id(request)
    await _require_opportunity(opportunity_id)
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
    if body.application_status not in ApplicationStatus.ALL:
        raise HTTPException(status_code=422, detail="Unknown application_status")
    await _require_opportunity(opportunity_id)
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
async def update_profile_endpoint(body: UserOpportunityProfileUpdate, request: Request):
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

    if is_fetch_failure(evidence):
        # Nothing was verified: keep the old last_verified_at and never raise the status. After a long
        # run of failed checks an "open" listing is demoted, again without touching the timestamp.
        demoted = should_demote_after_failure(opp.current_status, opp.last_verified_at)
        if demoted:
            await update_opportunity_status(opportunity_id, OpportunityStatus.NEEDS_VERIFICATION, opp.last_verified_at)
            await add_status_history(
                opportunity_id=opportunity_id,
                prev_status=opp.current_status,
                new_status=OpportunityStatus.NEEDS_VERIFICATION,
                evidence_source=target_url,
                reason="Could not re-check the listing for several weeks.",
            )
        return {
            "opportunity_id": opportunity_id,
            "previous_status": opp.current_status,
            "current_status": OpportunityStatus.NEEDS_VERIFICATION if demoted else opp.current_status,
            "evidence": "Could not re-check today.",
            "last_verified_at": opp.last_verified_at.isoformat() if opp.last_verified_at else None,
            "check_failed": True,
        }

    # Always persist last_verified_at so the cooldown holds even when status is unchanged.
    await update_opportunity_status(opportunity_id, new_status, verified_at)
    if new_status != opp.current_status:
        await add_status_history(
            opportunity_id=opportunity_id,
            prev_status=opp.current_status,
            new_status=new_status,
            evidence_source=target_url,
            reason=evidence,
        )

    result = {
        "opportunity_id": opportunity_id,
        "previous_status": opp.current_status,
        "current_status": new_status,
        "evidence": evidence,
        "last_verified_at": verified_at.isoformat(),
    }
    if new_status != OpportunityStatus.CLOSED_CONFIRMED:
        # Best effort: a stub description gets replaced by the real posting text, apply link and deadline.
        try:
            fresh_opp = opp.model_copy(update={"current_status": new_status})  # never write the pre-check status back
            details = await asyncio.wait_for(fetch_and_store_listing_details(opportunity_id, opportunity=fresh_opp), timeout=15.0)
            if details.get("fetched"):
                result["details_fetched"] = True
        except Exception:
            logger.info("Listing detail fetch skipped for %s", opportunity_id)
    return result


@router.get("/{opportunity_id}", response_model=OpportunityOut)
async def get_opportunity_detail_endpoint(opportunity_id: int, request: Request):
    """Retrieve complete opportunity details with sources, cycles, predictions, and eligibility evidence."""
    user_id = _get_or_create_user_id(request)
    opp = await get_opportunity_by_id(opportunity_id, user_id=user_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    profile = await get_user_opportunity_profile(user_id)
    return _enrich_opportunity(opp, profile)
