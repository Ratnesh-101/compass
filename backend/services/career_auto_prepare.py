"""
Compass — Career Auto-Prepare Service (Opt-In & Capped).

Replaces legacy unconstrained tailoring with an opt-in, cost-guarded, idempotent
background auto-prepare pipeline for strongest matching saved opportunities.

Guards:
- Default: OFF. Explicit opt-in per identity required.
- Limit: At most 3 saved/watchlisted opportunities with ELIGIBLE status and complete profile.
- Rate limits / cost guards:
    * Authenticated user: 5 drafts / 24 hours.
    * Guest identity: 2 drafts / 24 hours.
    * Global cap: 100 drafts / 24 hours.
    * Fail-closed with HTTP 429 and Retry-After header.
- Idempotency: per (identity, opportunity_id, profile_version_hash).
- Zero hallucination: Strictly reorders master profile facts, never invents qualifications.
- Review gate: Labeled 'Draft: review before use', never marks applied or emails anything.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from backend.models_career import CareerApplicationStatus
from backend.models_radar import EligibilityClassification
from backend.services.radar_eligibility import evaluate_eligibility
from backend.services.career_resume import tailor_resume_for_opportunity, draft_truthful_cover_letter

logger = logging.getLogger("compass.services.career_auto_prepare")

# Rate limit tracking: user_id -> list of timestamps
_user_auto_prepare_timestamps: Dict[str, List[float]] = {}
_global_auto_prepare_timestamps: List[float] = []

USER_DAILY_LIMIT = 5
GUEST_DAILY_LIMIT = 2
GLOBAL_DAILY_LIMIT = 100
WINDOW_SECONDS = 86400  # 24 hours


def _clean_old_timestamps(timestamps: List[float], now: float) -> List[float]:
    cutoff = now - WINDOW_SECONDS
    return [ts for ts in timestamps if ts > cutoff]


def get_profile_version_hash(full_name: str, email: str, skills: List[str], education_count: int) -> str:
    norm = f"{full_name.strip().lower()}|{email.strip().lower()}|{','.join(sorted(s.lower() for s in skills))}|{education_count}"
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def check_and_record_auto_prepare_quota(user_id: str) -> Tuple[bool, Optional[int]]:
    """
    Checks rate limits. Returns (allowed, retry_after_seconds).
    If allowed, records the draft generation timestamp.
    """
    global _user_auto_prepare_timestamps, _global_auto_prepare_timestamps
    now = time.time()

    # Clean global
    _global_auto_prepare_timestamps = _clean_old_timestamps(_global_auto_prepare_timestamps, now)
    if len(_global_auto_prepare_timestamps) >= GLOBAL_DAILY_LIMIT:
        oldest = _global_auto_prepare_timestamps[0]
        retry_after = max(1, int(WINDOW_SECONDS - (now - oldest)))
        return False, retry_after

    # Clean user
    user_ts = _clean_old_timestamps(_user_auto_prepare_timestamps.get(user_id, []), now)
    _user_auto_prepare_timestamps[user_id] = user_ts

    limit = GUEST_DAILY_LIMIT if user_id.startswith("guest:") else USER_DAILY_LIMIT
    if len(user_ts) >= limit:
        oldest = user_ts[0]
        retry_after = max(1, int(WINDOW_SECONDS - (now - oldest)))
        return False, retry_after

    # Record quota consumption
    _user_auto_prepare_timestamps[user_id].append(now)
    _global_auto_prepare_timestamps.append(now)
    return True, None


def get_user_quota_status(user_id: str) -> Dict[str, Any]:
    """Inspect user quota usage for UI visibility and retry countdown."""
    now = time.time()
    user_ts = _clean_old_timestamps(_user_auto_prepare_timestamps.get(user_id, []), now)
    _user_auto_prepare_timestamps[user_id] = user_ts

    limit = GUEST_DAILY_LIMIT if user_id.startswith("guest:") else USER_DAILY_LIMIT
    used = len(user_ts)
    remaining = max(0, limit - used)

    retry_after = None
    if remaining == 0 and user_ts:
        retry_after = max(1, int(WINDOW_SECONDS - (now - user_ts[0])))

    return {
        "user_id": user_id,
        "daily_limit": limit,
        "used_today": used,
        "remaining_today": remaining,
        "retry_after_seconds": retry_after,
        "is_rate_limited": remaining == 0,
    }


def reset_auto_prepare_quotas() -> None:
    """Testing helper to clear rate limit state."""
    global _user_auto_prepare_timestamps, _global_auto_prepare_timestamps
    _user_auto_prepare_timestamps.clear()
    _global_auto_prepare_timestamps.clear()


async def execute_auto_prepare_for_user(user_id: str) -> Dict[str, Any]:
    """
    Executes opt-in auto-prepare for a candidate's watchlisted opportunities.
    Returns summary result of processed, skipped, or rate-limited items.
    """
    from backend.memory.radar import get_user_opportunity_profile, get_user_saved_opportunities, get_opportunity_by_id
    from backend.memory.career import (
        get_master_resume,
        get_or_create_career_application,
        create_tailored_resume,
        update_career_application,
        log_application_event,
    )

    profile = await get_user_opportunity_profile(user_id)
    if not profile or not profile.auto_prepare_strongest_matches:
        return {
            "status": "opted_out",
            "message": "Auto-prepare is disabled for this profile. Opt-in required.",
            "prepared_count": 0,
            "drafts": [],
        }

    # Verify complete profile
    master = await get_master_resume(user_id)
    if not master or not master.content:
        return {
            "status": "incomplete_profile",
            "message": "Master resume profile is incomplete. Please add verified skills and education before enabling auto-prepare.",
            "prepared_count": 0,
            "drafts": [],
        }

    c = master.content
    has_name = bool((c.full_name or "").strip())
    has_email = bool((c.email or "").strip()) and "@" in (c.email or "")
    has_edu = len(c.education) > 0
    has_skills = len(c.skills) > 0

    if not (has_name and has_email and has_edu and has_skills):
        return {
            "status": "incomplete_profile",
            "message": "Master resume requires candidate name, email, education, and skills before auto-prepare can run.",
            "prepared_count": 0,
            "drafts": [],
        }

    profile_version = get_profile_version_hash(c.full_name, c.email, c.skills, len(c.education))

    # Fetch watchlisted opportunities
    saved_opps = await get_user_saved_opportunities(user_id)
    if not saved_opps:
        return {
            "status": "no_saved_opportunities",
            "message": "No watchlisted opportunities found to auto-prepare.",
            "prepared_count": 0,
            "drafts": [],
        }

    # Filter for eligible opportunities only (capped at top 3)
    eligible_opps = []
    for opp in saved_opps:
        # Check eligibility
        status_val, _, _ = evaluate_eligibility(opp, profile)
        if status_val == EligibilityClassification.ELIGIBLE:
            eligible_opps.append(opp)
        if len(eligible_opps) >= 3:
            break

    if not eligible_opps:
        return {
            "status": "no_eligible_opportunities",
            "message": "No watchlisted opportunities met confirmed ELIGIBLE status.",
            "prepared_count": 0,
            "drafts": [],
        }

    prepared_results = []
    for opp in eligible_opps:
        app = await get_or_create_career_application(user_id, opp.id)

        # Idempotency check:
        # If application already has a tailored resume and private notes record this profile version, skip!
        app_notes = app.private_notes or ""
        expected_tag = f"[auto_prep_v:{profile_version}]"
        if app.resume_id and expected_tag in app_notes:
            prepared_results.append({
                "opportunity_id": opp.id,
                "company_name": opp.company_name,
                "status": "already_up_to_date",
                "message": "Draft already tailored for current master profile version.",
            })
            continue

        # Check rate limit quota
        allowed, retry_after = check_and_record_auto_prepare_quota(user_id)
        if not allowed:
            return {
                "status": "rate_limited",
                "message": f"Daily auto-prepare limit reached. Retry after {retry_after} seconds.",
                "retry_after": retry_after,
                "prepared_count": len([r for r in prepared_results if r.get("status") == "prepared"]),
                "drafts": prepared_results,
            }

        # Deterministically tailor resume
        tailored_content, report, val_status = tailor_resume_for_opportunity(c, opp)
        tailored = await create_tailored_resume(
            user_id=user_id,
            opportunity_id=opp.id,
            title=f"{opp.company_name} Tailored Resume (Auto-Draft)",
            content=tailored_content,
            validation_report=report,
            validation_status=val_status,
        )

        # Truthful cover letter
        letter_text, _, _ = draft_truthful_cover_letter(c, opp)

        # Attach to application with non-mutating review status
        note_text = f"Draft: review before use {expected_tag}"
        updated_app = await update_career_application(app.id, user_id, {
            "resume_id": tailored.id,
            "cover_letter": letter_text,
            "status": CareerApplicationStatus.READY_FOR_REVIEW.value,
            "private_notes": note_text,
        })

        await log_application_event(app.id, "auto_prepared_draft", {
            "opportunity_id": opp.id,
            "profile_version": profile_version,
            "resume_id": tailored.id,
        })

        prepared_results.append({
            "opportunity_id": opp.id,
            "company_name": opp.company_name,
            "role_title": opp.role_title,
            "application_id": app.id,
            "status": "prepared",
            "message": "Draft tailored resume and truthful cover letter generated for candidate review.",
        })

    return {
        "status": "completed",
        "prepared_count": len([r for r in prepared_results if r.get("status") == "prepared"]),
        "drafts": prepared_results,
    }
