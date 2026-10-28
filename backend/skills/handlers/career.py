"""
Compass — Career Copilot Conversational Skill Handlers.

Handles conversational agent tool execution for Resume Studio and Application Center:
1. tailor_resume
2. prepare_application
3. submit_approved_application_batch
4. track_career_applications
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.memory.career import (
    claim_application_batch_for_submission,
    create_tailored_resume,
    finish_application_batch,
    get_application_batch,
    get_career_application_by_id,
    get_master_resume,
    get_or_create_career_application,
    list_career_applications,
    release_application_batch_claim,
    update_career_application,
    upsert_master_resume,
)
from backend.memory.radar import (
    get_all_opportunities,
    get_opportunity_by_id,
    get_user_opportunity_profile,
)
from backend.models_career import CareerApplicationStatus, SubmissionMethod
from backend.models_radar import UserOpportunityProfileIn
from backend.services.career_resume import (
    build_default_master_from_profile,
    draft_truthful_cover_letter,
    tailor_resume_for_opportunity,
)
from backend.services.career_submission import (
    compute_batch_content_hash,
    execute_batch_submission,
    get_batch_lock,
    verify_batch_approval_token,
)
from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.career")


@register_skill("tailor_resume")
async def handle_tailor_resume(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Tailor candidate resume for a specified opportunity."""
    user_id = args.get("user_id", "default_user")
    opp_id = args.get("opportunity_id")
    target_comp = args.get("target_company")

    opp = None
    if opp_id:
        try:
            opp_id_int = int(opp_id)
        except (TypeError, ValueError):
            return {"success": False, "error": f"Invalid opportunity_id '{opp_id}': must be a number."}
        opp = await get_opportunity_by_id(opp_id_int, user_id)
    elif target_comp:
        opps, _ = await get_all_opportunities(user_id=user_id, search=target_comp, page=1, page_size=1)
        if opps:
            opp = opps[0]

    if not opp:
        return {
            "success": False,
            "error": "Could not identify target opportunity. Please specify a verified opportunity ID or company name from Internship Radar.",
        }

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id) or UserOpportunityProfileIn()
        master = await upsert_master_resume(user_id, build_default_master_from_profile(profile), "Master Resume")

    tailored_content, report, val_status = tailor_resume_for_opportunity(
        master=master.content,
        opportunity=opp,
        skills_emphasis=args.get("skills_emphasis"),
    )

    tailored = await create_tailored_resume(
        user_id=user_id,
        opportunity_id=opp.id,
        title=f"{opp.company_name} — {opp.role_title} Tailored",
        content=tailored_content,
        validation_report=report,
        validation_status=val_status,
    )

    summary_lines = [
        f"📄 **Tailored Resume Created:** {tailored.title}",
        f"- **Validation Status:** `{tailored.validation_status.value}`",
        f"- **Skills Aligned:** {len(tailored.content.skills)} verified skills",
    ]
    if report.tailored_alignments:
        summary_lines.append(f"- **Key Emphases:** {', '.join(report.tailored_alignments[:3])}")
    if report.warnings:
        summary_lines.append(f"- **Notice:** {report.warnings[0]}")

    return {
        "success": True,
        "resume_id": tailored.id,
        "title": tailored.title,
        "validation_status": tailored.validation_status.value,
        "is_valid": report.is_valid,
        "summary": "\n".join(summary_lines),
    }


@register_skill("prepare_application")
async def handle_prepare_application(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Prepare application record with tailored resume and answers."""
    user_id = args.get("user_id", "default_user")
    opp_id = args.get("opportunity_id")
    if not opp_id:
        return {"success": False, "error": "opportunity_id is required."}

    opp = await get_opportunity_by_id(int(opp_id), user_id)
    if not opp:
        return {"success": False, "error": f"Opportunity #{opp_id} not found."}

    app = await get_or_create_career_application(user_id, opp.id)
    if not app.resume_id:
        # Auto-tailor
        master = await get_master_resume(user_id)
        if not master:
            profile = await get_user_opportunity_profile(user_id) or UserOpportunityProfileIn()
            master = await upsert_master_resume(user_id, build_default_master_from_profile(profile), "Master Resume")

        tailored_content, report, val_status = tailor_resume_for_opportunity(master.content, opp)
        tailored = await create_tailored_resume(
            user_id=user_id,
            opportunity_id=opp.id,
            title=f"{opp.company_name} Tailored Resume",
            content=tailored_content,
            validation_report=report,
            validation_status=val_status,
        )
        updated = await update_career_application(app.id, user_id, {
            "resume_id": tailored.id,
            "status": CareerApplicationStatus.READY_FOR_REVIEW.value,
        })
        if updated:
            app = updated

    return {
        "success": True,
        "application_id": app.id,
        "opportunity": f"{opp.company_name} — {opp.role_title}",
        "status": app.status.value,
        "summary": (
            f"🚀 **Application Prepared:** {opp.company_name} ({opp.role_title})\n"
            f"- Status: `{app.status.value}`\n"
            f"- Portal Link: {opp.official_application_url or opp.canonical_url}\n"
            f"- Tailored resume attached. Open **Application Center** to review and approve for submission."
        ),
    }


@register_skill("submit_approved_application_batch")
async def handle_submit_approved_application_batch(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Submit approved application batch enforcing explicit approval gate."""
    user_id = args.get("user_id", "default_user")
    batch_id = args.get("batch_id")
    if not batch_id:
        return {"success": False, "error": "batch_id is required."}

    batch = await get_application_batch(batch_id, user_id)
    if not batch:
        return {"success": False, "error": f"Batch '{batch_id}' not found."}

    if batch.get("status") != "APPROVED":
        return {
            "success": False,
            "error": "Approval required: This batch has not been explicitly reviewed and approved by user. Open Application Center to confirm attestations and approve.",
        }

    pref_method = args.get("preferred_method")
    try:
        method_enum = SubmissionMethod(pref_method) if pref_method else SubmissionMethod.MANUAL_HANDOFF
    except ValueError:
        valid = ", ".join(m.value for m in SubmissionMethod)
        return {"success": False, "error": f"Invalid preferred_method '{pref_method}'. Valid values: {valid}."}

    lock = get_batch_lock(batch_id)
    if lock.locked():
        return {"success": False, "error": "Concurrent submission rejected: A submission is already running for this batch."}

    async with lock:
        # Same atomic claim, content-hash and token checks as the HTTP submit route
        claimed = await claim_application_batch_for_submission(batch_id, user_id)
        if not claimed:
            return {
                "success": False,
                "error": "Submission rejected: this batch is already processing or is no longer in APPROVED status.",
            }
        try:
            apps_data = []
            for aid in batch.get("application_ids", []):
                app_rec = await get_career_application_by_id(aid, user_id)
                if app_rec:
                    apps_data.append(app_rec.model_dump())
            token = batch.get("approval_token")
            if not token:
                await release_application_batch_claim(batch_id, user_id, "APPROVED")
                return {"success": False, "error": "Submission blocked: missing approval token. Batch must be re-approved."}
            is_valid, reason = verify_batch_approval_token(
                token, user_id, batch_id, compute_batch_content_hash(apps_data)
            )
            if not is_valid:
                await release_application_batch_claim(batch_id, user_id, "APPROVED")
                return {"success": False, "error": f"Submission blocked: {reason}"}

            results = await execute_batch_submission(user_id, batch, method_enum)
            await finish_application_batch(batch_id, user_id, [r.model_dump() for r in results])
        except Exception:
            logger.exception("Unhandled error executing batch submission %s", batch_id)
            await finish_application_batch(batch_id, user_id, [{
                "application_id": 0,
                "status": "FAILED",
                "message": "Submission execution failed unexpectedly.",
            }])
            return {"success": False, "error": "Submission execution failed. Please try again later."}

    summary_lines = [
        f"✅ **Batch Submission Complete (ID: {batch_id})**",
        f"- Processed: {len(results)} applications",
        f"- Successful / Prepared: {sum(1 for r in results if r.status in {'SUBMITTED', 'MANUAL_SUBMISSION_REQUIRED'})}",
    ]
    for r in results:
        summary_lines.append(f"  • **{r.company_name}** ({r.role_title}): `{r.status}` — {r.message}")

    return {
        "success": True,
        "batch_id": batch_id,
        "results": [r.model_dump() for r in results],
        "summary": "\n".join(summary_lines),
    }


@register_skill("track_career_applications")
async def handle_track_career_applications(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """List and summarize tracked applications across lifecycle."""
    user_id = args.get("user_id", "default_user")
    status_filter = args.get("status")
    apps = await list_career_applications(user_id, status_filter)

    if not apps:
        return {
            "success": True,
            "count": 0,
            "summary": "No active applications found. Use Internship Radar to discover opportunities and prepare applications.",
        }

    lines = [f"📋 **Your Tracked Applications ({len(apps)} total):**"]
    for a in apps[:8]:
        opp = await get_opportunity_by_id(a.opportunity_id, user_id)
        comp = opp.company_name if opp else f"Opportunity #{a.opportunity_id}"
        role = opp.role_title if opp else "Role"
        deadline = f" | Deadline: {a.target_deadline}" if a.target_deadline else ""
        lines.append(f"- **{comp}** — {role} | Status: `{a.status.value}`{deadline}")

    return {
        "success": True,
        "count": len(apps),
        "applications": [a.model_dump() for a in apps],
        "summary": "\n".join(lines),
    }


@register_skill("draft_cover_letter")
async def handle_draft_cover_letter(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Draft a truthful, verified cover letter strictly referencing master projects and skills."""
    user_id = args.get("user_id", "default_user")
    opp_id = args.get("opportunity_id")
    target_comp = args.get("target_company")

    opp = None
    if opp_id:
        try:
            opp_id_int = int(opp_id)
        except (TypeError, ValueError):
            return {"success": False, "error": f"Invalid opportunity_id '{opp_id}': must be a number."}
        opp = await get_opportunity_by_id(opp_id_int, user_id)
    elif target_comp:
        opps, _ = await get_all_opportunities(user_id=user_id, search=target_comp, page=1, page_size=1)
        if opps:
            opp = opps[0]

    if not opp:
        return {
            "success": False,
            "error": "Could not identify target opportunity. Please provide an opportunity ID or company name from Internship Radar.",
        }

    master = await get_master_resume(user_id)
    if not master:
        profile = await get_user_opportunity_profile(user_id) or UserOpportunityProfileIn()
        master = await upsert_master_resume(user_id, build_default_master_from_profile(profile), "Master Resume")

    letter_text, verified_projs, verified_skls = draft_truthful_cover_letter(
        master=master.content,
        opportunity=opp,
        emphasis_projects=args.get("emphasis_projects"),
    )

    # Attach to application if application exists
    from backend.memory.career import get_or_create_career_application
    app = await get_or_create_career_application(user_id, opp.id)
    await update_career_application(app.id, user_id, {"cover_letter": letter_text})

    lines = [
        f"✍️ **Truthful Cover Letter Drafted:** {opp.company_name} — {opp.role_title}",
        f"- **Verified Projects Grounded:** {', '.join(verified_projs) if verified_projs else 'General Profile Highlights'}",
        f"- **Verified Skills Grounded:** {', '.join(verified_skls) if verified_skls else 'General Skills'}",
        "- **Factual Invariant:** Zero unverified qualifications or dates invented.",
        "",
        "```text",
        letter_text,
        "```",
        "You can review or edit this cover letter anytime in **Application Center**.",
    ]

    return {
        "success": True,
        "opportunity": f"{opp.company_name} — {opp.role_title}",
        "cover_letter": letter_text,
        "verified_projects": verified_projs,
        "verified_skills": verified_skls,
        "summary": "\n".join(lines),
    }


@register_skill("check_application_deadlines")
async def handle_check_application_deadlines(args: Dict[str, Any], pool: Any = None) -> Dict[str, Any]:
    """Check upcoming deadlines across tracked applications and verified opportunities."""
    from datetime import date, timedelta
    user_id = args.get("user_id", "default_user")
    days_ahead = int(args.get("days_ahead", 30))
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    apps = await list_career_applications(user_id)
    open_opps, _ = await get_all_opportunities(user_id=user_id, status="OPEN", page=1, page_size=25)

    upcoming: list[dict[str, Any]] = []

    # 1. Tracked application target deadlines
    for a in apps:
        if a.target_deadline and today <= a.target_deadline <= cutoff:
            opp = await get_opportunity_by_id(a.opportunity_id, user_id)
            days_left = (a.target_deadline - today).days
            upcoming.append({
                "type": "Application Target Deadline",
                "company": opp.company_name if opp else f"Opportunity #{a.opportunity_id}",
                "role": opp.role_title if opp else "Role",
                "deadline": a.target_deadline.isoformat(),
                "days_left": days_left,
                "status": a.status.value,
                "portal_url": (opp.official_application_url or opp.canonical_url) if opp else None,
            })

    # 2. Confirmed opportunity close dates
    tracked_opp_ids = {a.opportunity_id for a in apps}
    for opp in open_opps:
        if opp.confirmed_close_date and today <= opp.confirmed_close_date <= cutoff:
            days_left = (opp.confirmed_close_date - today).days
            upcoming.append({
                "type": "Official Closing Date",
                "company": opp.company_name,
                "role": opp.role_title,
                "deadline": opp.confirmed_close_date.isoformat(),
                "days_left": days_left,
                "status": "Tracked" if opp.id in tracked_opp_ids else "Open on Radar",
                "portal_url": opp.official_application_url or opp.canonical_url,
            })

    def _get_days_left(item: dict[str, Any]) -> int:
        val = item.get("days_left")
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
        return 0

    # Sort by days_left ascending
    upcoming.sort(key=_get_days_left)

    if not upcoming:
        msg = f"No deadlines found within the next {days_ahead} days. You can continue discovering opportunities on Internship Radar."
        return {
            "success": True,
            "count": 0,
            "upcoming_deadlines": [],
            "summary": msg,
        }

    lines = [f"⏰ **Upcoming Application Deadlines (Next {days_ahead} Days):**"]
    for item in upcoming[:10]:
        urgency = "🔴 URGENT" if item["days_left"] <= 7 else "🟡 SOON"
        lines.append(
            f"- {urgency}: **{item['company']}** — {item['role']}\n"
            f"  - Deadline: `{item['deadline']}` ({item['days_left']} days left)\n"
            f"  - Status: `{item['status']}` | [Official Portal]({item['portal_url']})"
        )

    return {
        "success": True,
        "count": len(upcoming),
        "upcoming_deadlines": upcoming,
        "summary": "\n".join(lines),
    }
