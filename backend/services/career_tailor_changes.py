"""
Compass - "What changed" summary for a tailored resume (N-007).

Tailoring never adds or rewrites facts: it moves the skills and projects that match the posting to
the front. This module compares the master resume with the tailored copy and describes the
difference in plain words, or says why nothing changed. The result is stored in
`validation_report.diff_summary["what_changed"]` so it travels with the resume.
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend.models_career import ResumeContent, ResumeValidationReport
from backend.models_radar import OpportunityOut

NEVER_ADDS_NOTE = "Tailoring never adds skills or rewrites your achievements. It only puts what matches this posting first."
PREVIEW_SKILLS = 8


def _job_text(opp: OpportunityOut) -> str:
    return f"{opp.role_title} {opp.category or ''} {opp.description or ''}".lower()


def _required(opp: OpportunityOut) -> set[str]:
    if opp.requirements and opp.requirements.required_skills:
        return {s.lower() for s in opp.requirements.required_skills}
    return set()


def _matches(skill: str, required: set[str], job_text: str) -> bool:
    low = skill.lower()
    return low in required or low in job_text


def compute_tailor_changes(master: ResumeContent, tailored: ResumeContent, opp: OpportunityOut) -> Dict[str, Any]:
    """Plain-language description of how `tailored` differs from `master` for `opp`."""
    required, job = _required(opp), _job_text(opp)
    matching = [s for s in master.skills if _matches(s, required, job)]
    moved_up = [s for i, s in enumerate(tailored.skills) if s in master.skills and master.skills.index(s) > i and s in matching]
    master_titles = [p.title for p in master.projects]
    tailored_titles = [p.title for p in tailored.projects]
    projects_reordered = tailored_titles if master_titles != tailored_titles else []
    skills_added = [s for s in tailored.skills if s not in master.skills]
    skills_removed = [s for s in master.skills if s not in tailored.skills]
    summary_changed = (tailored.summary or "") != (master.summary or "")

    lines: List[str] = []
    if moved_up:
        lines.append("Skills moved to the front: " + ", ".join(moved_up[:8]) + ".")
    elif matching:
        lines.append("Your matching skills were already first: " + ", ".join(matching[:6]) + ".")
    if projects_reordered:
        lines.append("Projects reordered, most relevant first: " + ", ".join(projects_reordered[:4]) + ".")
    if skills_added:
        lines.append("Skills added: " + ", ".join(skills_added) + ".")
    if skills_removed:
        lines.append("Skills left out: " + ", ".join(skills_removed) + ".")
    if summary_changed:
        lines.append("Summary changed.")

    changed = bool(moved_up or projects_reordered or skills_added or skills_removed or summary_changed)
    reason = None
    if not changed:
        if not master.skills and not master.projects:
            reason = "Your resume has no skills or projects yet, so there was nothing to reorder. Add some in My resume."
        elif not required and not matching:
            reason = "This posting lists no skills we could match."
        elif matching:
            reason = "Your resume already puts the skills that match this posting first, so nothing needed to move."
        else:
            reason = "None of your listed skills appear in this posting, so nothing was moved."

    return {
        "changed": changed,
        "lines": lines,
        "reason_if_unchanged": reason,
        "skills_added": skills_added,
        "skills_moved_up": moved_up,
        "projects_reordered": projects_reordered,
        "bullets_rephrased": 0,
        "summary_changed": summary_changed,
        "note": NEVER_ADDS_NOTE,
        "preview": {
            "skills": tailored.skills[:PREVIEW_SKILLS],
            "projects": tailored_titles[:4],
            "summary": tailored.summary or "",
        },
    }


def attach_changes(
    report: ResumeValidationReport, master: ResumeContent, tailored: ResumeContent, opp: OpportunityOut
) -> ResumeValidationReport:
    """Store the change summary on the report's diff_summary and return the report."""
    report.diff_summary = {**(report.diff_summary or {}), "what_changed": compute_tailor_changes(master, tailored, opp)}
    return report
