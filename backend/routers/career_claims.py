"""
Compass — Career Copilot Online Factual Claim Verification Router.

Provides authenticated endpoints for:
1. Cross-referencing resume claims (institutions, employers, certifications,
   awards, publications, and external links) against live web sources.
2. Synchronously refreshing offline consistency validation so UI state stays in sync.
"""
from __future__ import annotations

import logging
import time
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.dependencies import _get_or_create_user_id, rate_limit
from backend.memory.career import get_master_resume, get_resume_by_id, update_resume
from backend.memory.radar import get_opportunity_by_id
from backend.models_career import ResumeValidationStatus
from backend.services.career_resume import validate_resume_against_master
from backend.services.claim_verifier import ClaimVerificationReport, verify_claims

logger = logging.getLogger("compass.routers.career_claims")

router = APIRouter(prefix="/api/career", tags=["career_copilot"])

_user_cooldowns: Dict[str, float] = {}
COOLDOWN_SECONDS: float = 20.0


def _enforce_user_cooldown(user_id: str) -> None:
    now = time.monotonic()
    # Periodic pruning of stale cooldown entries to prevent unbounded growth
    if len(_user_cooldowns) > 1000:
        stale_threshold = now - (COOLDOWN_SECONDS * 2)
        stale_keys = [k for k, v in _user_cooldowns.items() if v < stale_threshold]
        for k in stale_keys:
            _user_cooldowns.pop(k, None)

    last_run = _user_cooldowns.get(user_id)
    if last_run is not None and (now - last_run) < COOLDOWN_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait a few seconds before checking again.",
        )
    _user_cooldowns[user_id] = now


@router.post(
    "/resumes/{resume_id}/verify-claims",
    response_model=ClaimVerificationReport,
    dependencies=[Depends(rate_limit)],
)
async def verify_resume_claims_endpoint(
    resume_id: int,
    request: Request,
) -> ClaimVerificationReport:
    """Verify factual claims from a tailored or master resume against live web data."""
    user_id = _get_or_create_user_id(request)

    # Cooldown check: at most 1 run per 20 seconds per user
    _enforce_user_cooldown(user_id)

    res = await get_resume_by_id(resume_id, user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Offline consistency validation & persist (so Resume Studio card stays up to date)
    master = await get_master_resume(user_id)
    master_content = res.content if res.is_master else (master.content if master else res.content)

    opp = None
    if res.opportunity_id:
        opp = await get_opportunity_by_id(res.opportunity_id, user_id)

    offline_report = validate_resume_against_master(res.content, master_content, opp)
    new_status = (
        ResumeValidationStatus.READY_FOR_REVIEW
        if offline_report.is_valid
        else ResumeValidationStatus.VALIDATION_FAILED
    )

    await update_resume(
        resume_id,
        user_id,
        {
            "validation_status": new_status.value,
            "validation_report": offline_report,
        },
    )

    # Online factual claim verification (results are not persisted to database)
    claims_report = await verify_claims(res.content)
    return claims_report
