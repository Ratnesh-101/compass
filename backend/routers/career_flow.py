"""
Compass - Career flow routes (WS-D): paste a job link, ATS check.

Included by `backend.routers.career`, so the paths live under /api/career and use the same identity
dependency. Both routes are owner scoped: the resume and the application come from the caller's own
records only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.dependencies import _get_current_identity, _get_or_create_user_id, rate_limit
from backend.memory.career import get_master_resume, get_resume_by_id
from backend.memory.radar import get_opportunity_by_id
from backend.models_career import CareerApplicationOut, ResumeContent
from backend.models_radar import UserOpportunityProfileIn
from backend.services import winning_features
from backend.services.career_flow import MAX_LINK_CHARS, prepare_from_link
from backend.services.career_resume import build_default_master_for_user

logger = logging.getLogger("compass.routers.career_flow")

router = APIRouter()


class JobLinkRequest(BaseModel):
    url: str = Field(min_length=4, max_length=MAX_LINK_CHARS)


class AtsCheckRequest(BaseModel):
    resume_id: Optional[int] = None
    opportunity_id: Optional[int] = None


def _master_factory(request: Request):
    ident = getattr(request.state, "identity", None) or _get_current_identity(request)
    authed_id = ident.user_id if ident and not ident.is_guest else None

    def build(profile: Optional[UserOpportunityProfileIn]) -> ResumeContent:
        return build_default_master_for_user(profile, authed_id)

    return build


@router.post("/applications/from-url", response_model=CareerApplicationOut, dependencies=[Depends(rate_limit)])
async def prepare_from_job_link_endpoint(body: JobLinkRequest, request: Request):
    """Paste a job link: Compass reads the page, finds or creates the listing and prepares the application."""
    user_id = _get_or_create_user_id(request)
    return await prepare_from_link(user_id, body.url, _master_factory(request))


@router.post("/ats-check")
async def ats_check_endpoint(body: AtsCheckRequest, request: Request) -> Dict[str, Any]:
    """Estimate how a basic applicant tracking system reads a resume (the master when no id is given)."""
    user_id = _get_or_create_user_id(request)
    resume = await get_resume_by_id(body.resume_id, user_id) if body.resume_id is not None else await get_master_resume(user_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    required, job_text = [], ""
    opp_id = body.opportunity_id if body.opportunity_id is not None else resume.opportunity_id
    if opp_id is not None:
        opp = await get_opportunity_by_id(opp_id, user_id)
        if opp:
            required = list(opp.requirements.required_skills) if opp.requirements and opp.requirements.required_skills else []
            job_text = f"{opp.role_title}\n{opp.description or ''}"
    return winning_features.simulate_ats_parsing(resume.content, required, job_text)
