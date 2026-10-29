"""
Compass — Task and Project Management Skill Handlers.
"""

from typing import Any, Dict, List, Optional
import logging
import re
from datetime import datetime, date, timedelta

from backend.services.task_scope import list_chat_tasks
from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.tasks")


def prioritize_tasks(tasks: List[Dict[str, Any]], target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Prioritize tasks according to Phase 4 rules:
    1. Overdue tasks (due_date < today and status != 'done')
    2. Tasks due today (due_date == today and status != 'done')
    3. Tasks due soon (today < due_date <= today + 7 days)
    4. Explicit high / urgent priority
    5. Other open tasks
    """
    today = target_date or date.today()

    def score_task(t: Dict[str, Any]) -> tuple:
        due = t.get("due_date")
        if isinstance(due, str):
            try:
                due = datetime.strptime(due[:10], "%Y-%m-%d").date()
            except Exception:
                due = None
        status = str(t.get("status") or "open").lower()
        priority = str(t.get("priority") or "medium").lower()

        if status == "done":
            tier = 5
        elif due and due < today:
            tier = 0  # Overdue
        elif due and due == today:
            tier = 1  # Due today
        elif due and due <= today + timedelta(days=7):
            tier = 2  # Due soon
        elif priority in ("urgent", "high"):
            tier = 3  # High/urgent priority
        else:
            tier = 4  # Other open tasks

        prio_weight = {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 2)
        due_sort = due or date.max
        return (tier, prio_weight, due_sort, t.get("id") or 0)

    return sorted(tasks, key=score_task)


def build_daily_roadmap(
    tasks: List[Dict[str, Any]],
    target_date: Optional[date] = None,
    tone: Optional[str] = None,
) -> str:
    """Synthesize an actionable, structured step-by-step daily roadmap from task records."""
    today = target_date or date.today()
    prioritized = prioritize_tasks(tasks, today)

    active_tasks = [t for t in prioritized if str(t.get("status", "")).lower() != "done"]
    if not active_tasks:
        clean_tone = (tone or "").strip().lower()
        if clean_tone == "brief":
            return "No pending tasks today. All clear!"
        if clean_tone == "exploratory":
            return (
                "You have no pending tasks requiring attention today. Your workspace schedule is clear of immediate deadlines. "
                "This provides an opportune strategic window to review upcoming milestones or outline new project goals. "
                "Would you like to examine your project timeline or add new tasks?"
            )
        return "You have no pending tasks requiring attention today. All clear!"

    top_tasks = active_tasks[:6]
    total_count = len(active_tasks)

    overdue_count = sum(
        1 for t in active_tasks
        if t.get("due_date") and (
            (isinstance(t["due_date"], date) and t["due_date"] < today)
            or (isinstance(t["due_date"], str) and t["due_date"][:10] < today.isoformat())
        )
    )
    due_today_count = sum(
        1 for t in active_tasks
        if t.get("due_date") and (
            (isinstance(t["due_date"], date) and t["due_date"] == today)
            or (isinstance(t["due_date"], str) and t["due_date"][:10] == today.isoformat())
        )
    )

    clean_tone = (tone or "").strip().lower()
    if clean_tone == "brief":
        first = top_tasks[0]
        due_lbl = f" (Due: {first.get('due_date')})" if first.get("due_date") else ""
        return (
            f"You have **{total_count}** active task(s). Start with: **{first['title']}**{due_lbl}."
        )

    lines = []
    lines.append("### Your plan for today")
    summary_parts = []
    if due_today_count:
        summary_parts.append(f"**{due_today_count}** task(s) due today")
    if overdue_count:
        summary_parts.append(f"**{overdue_count}** overdue item(s)")
    summary_text = f"You have {total_count} total task(s) in your workspace"
    if summary_parts:
        summary_text += f", with {', '.join(summary_parts)}."
    else:
        summary_text += f". Prioritizing the top {len(top_tasks)} items needing attention."
    lines.append(summary_text)
    lines.append("")

    # 1. Start here
    first = top_tasks[0]
    due_label = str(first.get("due_date")) if first.get("due_date") else "No due date"
    prio_label = first.get("priority", "medium").title()
    domain_label = first.get("domain", "general").title()
    lines.append("### 1. Start here")
    lines.append(f"**{first['title']}**")
    lines.append(f"*{domain_label} · Priority: {prio_label} · Due: {due_label}*")
    why = (
        "Highest immediate priority with pressing deadline or dependency."
        if (overdue_count or due_today_count)
        else "Recommended lead task to establish momentum."
    )
    lines.append(why)
    lines.append("")

    # 2. Next
    if len(top_tasks) > 1:
        second = top_tasks[1]
        due_label2 = str(second.get("due_date")) if second.get("due_date") else "No due date"
        prio_label2 = second.get("priority", "medium").title()
        domain_label2 = second.get("domain", "general").title()
        lines.append("### 2. Next")
        lines.append(f"**{second['title']}**")
        lines.append(f"*{domain_label2} · Priority: {prio_label2} · Due: {due_label2}*")
        lines.append("Follow up immediately after completing the lead task.")
        lines.append("")

    # 3. Continue
    if len(top_tasks) > 2:
        lines.append("### 3. Continue")
        for t in top_tasks[2:]:
            d_lbl = str(t.get("due_date")) if t.get("due_date") else "No due date"
            p_lbl = t.get("priority", "medium").title()
            dom_lbl = t.get("domain", "general").title()
            lines.append(f"- **{t['title']}** ({dom_lbl} · {p_lbl} · Due: {d_lbl})")
        lines.append("")

    # Suggested schedule (explicitly estimates)
    lines.append("### Suggested schedule")
    lines.append("*Estimated focus blocks (adapt based on your actual availability):*")
    blocks = [
        ("Morning (09:00 - 11:30)", top_tasks[0]["title"]),
    ]
    if len(top_tasks) > 1:
        blocks.append(("Midday (12:30 - 14:30)", top_tasks[1]["title"]))
    if len(top_tasks) > 2:
        rem_titles = ", ".join(f"'{t['title']}'" for t in top_tasks[2:4])
        blocks.append(("Afternoon (15:00 - 17:00)", rem_titles))
    for time_slot, item_title in blocks:
        lines.append(f"- **{time_slot}**: {item_title}")
    lines.append("")

    # Before you finish
    lines.append("### Before you finish")
    lines.append("- [ ] Review completed tasks and update statuses")
    rem_count = max(0, total_count - len(top_tasks))
    if rem_count > 0:
        lines.append(f"- [ ] Check remaining {rem_count} task(s) in Timeline")
    lines.append("")

    # Exploratory addition: in-depth context and strategic trade-offs
    if clean_tone == "exploratory":
        lines.append("### Context & Deep Dive")
        lines.append("- **Strategic Alignment**: Focusing on core milestones unlocks prerequisite work across your active projects.")
        lines.append("- **Energy & Pacing**: Tackle cognitively intensive tasks during your peak focus window, leaving routine admin for buffer periods.")
        lines.append("- **Schedule Adaptability**: If unexpected blockers arise, shift the secondary focus block rather than delaying the lead deliverable.")
        lines.append("")

    # Next action
    lines.append("### Next action")
    lines.append("Would you like me to commit this focus schedule to your calendar, or filter by a specific domain like **Coursework** or **Hackathon**?")

    return "\n".join(lines)


def _is_same_deliverable(s1_raw: str, s2_raw: str) -> bool:
    """Determine whether two subject strings reliably refer to the same deliverable."""
    n1 = re.sub(r'[^a-z0-9]', '', s1_raw.lower())
    n2 = re.sub(r'[^a-z0-9]', '', s2_raw.lower())
    if not n1 or not n2 or len(n1) < 3 or len(n2) < 3:
        return False
    if n1 == n2:
        return True
    # Substantial word token overlap
    w1 = set(re.findall(r'[a-z0-9]{3,}', s1_raw.lower()))
    w2 = set(re.findall(r'[a-z0-9]{3,}', s2_raw.lower()))
    if w1 and w2:
        common = w1 & w2
        min_len = min(len(w1), len(w2))
        if len(common) >= 2 and (len(common) / min_len >= 0.7):
            return True
        if min_len == 1 and len(common) == 1 and len(next(iter(common))) >= 6:
            return True
    return False


def _parse_memory_deadline_entry(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single line from memory context into source, subject (deliverable name), and deadline."""
    line = line.strip()
    if not line:
        return None

    # Format A: Orchestrator-injected task summary:
    # e.g., "- Review RISC-V pipeline hazards lecture (coursework) | Due: 2026-09-03 | 60m | medium"
    # or "- Title | Due: 2026-09-03"
    orch_match = re.match(
        r"^[-*]\s*(?P<title>.+?)(?:\s*\((?P<domain>[^)]+)\))?\s*\|\s*Due:\s*(?P<due>[^|]+)(?:\s*\|\s*(?P<extra>.*))?$",
        line,
        re.IGNORECASE,
    )
    if orch_match:
        title = orch_match.group("title").strip()
        due_val = orch_match.group("due").strip()
        if not due_val or due_val.lower() in ("unscheduled", "none", "null"):
            return None
        return {
            "source": f"Workspace Task ({title})",
            "subject": title,
            "deadline": due_val,
            "full": line,
        }

    # Format B: Key-value source format, e.g.:
    # "Course Syllabus: CS 61C Homework due at 5:00 PM."
    # "Task Tracker: CS 61C Homework recorded due at 11:59 PM."
    if ":" in line:
        src, _, detail = line.partition(":")
        src = src.strip().lstrip("-* ").strip()
        detail = detail.strip()
    else:
        src = "Record"
        detail = line.lstrip("-* ").strip()

    time_match = re.search(
        r'\b(\d{1,2}(?::\d{2})?\s*(?:[apAP]\.?[mM]\.?|[apAP][mM]))\b|\b(\d{1,2}:\d{2})\b',
        detail
    )
    date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', detail)
    deadline_val = (time_match.group(0).strip() if time_match else None) or (date_match.group(0).strip() if date_match else None)
    if not deadline_val:
        return None

    cleaned = re.sub(
        r'\b(due|at|recorded|deadline|due at|recorded due at)\b',
        '', detail, flags=re.IGNORECASE
    )
    if time_match:
        cleaned = cleaned.replace(time_match.group(0), '')
    if date_match:
        cleaned = cleaned.replace(date_match.group(0), '')
    cleaned = re.sub(r'[\|\(\)\.\,\:\;]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return {
        "source": src or "Record",
        "subject": cleaned,
        "deadline": deadline_val,
        "full": detail,
    }


def _extract_conversational_deadlines(
    history: Optional[List[Dict[str, str]]],
    subject_keywords: Optional[List[str]] = None,
) -> List[str]:
    """Extract distinct deadline phrases mentioned in recent conversation history relevant to the subject."""
    if not history:
        return []
    candidates: List[str] = []
    seen = set()

    # Pattern matching deadline expressions:
    # e.g., "Friday at 5 PM", "Friday 5 PM", "October 24 at 3 PM", "2026-10-24 at 15:00", "2026-10-24"
    pattern = re.compile(
        r'\b(?:(?:next\s+|this\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|'
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|'
        r'sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,\s*\d{4})?|'
        r'\d{4}-\d{2}-\d{2})'
        r'(?:\s+(?:at\s+|by\s+)?\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?|[ap]m))?',
        re.IGNORECASE
    )

    for h in reversed(history):
        content = h.get("content", "")
        if not content:
            continue
        c_lower = content.lower()
        if subject_keywords:
            if not any(kw in c_lower for kw in subject_keywords):
                continue
        elif not any(term in c_lower for term in ("deadline", "due", "deliverable", "task", "submit", "submission", "demo", "video")):
            continue

        for m in pattern.finditer(content):
            phrase = m.group(0).strip()
            norm = re.sub(r'\s+', ' ', phrase.lower())
            if norm not in seen:
                seen.add(norm)
                candidates.append(phrase)

    return candidates


def detect_deadline_discrepancies(
    tasks: Optional[List[Dict[str, Any]]] = None,
    memory_context: Optional[str] = None,
    user_message: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Detect conflicting or contradictory deadline information across memory sources or task records."""
    # 1. Parse memory_context for conflicting sources
    if memory_context:
        lines = [line.strip() for line in memory_context.split("\n") if line.strip()]
        parsed_entries = []
        for line in lines:
            entry = _parse_memory_deadline_entry(line)
            if entry:
                parsed_entries.append(entry)

        for i in range(len(parsed_entries)):
            for j in range(i + 1, len(parsed_entries)):
                e1 = parsed_entries[i]
                e2 = parsed_entries[j]
                if _is_same_deliverable(e1["subject"], e2["subject"]) and e1["deadline"] != e2["deadline"]:
                    return {
                        "task_name": e1["subject"] or e2["subject"] or "Task",
                        "conflicting_values": [
                            {"source": e1["source"], "value": e1["deadline"], "detail": e1["full"]},
                            {"source": e2["source"], "value": e2["deadline"], "detail": e2["full"]},
                        ],
                    }

    # 2. Check for contradictory records within tasks for the same task
    if tasks and len(tasks) > 1:
        by_title: Dict[str, List[Dict[str, Any]]] = {}
        for t in tasks:
            if str(t.get("status", "")).lower() == "done":
                continue
            norm_t = re.sub(r'[^a-zA-Z0-9]', '', t.get("title", "").lower())
            if norm_t:
                by_title.setdefault(norm_t, []).append(t)

        for norm_t, group in by_title.items():
            if len(group) > 1:
                dates = {str(t.get("due_date")) for t in group if t.get("due_date")}
                if len(dates) > 1:
                    vals = []
                    for t in group:
                        d_val = str(t.get("due_date") or "unscheduled")
                        vals.append({"source": f"Task #{t.get('id', '')} ({t.get('title')})", "value": d_val, "detail": f"Status: {t.get('status')}"})
                    return {
                        "task_name": group[0]["title"],
                        "conflicting_values": vals,
                    }

    return None


def format_conflict_discrepancy(conflict: Dict[str, Any]) -> str:
    """Format an honest, transparent discrepancy explanation without arbitrary resolution."""
    task = conflict.get("task_name", "the requested task")
    lines = [
        f"⚠️ **Conflicting Deadline Information Detected for {task}**:",
        "The available records contain contradictory deadline information:",
    ]
    vals = []
    for cv in conflict.get("conflicting_values", []):
        src = cv.get("source", "Record")
        val = cv.get("value", "")
        vals.append(val)
        lines.append(f"- **{src}**: {val}")
    lines.append("")

    earlier_hint = ""
    if any("5:00" in v for v in vals):
        earlier_hint = " (such as 5:00 PM)"

    lines.append(
        "The available sources disagree on the exact submission cutoff, and neither can be verified as authoritative "
        "from the records alone. To avoid late penalties, I recommend aiming for the earlier submission deadline"
        f"{earlier_hint} and verifying the official cutoff on your course portal (such as Gradescope or Canvas) "
        "or confirming directly with the course staff."
    )
    return "\n".join(lines)


def _safe_error_message(prefix: str, exc: Exception) -> str:
    """Format user-safe error message without leaking credentials or raw DSN."""
    err_str = str(exc)
    clean_err = re.sub(r'postgres(?:ql)?://[^\s\'"]+', '[REDACTED_DATABASE_URL]', err_str)
    clean_err = re.sub(r'password\s*=\s*[\'"][^\'"]+[\'"]', 'password=[REDACTED]', clean_err, flags=re.IGNORECASE)
    if '[REDACTED_DATABASE_URL]' in clean_err:
        return f"{prefix}: Database connection failed. Please verify database connectivity."
    return f"{prefix}: {clean_err}"


@register_skill("query_tasks")
async def handle_query_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query tasks table via structured.list_tasks and format summary."""
    from backend.memory import structured
    domain = args.get("domain")
    status = args.get("status")
    user_id = args.get("user_id")

    try:
        async with pool.acquire() as conn:
            tasks = await list_chat_tasks(conn, args, domain=domain, status=status)
    except Exception as e:
        logger.error("Failed to query tasks: %s", e)
        clean_msg = _safe_error_message("Failed to retrieve tasks", e)
        return {
            "success": False,
            "response": clean_msg,
            "error": "database_error",
            "data": [],
        }

    # Optional project filter
    project = args.get("project")
    if project:
        p_clean = project.strip().lower()
        tasks = [
            t for t in tasks
            if p_clean in t.get("title", "").lower()
            or (t.get("project_name") and p_clean in t["project_name"].lower())
            or (t.get("notes") and p_clean in t["notes"].lower())
        ]

    # Check for contradictory / conflicting deadline information
    conflict = detect_deadline_discrepancies(
        tasks=tasks,
        memory_context=args.get("memory_context"),
        user_message=args.get("user_message") or args.get("message") or args.get("query"),
    )

    count = len(tasks)
    d_str = f" in {domain.upper()}" if domain else ""
    s_str = f" with status '{status}'" if status else ""

    # Check conversation history for explicitly mentioned deadlines
    history = args.get("history") or []
    user_msg = str(args.get("user_message") or args.get("message") or args.get("query") or "").lower()
    stopwords = {"when", "is", "that", "the", "a", "an", "my", "our", "due", "again", "deadline", "date", "time", "what", "to", "for", "at", "by", "of", "in"}
    subj_words = [w for w in re.findall(r'[a-z0-9_-]+', user_msg) if len(w) > 2 and w not in stopwords]
    conv_deadlines = _extract_conversational_deadlines(history, subj_words) if history else []

    # Check if request has roadmap or planning intent
    req_context = " ".join([
        str(args.get("intent") or ""),
        str(args.get("mode") or ""),
        str(args.get("goal") or ""),
        str(args.get("query") or ""),
        str(args.get("message") or ""),
        str(args.get("user_message") or ""),
    ]).lower()

    is_roadmap = any(
        kw in req_context
        for kw in (
            "roadmap", "plan", "today", "prioritize", "what should i do",
            "step-by-step", "step by step", "actionable", "attention",
            "work on first", "start with", "first",
        )
    )

    tone = (args.get("tone") or "").strip().lower()
    prioritized = prioritize_tasks(tasks, target_date=date.today())

    if is_roadmap:
        summary = build_daily_roadmap(prioritized, target_date=date.today(), tone=tone)
        return {
            "response": summary,
            "data": prioritized,
        }

    if count == 0:
        if conflict:
            return {
                "response": format_conflict_discrepancy(conflict),
                "data": [],
            }
        # Check if conversation history explicitly contains the answer to a follow-up deadline question
        if conv_deadlines and any(w in user_msg for w in ("when", "due", "deadline", "date", "time")):
            if len(conv_deadlines) > 1:
                options_str = " and ".join(f"'{d}'" for d in conv_deadlines)
                clarification = (
                    f"Earlier in our conversation, multiple possible deadlines were mentioned: {options_str}. "
                    f"Could you clarify which deadline you are aiming for?"
                )
                return {"response": clarification, "data": []}
            return {
                "response": (
                    f"Based on our earlier conversation, the deadline was noted as {conv_deadlines[0]}. "
                    f"Note that this was noted conversationally and has not yet been saved as a database task."
                ),
                "data": [],
            }
        if tone == "brief":
            zero_resp = f"Found 0 tasks{d_str}{s_str}."
        elif tone == "exploratory":
            zero_resp = (
                f"Found 0 task(s){d_str}{s_str}. No matching tasks were found in your workspace schedule. "
                f"You can add new deadlines anytime or import items from your project timeline to begin tracking."
            )
        else:
            zero_resp = f"Found 0 task(s){d_str}{s_str}."
        return {
            "response": zero_resp,
            "data": [],
        }

    # If database has matching tasks and user asks for a deadline, check for discrepancy between DB and conversation
    if conv_deadlines and any(w in user_msg for w in ("when", "due", "deadline", "date", "time")):
        matching_db_tasks = [
            t for t in tasks
            if any(kw in t.get("title", "").lower() for kw in subj_words)
        ] if subj_words else tasks[:1]
        if matching_db_tasks:
            target_t = matching_db_tasks[0]
            db_due = str(target_t.get("due_date") or "unscheduled")
            if not any(d.lower() in db_due.lower() or db_due.lower() in d.lower() for d in conv_deadlines):
                disc_lines = [
                    f"⚠️ **Discrepancy Detected between Conversation and Database Records for '{target_t['title']}'**:",
                    f"- **Conversation context**: {conv_deadlines[0]}",
                    f"- **Database record**: {db_due}",
                    "The database record is currently active, but our earlier conversation mentioned a different deadline. Would you like me to update the task to match the conversation?",
                ]
                return {"response": "\n".join(disc_lines), "data": tasks}

    top_tasks = prioritized[:6]
    if tone == "brief" and top_tasks:
        due_str = str(top_tasks[0].get("due_date")) if top_tasks[0].get("due_date") else "No due date"
        base_summary = f"Found **{count}** task(s){d_str}{s_str}. Immediate lead item: **{top_tasks[0]['title']}** (Due: {due_str})."
    else:
        task_lines = []
        for t in top_tasks:
            due_str = str(t.get("due_date")) if t.get("due_date") else "No due date"
            dom = t.get("domain", "general").title()
            prio = t.get("priority", "medium").title()
            stat = t.get("status", "open")
            task_lines.append(f"- **{t['title']}** (`{dom}` · {stat} · Due: {due_str} · Priority: {prio})")

        more_notice = (
            f"\n\n*Showing top {len(top_tasks)} prioritized items out of {count} total matching task(s). "
            f"You can view the full list in the Timeline view.*"
            if count > len(top_tasks)
            else ""
        )
        base_summary = f"Found **{count}** task(s){d_str}{s_str}:\n\n" + "\n".join(task_lines) + more_notice

        if tone == "exploratory":
            base_summary += (
                "\n\n### Backlog Insights & Planning Guidance\n"
                "- **Prioritization**: High-priority tasks are scheduled first to prevent last-minute deadline compression.\n"
                "- **Domain Balance**: Reviewing tasks across active projects helps maintain continuous momentum without burnout."
            )

    if conflict:
        summary = format_conflict_discrepancy(conflict) + "\n\n" + base_summary
    else:
        summary = base_summary

    return {
        "response": summary,
        "data": prioritized,
    }


@register_skill("query_coursework_tasks")
async def handle_query_coursework_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query coursework tasks such as CS 61C labs, reports, and homework."""
    from backend.memory import structured
    status = args.get("status")
    course = args.get("course")
    user_id = args.get("user_id")

    try:
        async with pool.acquire() as conn:
            tasks = await list_chat_tasks(conn, args, domain="coursework", status=status)
    except Exception as e:
        logger.error("Failed to query coursework tasks: %s", e)
        clean_msg = _safe_error_message("Failed to retrieve coursework tasks", e)
        return {
            "success": False,
            "response": clean_msg,
            "error": "database_error",
            "data": {"tasks": [], "count": 0},
        }

    matching_tasks = tasks
    if course:
        c_clean = course.strip().lower()
        matching_tasks = [
            t for t in tasks
            if c_clean in t.get("title", "").lower()
            or (t.get("project_name") and c_clean in t["project_name"].lower())
            or (t.get("notes") and c_clean in t["notes"].lower())
        ]

    # Check for contradictory / conflicting deadline information
    conflict = detect_deadline_discrepancies(
        tasks=matching_tasks,
        memory_context=args.get("memory_context"),
        user_message=args.get("user_message") or args.get("course"),
    )

    count = len(matching_tasks)
    c_str = f" for '{course}'" if course and count > 0 else ""

    if count == 0:
        if conflict:
            summary = format_conflict_discrepancy(conflict)
        else:
            summary = f"📚 **Coursework**: Found 0 matching coursework task(s){c_str}."
        return {"response": summary, "data": {"tasks": [], "count": 0}}

    prioritized = prioritize_tasks(matching_tasks, target_date=date.today())
    top_tasks = prioritized[:6]
    task_lines = []
    for t in top_tasks:
        due_str = str(t.get("due_date")) if t.get("due_date") else "No due date"
        prio = str(t.get("priority") or "medium").title()
        stat = str(t.get("status") or "open")
        task_lines.append(f"- **{t['title']}** (`coursework` · {stat} · Due: {due_str} · Priority: {prio})")

    more_notice = (
        f"\n\n*Showing top {len(top_tasks)} prioritized items out of {count} total matching coursework task(s). "
        f"You can view the full list in the Timeline view.*"
        if count > len(top_tasks)
        else ""
    )
    base_summary = f"📚 **Coursework**: Found **{count}** task(s){c_str}:\n\n" + "\n".join(task_lines) + more_notice

    if conflict:
        summary = format_conflict_discrepancy(conflict) + "\n\n" + base_summary
    else:
        summary = base_summary

    return {"response": summary, "data": {"tasks": matching_tasks, "count": count}}


@register_skill("get_hackathon_deadlines")
async def handle_get_hackathon_deadlines(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Retrieve urgent hackathon deliverables and demo benchmark deadlines."""
    from backend.memory import structured
    project = args.get("project")
    user_id = args.get("user_id")

    try:
        async with pool.acquire() as conn:
            tasks = await list_chat_tasks(conn, args, domain="hackathon")
    except Exception as e:
        logger.error("Failed to query hackathon deadlines: %s", e)
        clean_msg = _safe_error_message("Failed to retrieve hackathon deadlines", e)
        return {
            "success": False,
            "response": clean_msg,
            "error": "database_error",
            "data": {"tasks": [], "count": 0},
        }

    if project:
        p_clean = project.strip().lower()
        tasks = [
            t for t in tasks
            if p_clean in t.get("title", "").lower()
            or (t.get("project_name") and p_clean in t["project_name"].lower())
            or (t.get("notes") and p_clean in t["notes"].lower())
        ]

    count = len(tasks)
    p_str = f" for '{project}'" if project else ""
    if count == 0:
        summary = f"🚀 **Hackathon**: Found 0 active hackathon deliverable(s){p_str}."
        return {"response": summary, "data": {"tasks": [], "count": 0}}

    prioritized = prioritize_tasks(tasks, target_date=date.today())
    top_tasks = prioritized[:6]
    task_lines = []
    for t in top_tasks:
        due_str = str(t.get("due_date")) if t.get("due_date") else "No due date"
        prio = str(t.get("priority") or "medium").title()
        stat = str(t.get("status") or "open")
        task_lines.append(f"- **{t['title']}** (`hackathon` · {stat} · Due: {due_str} · Priority: {prio})")

    more_notice = (
        f"\n\n*Showing top {len(top_tasks)} prioritized deliverables out of {count} total matching hackathon item(s). "
        f"You can view the full list in the Timeline view.*"
        if count > len(top_tasks)
        else ""
    )
    summary = f"🚀 **Hackathon**: Found **{count}** active deliverable(s){p_str}:\n\n" + "\n".join(task_lines) + more_notice
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


@register_skill("add_task")
async def handle_add_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Add a new task via structured.create_task."""
    from backend.memory import structured
    from backend.services.ownership import scope_owner

    title = args.get("title", "Untitled Task")
    domain = args.get("domain", "general")
    if domain not in {"hackathon", "coursework", "code", "general"}:
        domain = "general"

    project_name = args.get("project")
    due_str = args.get("due_date")
    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(str(due_str)[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    priority = args.get("priority", "medium")
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"

    status = args.get("status", "open")
    if status not in {"open", "in_progress", "done", "overdue"}:
        status = "open"

    notes = args.get("notes")
    shift_existing = bool(args.get("shift_existing", False))
    allow_different_thing = bool(args.get("allow_different_thing", False))
    allow_duplicate = bool(args.get("allow_duplicate", False))

    try:
        user_id = args.get("user_id")
        async with pool.acquire() as conn:
            existing_tasks = await list_chat_tasks(conn, args)
            exact_matches = [
                t for t in existing_tasks
                if t["title"].strip().lower() == title.lower()
                and (
                    (t.get("due_date") is None and due_date is None)
                    or (t.get("due_date") == due_date)
                )
                and t.get("status") != "done"
            ]
            if exact_matches and not allow_duplicate:
                ex = exact_matches[0]
                d_str = ex.get("due_date") or "unscheduled"
                return {
                    "response": (
                        f"⚠️ A deadline with the exact same name '{ex['title']}' and due date ({d_str}) "
                        f"already exists in your schedule. You cannot add the exact same deadline multiple times. "
                        f"I can inspect your schedules to see when you have free slots or help you rebalance your tasks."
                    ),
                    "data": {
                        "error": "duplicate_exact_deadline",
                        "existing_task_id": ex["id"],
                        "title": ex["title"],
                        "due_date": str(d_str),
                    },
                }

            same_name_matches = [
                t for t in existing_tasks
                if t["title"].strip().lower() == title.lower()
                and t.get("status") != "done"
            ]
            if same_name_matches and not allow_different_thing and not allow_duplicate:
                ex = same_name_matches[0]
                old_d = ex.get("due_date") or "unscheduled"
                new_d = due_date or "unscheduled"
                if shift_existing:
                    updated = await structured.update_task(
                        conn,
                        ex["id"],
                        owner_id=scope_owner(args.get("user_id")),
                        due_date=due_date,
                        priority=priority,
                        notes=notes or ex.get("notes"),
                    )
                    return {
                        "response": f"Shifted existing deadline '{ex['title']}' from {old_d} to {new_d}.",
                        "data": updated,
                    }
                else:
                    return {
                        "response": (
                            f"⚠️ A deadline with the name '{ex['title']}' already exists, scheduled for {old_d}. "
                            f"Would you like me to shift your existing deadline to {new_d}, or is this for a completely different thing? "
                            f"I can also look into your schedules to find an optimal slot without clashes."
                        ),
                        "data": {
                            "warning": "duplicate_name",
                            "existing_task_id": ex["id"],
                            "existing_due_date": str(old_d),
                            "proposed_due_date": str(new_d),
                            "action_required": "confirm_shift_or_different",
                        },
                    }

            project_id = None
            if project_name:
                proj = await structured.get_or_create_project(conn, name=project_name, domain=domain)
                project_id = proj.get("id")

            task_record = await structured.create_task(
                conn,
                domain=domain,
                title=title,
                project_id=project_id,
                due_date=due_date,
                status=status,
                priority=priority,
                notes=notes,
                user_id=user_id,
            )
            dur_arg = args.get("duration_minutes")
            if dur_arg:
                try:
                    await structured.update_task(conn, task_record["id"], duration_minutes=int(dur_arg))
                    task_record["duration_minutes"] = int(dur_arg)
                except Exception as dex:
                    logger.debug(f"Could not persist duration_minutes: {dex}")

            # Proactive Cognitive Conflict Detection
            conflict_info = None
            try:
                from backend.services.scheduler import check_proactive_cognitive_conflicts
                conflict_info = check_proactive_cognitive_conflicts(
                    proposed_task={
                        "id": task_record.get("id"),
                        "title": title,
                        "domain": domain,
                        "due_date": str(due_date) if due_date else None,
                        "priority": priority,
                        "notes": notes,
                        "duration_minutes": task_record.get("duration_minutes"),
                    },
                    existing_tasks=existing_tasks,
                )
            except Exception as conf_err:
                logger.debug(f"Conflict detection skipped: {conf_err}")

        base_summary = f"Added task #{task_record.get('id')}: '{title}' in {domain}."
        if conflict_info and conflict_info.get("has_conflict"):
            final_summary = f"{base_summary}\n\n{conflict_info['alert_message']}"
            return {
                "response": final_summary,
                "data": {
                    **task_record,
                    "cognitive_conflict": conflict_info,
                },
            }

        return {
            "response": base_summary,
            "data": task_record,
        }
    except Exception as e:
        logger.warning(f"Failed to add task: {e}")
        return {"response": f"Failed to add task: {e}", "data": {"error": str(e)}}


@register_skill("update_task_status")
async def handle_update_task_status(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Update the status of an existing task."""
    from backend.memory import structured
    from backend.services.ownership import scope_owner
    task_id = args.get("task_id")
    status = args.get("status") or "open"

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    try:
        async with pool.acquire() as conn:
            updated = await structured.update_task(
                conn, int(task_id), owner_id=scope_owner(args.get("user_id")), status=status
            )
        if updated:
            return {
                "response": f"Updated task #{task_id} status to '{status}'.",
                "data": updated,
            }
        return {"response": f"Task #{task_id} not found.", "data": {}}
    except Exception as e:
        return {"response": f"Failed to update task status: {e}", "data": {"error": str(e)}}


@register_skill("edit_task")
async def handle_edit_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Edit an existing task's title, due date, priority, or notes."""
    from backend.memory import structured
    from backend.services.ownership import scope_owner
    task_id = args.get("task_id")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    update_fields: Dict[str, Any] = {}
    if "title" in args:
        update_fields["title"] = args["title"]
    if "due_date" in args and args["due_date"] is None:
        update_fields["due_date"] = None
    elif "due_date" in args:
        try:
            update_fields["due_date"] = datetime.strptime(args["due_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return {"response": f"Invalid date format: {args['due_date']}. Use YYYY-MM-DD.", "data": {}}
    if "priority" in args:
        update_fields["priority"] = args["priority"]
    if "notes" in args:
        update_fields["notes"] = args["notes"]

    if not update_fields:
        return {"response": "No fields to update. Provide title, due_date, priority, or notes.", "data": {}}

    try:
        async with pool.acquire() as conn:
            updated = await structured.update_task(
                conn, int(task_id), owner_id=scope_owner(args.get("user_id")), **update_fields
            )
        if updated:
            fields_str = ", ".join(f"{k}={v}" for k, v in update_fields.items())
            return {
                "response": f"Updated task #{task_id}: {fields_str}.",
                "data": updated,
            }
        return {"response": f"Task #{task_id} not found.", "data": {}}
    except Exception as e:
        return {"response": f"Failed to edit task: {e}", "data": {"error": str(e)}}


@register_skill("delete_task")
async def handle_delete_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Delete a task by ID."""
    from backend.memory import structured
    from backend.services.ownership import scope_owner
    task_id = args.get("task_id")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    try:
        async with pool.acquire() as conn:
            deleted = await structured.delete_task(
                conn, int(task_id), owner_id=scope_owner(args.get("user_id"))
            )
        if deleted:
            return {"response": f"Deleted task #{task_id}.", "data": {"deleted": True}}
        return {"response": f"Task #{task_id} not found.", "data": {"deleted": False}}
    except Exception as e:
        return {"response": f"Failed to delete task: {e}", "data": {"error": str(e)}}


@register_skill("list_projects")
async def handle_list_projects(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """List all tracked projects via structured.list_projects."""
    from backend.memory import structured
    domain = args.get("domain")
    async with pool.acquire() as conn:
        projects = await structured.list_projects(conn)
    if domain:
        projects = [p for p in projects if p.get("domain") == domain]
    p_names = [f"'{p['name']}' ({p.get('domain', 'general')})" for p in projects]
    summary = f"Found {len(projects)} tracked project(s): {', '.join(p_names)}." if projects else "No tracked projects found."
    return {
        "response": summary,
        "data": {"projects": projects, "count": len(projects)},
    }


@register_skill("detect_deadline_conflicts")
async def handle_detect_deadline_conflicts(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Scan active tasks for conflicting deadlines across domains within the next N days."""
    from backend.memory import structured

    days = int(args.get("days_ahead") or 7)
    today = date.today()
    cutoff = today + timedelta(days=days)
    user_id = args.get("user_id")
    async with pool.acquire() as conn:
        tasks = await list_chat_tasks(conn, args, status="open")

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        d = t.get("due_date")
        if d:
            d_str = str(d)[:10]
            try:
                task_date = date.fromisoformat(d_str)
                if today <= task_date <= cutoff:
                    by_date.setdefault(d_str, []).append(t)
            except Exception:
                pass

    conflicts: List[Dict[str, Any]] = []
    for d_str, day_tasks in sorted(by_date.items()):
        domains = {t.get("domain", "general") for t in day_tasks}
        priorities = {t.get("priority", "medium") for t in day_tasks}
        if len(day_tasks) > 1 or ("urgent" in priorities and "hackathon" in domains and "coursework" in domains):
            is_critical = ("hackathon" in domains and "coursework" in domains) or ("urgent" in priorities)
            conflicts.append({
                "date": d_str,
                "task_count": len(day_tasks),
                "severity": "critical" if is_critical else "moderate",
                "domains": list(domains),
                "tasks": [
                    {"id": t["id"], "title": t["title"], "domain": t.get("domain"), "priority": t.get("priority")}
                    for t in day_tasks
                ],
                "recommendation": (
                    f"Reschedule non-urgent tasks on {d_str} to avoid clash between {', '.join(domains)}."
                    if is_critical
                    else f"Review task pacing on {d_str} to prevent bottleneck."
                )
            })

    if conflicts:
        top_domains = [str(d) for d in (conflicts[0].get("domains") or [])]
        summary = (
            f"⚠️ Detected {len(conflicts)} deadline conflict cluster(s) within the next {days} days. "
            f"Most critical: {conflicts[0]['date']} with {conflicts[0]['task_count']} tasks across {', '.join(top_domains)}."
        )
    else:
        summary = f"✅ No critical deadline conflicts detected across domains in the next {days} days."

    return {
        "response": summary,
        "data": {
            "conflicts_count": len(conflicts),
            "conflicts": conflicts,
            "scanned_tasks_count": len(tasks),
            "days_ahead": days,
        },
    }
