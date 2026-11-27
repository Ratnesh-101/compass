"""Deterministic schedule formatting, real task due-date join, internal agent text scrubbing,
and commit-plan staging helper for Compass agents.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("compass.schedule_deterministic")

# Regex to scrub internal reviewer, critic, and revision artifacts leaking to the user.
# Bounded and unambiguous to avoid any backtracking or ReDoS (CodeQL safe).
_INTERNAL_AGENT_PATTERNS = re.compile(
    r"\b(?:reviewer(?:\x27s)?|critic(?:\x27s|ism)?|revision[s]?|previously approved|per feedback)\b",
    re.IGNORECASE,
)


def _replace_first_table(reply: str, table_md: str) -> Optional[str]:
    """Replace the first markdown table block in reply with table_md (line scan, no regex). None if no table."""
    lines = reply.split("\n")
    start = end = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        is_row = len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|")
        if is_row and start < 0:
            start = i
        if is_row:
            end = i
        elif start >= 0:
            break
    if start < 0:
        return None
    return "\n".join(lines[:start] + [table_md, ""] + lines[end + 1:])



def scrub_internal_agent_text(text: str) -> str:
    """Pure helper that strips sentences containing internal reviewer or critic text.

    Removes any sentence mentioning 'reviewer', 'critic', 'revision', 'previously approved',
    'per feedback', etc. Bounded regex, zero backtracking risk.
    """
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if _INTERNAL_AGENT_PATTERNS.search(line):
            # Split line into individual sentences
            sentences = re.split(r"(?<=[.!?]) +", line)
            kept = [s for s in sentences if not _INTERNAL_AGENT_PATTERNS.search(s)]
            if kept:
                cleaned_lines.append(" ".join(kept))
        else:
            cleaned_lines.append(line)
    res = "\n".join(cleaned_lines)
    res = re.sub(r"\n{3,}", "\n\n", res)
    return res.strip()


def extract_schedule_target_date(query: str, base_date: Optional[date] = None) -> Tuple[Optional[date], Optional[str]]:
    """Determine if query asks for a specific target day (tomorrow, today, or a weekday)."""
    if not query:
        return None, None
    q = query.lower()
    today = base_date or date.today()

    if "tomorrow" in q:
        return today + timedelta(days=1), "Tomorrow"
    if "today" in q or "tonight" in q:
        return today, "Today"

    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    for name, wday in weekdays.items():
        if name in q:
            delta = (wday - today.weekday()) % 7
            target = today + timedelta(days=delta if delta != 0 else 7)
            return target, name.title()

    return None, None


def _format_time_slot(start_iso: Optional[str], end_iso: Optional[str]) -> str:
    """Format scheduled slot into a readable string like 'Thu 09:00 - 10:30'."""
    if not start_iso or not end_iso:
        return "Unscheduled"
    try:
        s_dt = datetime.fromisoformat(str(start_iso).replace("Z", "+00:00"))
        e_dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
        day_str = s_dt.strftime("%a %b %d")
        return f"{day_str} {s_dt:%H:%M} - {e_dt:%H:%M}"
    except Exception:
        return f"{str(start_iso)[:16]} - {str(end_iso)[11:16]}"


def _format_due_date(raw_due: Any) -> str:
    """Extract strictly real due date string from task row (never LLM prose)."""
    if not raw_due:
        return "No Due Date"
    if isinstance(raw_due, (datetime, date)):
        return raw_due.strftime("%Y-%m-%d")
    s = str(raw_due).strip()
    return s[:10] if len(s) >= 10 else s


def build_deterministic_schedule_table(
    scheduled_blocks: List[Dict[str, Any]],
    real_tasks: Dict[int, Dict[str, Any]],
    target_date: Optional[date] = None,
    day_label: Optional[str] = None,
) -> str:
    """Build a deterministic markdown schedule table.

    Due dates and times come ONLY from real task rows (join on task_id).
    For 'tomorrow'/'today'/weekday queries, tasks whose real due date is that day
    (and scheduled blocks of that day) are listed FIRST and never omitted.
    """
    if not scheduled_blocks and not real_tasks:
        return ""

    blocks_by_id: Dict[int, List[Dict[str, Any]]] = {}
    for b in scheduled_blocks:
        tid = b.get("task_id")
        if tid is not None:
            try:
                blocks_by_id.setdefault(int(tid), []).append(b)
            except (ValueError, TypeError):
                pass

    all_task_ids = set(real_tasks.keys()) | set(blocks_by_id.keys())
    combined_rows: List[Dict[str, Any]] = []

    for tid in sorted(all_task_ids):
        task = real_tasks.get(tid, {})
        blocks = blocks_by_id.get(tid, [])
        title = task.get("title") or (blocks[0].get("title") if blocks else f"Task #{tid}")
        domain = task.get("domain") or (blocks[0].get("domain") if blocks else None) or "general"
        priority = str(task.get("priority") or "medium")
        raw_due = task.get("due_date") or task.get("due_at")
        due_str = _format_due_date(raw_due)

        due_date_obj: Optional[date] = None
        if isinstance(raw_due, datetime):
            due_date_obj = raw_due.date()
        elif isinstance(raw_due, date):
            due_date_obj = raw_due
        elif raw_due:
            try:
                due_date_obj = date.fromisoformat(str(raw_due)[:10])
            except Exception:
                pass

        if blocks:
            for b in blocks:
                s_start = b.get("scheduled_start")
                s_end = b.get("scheduled_end")
                slot_date: Optional[date] = None
                if s_start:
                    try:
                        slot_date = datetime.fromisoformat(str(s_start).replace("Z", "+00:00")).date()
                    except Exception:
                        pass

                is_target = False
                if target_date is not None:
                    if due_date_obj == target_date or slot_date == target_date:
                        is_target = True

                combined_rows.append({
                    "task_id": tid,
                    "title": title,
                    "domain": domain,
                    "slot": _format_time_slot(s_start, s_end),
                    "due_date": due_str,
                    "due_date_obj": due_date_obj,
                    "priority": priority,
                    "is_target": is_target,
                })
        else:
            is_target = False
            if target_date is not None and due_date_obj == target_date:
                is_target = True

            combined_rows.append({
                "task_id": tid,
                "title": title,
                "domain": domain,
                "slot": "Unscheduled",
                "due_date": due_str,
                "due_date_obj": due_date_obj,
                "priority": priority,
                "is_target": is_target,
            })

    # Sort rows: Target day items first (is_target=True), then by due_date ASC
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    combined_rows.sort(
        key=lambda r: (
            0 if r["is_target"] else 1,
            r["due_date_obj"] or date.max,
            priority_order.get(str(r["priority"]).lower(), 2),
        )
    )

    header_title = f"### Schedule Plan ({day_label})" if day_label else "### Deterministic Schedule Plan"
    lines = [
        header_title,
        "| Task | Domain | Scheduled Slot | Due Date | Priority |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in combined_rows:
        lines.append(
            f"| {r['title']} | {r['domain'].title()} | {r['slot']} | {r['due_date']} | {r['priority'].capitalize()} |"
        )
    return "\n".join(lines)


def patch_schedule_answer(
    reply: str,
    scheduled_blocks: List[Dict[str, Any]],
    real_tasks: Dict[int, Dict[str, Any]],
    user_goal: str,
    committed: bool = False,
) -> str:
    """Produce deterministically verified schedule answer with honest commit status.

    1. Scrubs internal critic/reviewer text.
    2. Appends or replaces schedule table with deterministic real-task data.
    3. If proposed blocks exist and not committed, ends with honest commit call to action.
    """
    clean_reply = scrub_internal_agent_text(reply)
    target_date, day_label = extract_schedule_target_date(user_goal)
    table_md = build_deterministic_schedule_table(
        scheduled_blocks, real_tasks, target_date=target_date, day_label=day_label
    )

    if table_md:
        replaced = _replace_first_table(clean_reply, table_md)
        clean_reply = replaced if replaced is not None else clean_reply.rstrip() + "\n\n" + table_md

    has_proposed = bool(scheduled_blocks)
    honest_sentence = "Nothing is saved yet. Say 'commit this plan' to put these blocks on your calendar."

    if has_proposed and not committed:
        if honest_sentence not in clean_reply:
            clean_reply = clean_reply.rstrip() + f"\n\n{honest_sentence}"

    from backend.services.action_claim_guard import guard_unbacked_action_claims
    guarded_reply, _ = guard_unbacked_action_claims(clean_reply, committed)

    if has_proposed and not committed and honest_sentence not in guarded_reply:
        guarded_reply = guarded_reply.rstrip() + f"\n\n{honest_sentence}"

    return guarded_reply.strip()


async def fetch_real_tasks_for_schedule(
    pool: Any,
    user_id: Optional[str],
    task_ids: Optional[List[int]] = None,
    include_demo: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """Fetch real task rows joined on task_id directly from the database."""
    if not pool:
        return {}
    from backend.services.ownership import scope_owner
    scoped_user = scope_owner(user_id)
    try:
        async with pool.acquire() as conn:
            if task_ids:
                rows = await conn.fetch(
                    """
                    SELECT id, title, domain, due_date, due_at, status, priority, duration_minutes
                    FROM tasks
                    WHERE deleted_at IS NULL
                      AND id = ANY($1::int[])
                      AND ($2::text IS NULL OR lower(user_id) = lower($2::text))
                    """,
                    task_ids,
                    scoped_user,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, title, domain, due_date, due_at, status, priority, duration_minutes
                    FROM tasks
                    WHERE deleted_at IS NULL
                      AND status != 'completed'
                      AND ($1::text IS NULL OR lower(user_id) = lower($1::text))
                      AND ($2::boolean OR COALESCE(trusted_event_url,'') NOT LIKE 'compass://demo-persona/%')
                    ORDER BY due_date ASC NULLS LAST, priority DESC
                    LIMIT 30
                    """,
                    scoped_user,
                    bool(include_demo),
                )
            return {int(r["id"]): dict(r) for r in rows}
    except Exception as e:
        logger.warning(f"[fetch_real_tasks_for_schedule] Query failed: {e}")
        return {}


async def find_pending_agent_run(
    pool: Any, user_id: Optional[str], conversation_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Find the most recent agent run with pending actions to commit/approve."""
    if not pool:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT run_id, goal, status, accumulated_steps, messages, pending_actions, conversation_id, user_id
                FROM agent_runs
                WHERE ($1::text IS NULL OR lower(user_id) = lower($1::text) OR conversation_id = $2::text)
                  AND jsonb_array_length(COALESCE(pending_actions, '[]'::jsonb)) > 0
                ORDER BY created_at DESC LIMIT 1
                """,
                user_id,
                conversation_id,
            )
            return dict(row) if row else None
    except Exception as e:
        logger.debug(f"Pending agent run lookup failed: {e}")
        return None


async def handle_agent_schedule_synthesis(
    reply: str,
    goal: str,
    proposed_blocks: List[Dict[str, Any]],
    pool: Any,
    user_id: Optional[str],
    run_id: str,
    step_num: int,
) -> Tuple[str, List[Dict[str, Any]], List[Any], List[Dict[str, Any]]]:
    """Process agent answer for scheduling: enforce deterministic real task due dates,
    stage commit_schedule confirm_request, and scrub internal text.
    Returns (cleaned_reply, proposed_blocks, extra_steps, pending_confirmations).
    """
    from backend.agent_types import AgentStep

    is_sched = any(
        k in goal.lower()
        for k in ["schedule", "plan", "tomorrow", "calendar", "weekday", "thursday", "friday", "monday", "routine"]
    )
    extra_steps: List[Any] = []
    pending_cf: List[Dict[str, Any]] = []

    if pool and (proposed_blocks or is_sched):
        if not proposed_blocks and is_sched:
            try:
                from backend.skills.handlers.calendar import handle_propose_schedule
                p_res = await handle_propose_schedule({"user_id": user_id}, pool)
                proposed_blocks = p_res.get("data", {}).get("scheduled") or []
            except Exception as ex:
                logger.debug(f"Fallback propose failed: {ex}")

        t_ids = [b["task_id"] for b in proposed_blocks if "task_id" in b] or None
        real_tasks = await fetch_real_tasks_for_schedule(pool, user_id, t_ids, include_demo=False)
        clean_reply = patch_schedule_answer(reply, proposed_blocks, real_tasks, goal, committed=False)

        if proposed_blocks:
            step_num += 1
            c_args = {"assignments": proposed_blocks, "rationale": "Schedule plan proposed by Compass Agent."}
            c_step = AgentStep(
                type="confirm_request",
                content="Say 'commit this plan' to put these blocks on your calendar.",
                tool_name="commit_schedule",
                tool_args=c_args,
                step_number=step_num,
                run_id=run_id,
                model_tier="Human Authorization Gate",
                metadata={"scheduled": proposed_blocks},
            )
            extra_steps.append(c_step)
            from backend.agent_pending import register_pending_action
            act_id = await register_pending_action(pool, run_id, user_id or "default_user", "commit_schedule", c_args)
            pending_cf.append({"action_id": act_id, "tool": "commit_schedule", "args": c_args})
    else:
        clean_reply = scrub_internal_agent_text(reply)

    return clean_reply, proposed_blocks, extra_steps, pending_cf


__all__ = [
    "scrub_internal_agent_text",
    "extract_schedule_target_date",
    "build_deterministic_schedule_table",
    "patch_schedule_answer",
    "fetch_real_tasks_for_schedule",
    "find_pending_agent_run",
    "handle_agent_schedule_synthesis",
]

