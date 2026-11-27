"""Deterministic schedule formatting, real task due-date join, internal agent text scrubbing,
and commit-plan staging helper for Compass agents.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("compass.schedule_deterministic")

# Regex to scrub internal reviewer, critic, and revision artifacts leaking to the user.
_INTERNAL_AGENT_PATTERNS = re.compile(
    r"\b(?:reviewer(?:\x27s)?|critic(?:\x27s|ism)?|revision[s]?|previously approved|per feedback)\b",
    re.IGNORECASE,
)
_WEEKDAY_PATTERN = re.compile(
    r"\b(Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\b",
    re.IGNORECASE,
)
_MONTH_DAY_PATTERN = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})\b",
    re.IGNORECASE,
)
_WINDOW_PATTERN = re.compile(r"\b(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\b")
_BREAK_PATTERN = re.compile(r"\b(\d+)\s*-?\s*minute\s+breaks?\b", re.IGNORECASE)


def _resolve_tz(tz_name: Optional[str] = None) -> ZoneInfo:
    """Resolve IANA timezone, falling back to request context or Asia/Kolkata."""
    if tz_name:
        try:
            return ZoneInfo(tz_name.strip())
        except Exception:
            pass
    try:
        from backend.services.task_time import request_timezone
        req_tz = request_timezone.get()
        if req_tz:
            return ZoneInfo(req_tz.strip())
    except Exception:
        pass
    try:
        return ZoneInfo("Asia/Kolkata")
    except Exception:
        return ZoneInfo("UTC")


def _format_date_short(d: date) -> str:
    """Format date as 'Sat Nov 28' or 'Fri Dec 4' without leading zero on day."""
    return f"{d.strftime('%a %b')} {d.day}"


def _format_task_due(task: Dict[str, Any], tz: ZoneInfo) -> str:
    """Extract strictly real due date string from task row (never LLM prose)."""
    due_at = task.get("due_at")
    if due_at:
        try:
            dt = due_at if isinstance(due_at, datetime) else datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_loc = dt.astimezone(tz)
            hr = dt_loc.hour % 12 or 12
            return f"{_format_date_short(dt_loc.date())}, {hr}:{dt_loc.minute:02d} {dt_loc.strftime('%p')}"
        except Exception:
            pass
    raw_due = task.get("due_date")
    if not raw_due:
        return "No Due Date"
    try:
        if isinstance(raw_due, (datetime, date)):
            d = raw_due if isinstance(raw_due, date) else raw_due.date()
        else:
            d = date.fromisoformat(str(raw_due).strip()[:10])
        return _format_date_short(d)
    except Exception:
        s = str(raw_due).strip()
        return s[:10] if len(s) >= 10 else s


def _format_due_date(raw_due: Any, due_at: Any = None, tz: Optional[ZoneInfo] = None) -> str:
    """Extract strictly real due date string from task row (backwards-compatible)."""
    return _format_task_due({"due_date": raw_due, "due_at": due_at}, tz or _resolve_tz())


def _format_time_slot(start_iso: Optional[str], end_iso: Optional[str], tz: Optional[ZoneInfo] = None) -> str:
    """Format scheduled slot into readable string in user's timezone, e.g. 'Fri Nov 27, 3:00-4:00 PM'."""
    if not start_iso or not end_iso:
        return "Unscheduled"
    zone = tz or _resolve_tz()
    try:
        s_dt = datetime.fromisoformat(str(start_iso).replace("Z", "+00:00"))
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=timezone.utc)
        s_loc = s_dt.astimezone(zone)
        e_dt = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
        if e_dt.tzinfo is None:
            e_dt = e_dt.replace(tzinfo=timezone.utc)
        e_loc = e_dt.astimezone(zone)

        day_str = _format_date_short(s_loc.date())
        s_hr, e_hr = s_loc.hour % 12 or 12, e_loc.hour % 12 or 12
        s_ampm, e_ampm = s_loc.strftime("%p"), e_loc.strftime("%p")
        if s_ampm == e_ampm:
            t_part = f"{s_hr}:{s_loc.minute:02d}-{e_hr}:{e_loc.minute:02d} {e_ampm}"
        else:
            t_part = f"{s_hr}:{s_loc.minute:02d} {s_ampm}-{e_hr}:{e_loc.minute:02d} {e_ampm}"
        return f"{day_str}, {t_part}"
    except Exception:
        return f"{str(start_iso)[:16]} - {str(end_iso)[11:16]}"


def _get_block_local_dt(block: Dict[str, Any], tz: ZoneInfo) -> Optional[datetime]:
    s_start = block.get("scheduled_start")
    if not s_start:
        return None
    try:
        s_dt = datetime.fromisoformat(str(s_start).replace("Z", "+00:00"))
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=timezone.utc)
        return s_dt.astimezone(tz)
    except Exception:
        return None


def _get_task_due_date_obj(task: Dict[str, Any], tz: ZoneInfo) -> Optional[date]:
    due_at = task.get("due_at")
    if due_at:
        try:
            dt = due_at if isinstance(due_at, datetime) else datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(tz).date()
        except Exception:
            pass
    raw_due = task.get("due_date")
    if raw_due:
        if isinstance(raw_due, (datetime, date)):
            return raw_due if isinstance(raw_due, date) else raw_due.date()
        try:
            return date.fromisoformat(str(raw_due).strip()[:10])
        except Exception:
            pass
    return None


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

    h_idx = start - 1
    while h_idx >= 0 and lines[h_idx].strip() == "":
        h_idx -= 1
    if h_idx >= 0 and lines[h_idx].strip().startswith("#") and any(w in lines[h_idx].lower() for w in ["schedule", "plan"]):
        start = h_idx

    return "\n".join(lines[:start] + [table_md, ""] + lines[end + 1:])


def scrub_internal_agent_text(text: str) -> str:
    """Pure helper that strips sentences containing internal reviewer or critic text."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if line.lstrip(" \t").startswith("\\*"):
            continue
        if _INTERNAL_AGENT_PATTERNS.search(line):
            sentences = re.split(r"(?<=[.!?]) +", line)
            kept = [s for s in sentences if not _INTERNAL_AGENT_PATTERNS.search(s)]
            if kept:
                cleaned_lines.append(" ".join(kept))
        else:
            cleaned_lines.append(line)
    res = "\n".join(cleaned_lines)
    return re.sub(r"\n{3,}", "\n\n", res).strip()


def extract_schedule_target_date(
    query: str, base_date: Optional[date] = None, tz_name: Optional[str] = None
) -> Tuple[Optional[date], Optional[str]]:
    """Determine if query asks for a specific target day (tomorrow, today, or a weekday)."""
    if not query:
        return None, None
    q = query.lower()
    zone = _resolve_tz(tz_name)
    today = base_date or datetime.now(zone).date()

    if "tomorrow" in q:
        return today + timedelta(days=1), "Tomorrow"
    if "today" in q or "tonight" in q:
        return today, "Today"

    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    for name, wday in weekdays.items():
        if name in q:
            delta = (wday - today.weekday()) % 7
            return today + timedelta(days=delta if delta != 0 else 7), name.title()

    return None, None


def drop_contradicting_sentences(
    text: str, table_md: str, tasks: Any, allowed_facts: Optional[Sequence[str]] = None
) -> str:
    """Drop prose sentences that contradict the deterministic table, real due dates, or saved preferences."""
    if not text:
        return ""
    task_list = list(tasks.values()) if isinstance(tasks, dict) else (tasks if isinstance(tasks, list) else [])

    allowed_wds = {m.group(0)[:3].lower() for m in _WEEKDAY_PATTERN.finditer(table_md)}
    allowed_dates = {f"{m.group(1)[:3].lower()} {int(m.group(2))}" for m in _MONTH_DAY_PATTERN.finditer(table_md)}

    zone = _resolve_tz()
    today = datetime.now(zone).date()
    any_due_today = False
    for t in task_list:
        d_obj = _get_task_due_date_obj(t, zone)
        if d_obj:
            any_due_today = any_due_today or d_obj == today
            allowed_wds.add(d_obj.strftime("%a")[:3].lower())
            allowed_dates.add(f"{d_obj.strftime('%b')[:3].lower()} {d_obj.day}")

    allowed_windows, allowed_breaks = set(), set()
    for f in list(allowed_facts or []):
        for m in _WINDOW_PATTERN.finditer(str(f)):
            h1, m1 = m.group(1).split(":")
            h2, m2 = m.group(2).split(":")
            allowed_windows.add(f"{int(h1):02d}:{m1}-{int(h2):02d}:{m2}")
        for m in _BREAK_PATTERN.finditer(str(f)):
            allowed_breaks.add(str(int(m.group(1))))
        for m in re.finditer(r"\b(\d+)\b", str(f)):
            allowed_breaks.add(m.group(1))

    if not allowed_windows:
        allowed_windows = {"09:00-18:00"}
    if not allowed_breaks:
        allowed_breaks = {"15"}

    lines, cleaned_lines = text.split("\n"), []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("|", "#", "- ", "* ")) or not stripped:
            cleaned_lines.append(line)
            continue

        kept_sentences = []
        for s in re.split(r"(?<=[.!?]) +", line):
            s_clean = s.strip()
            if not s_clean:
                continue

            low_s = s_clean.lower()
            drop = "task id" in low_s or "(id:" in low_s or ("due today" in low_s and not any_due_today)
            for m in ([] if drop else _WEEKDAY_PATTERN.finditer(s_clean)):
                if m.group(0)[:3].lower() not in allowed_wds:
                    drop = True
                    break
            if not drop:
                for m in _MONTH_DAY_PATTERN.finditer(s_clean):
                    if f"{m.group(1)[:3].lower()} {int(m.group(2))}" not in allowed_dates:
                        drop = True
                        break
            if not drop:
                for m in _WINDOW_PATTERN.finditer(s_clean):
                    h1, m1 = m.group(1).split(":")
                    h2, m2 = m.group(2).split(":")
                    norm_w = f"{int(h1):02d}:{m1}-{int(h2):02d}:{m2}"
                    if norm_w not in allowed_windows and f"{m.group(1)}-{m.group(2)}" not in table_md:
                        drop = True
                        break
            if not drop:
                for m in _BREAK_PATTERN.finditer(s_clean):
                    if str(int(m.group(1))) not in allowed_breaks:
                        drop = True
                        break
            if not drop:
                kept_sentences.append(s_clean)

        if kept_sentences:
            cleaned_lines.append(" ".join(kept_sentences))

    res = "\n".join(cleaned_lines)
    return re.sub(r"\n{3,}", "\n\n", res).strip()


def build_deterministic_schedule_table(
    scheduled_blocks: List[Dict[str, Any]],
    real_tasks: Dict[int, Dict[str, Any]],
    target_date: Optional[date] = None,
    day_label: Optional[str] = None,
    tz_name: Optional[str] = None,
) -> str:
    """Build a deterministic markdown schedule table."""
    zone = _resolve_tz(tz_name)

    if target_date is not None:
        target_blocks = [
            b for b in scheduled_blocks
            if _get_block_local_dt(b, zone) and _get_block_local_dt(b, zone).date() == target_date  # type: ignore[union-attr]
        ]
        target_due_tasks = [t for t in real_tasks.values() if _get_task_due_date_obj(t, zone) == target_date]
        priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        target_due_tasks.sort(key=lambda t: (priority_order.get(str(t.get("priority", "")).lower(), 2), t.get("title", "")))

        day_full_name = f"{target_date.strftime('%A, %B')} {target_date.day}"
        section_lines = []
        if target_due_tasks:
            due_hdr = f"**Due tomorrow ({day_full_name}):**" if (day_label and day_label.lower() == "tomorrow") else f"**Due {day_full_name}:**"
            section_lines.append(due_hdr)
            for t in target_due_tasks:
                section_lines.append(f"- {t.get('title')} (due {_format_task_due(t, zone)})")
            section_lines.append("")

        if target_blocks:
            section_lines.append(f"### Schedule for {day_full_name}")
            section_lines.append("| Task | Domain | Scheduled Slot | Due Date | Priority |")
            section_lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for b in target_blocks:
                tid = b.get("task_id")
                task = real_tasks.get(tid, {}) if tid is not None else {}
                title = task.get("title") or b.get("title") or f"Task #{tid}"
                domain = task.get("domain") or b.get("domain") or "general"
                priority = str(task.get("priority") or "medium").capitalize()
                slot_str = _format_time_slot(b.get("scheduled_start"), b.get("scheduled_end"), zone)
                due_str = _format_task_due(task, zone)
                section_lines.append(f"| {title} | {domain.title()} | {slot_str} | {due_str} | {priority} |")
        else:
            section_lines.append(f"Nothing is scheduled for {day_full_name} yet.")

        return "\n".join(section_lines).strip()

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
    block_dates: List[date] = []

    for tid in sorted(all_task_ids):
        task = real_tasks.get(tid, {})
        blocks = blocks_by_id.get(tid, [])
        title = task.get("title") or (blocks[0].get("title") if blocks else f"Task #{tid}")
        domain = task.get("domain") or (blocks[0].get("domain") if blocks else None) or "general"
        priority = str(task.get("priority") or "medium")
        due_str = _format_task_due(task, zone)
        due_date_obj = _get_task_due_date_obj(task, zone)

        if blocks:
            for b in blocks:
                s_start, s_end = b.get("scheduled_start"), b.get("scheduled_end")
                b_dt = _get_block_local_dt(b, zone)
                if b_dt:
                    block_dates.append(b_dt.date())
                combined_rows.append({
                    "task_id": tid, "title": title, "domain": domain,
                    "slot": _format_time_slot(s_start, s_end, zone),
                    "due_date": due_str, "due_date_obj": due_date_obj,
                    "slot_dt": b_dt, "priority": priority,
                })
        else:
            combined_rows.append({
                "task_id": tid, "title": title, "domain": domain, "slot": "Unscheduled",
                "due_date": due_str, "due_date_obj": due_date_obj, "slot_dt": None, "priority": priority,
            })

    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    combined_rows.sort(key=lambda r: (r["slot_dt"] or datetime.max.replace(tzinfo=zone), r["due_date_obj"] or date.max, priority_order.get(str(r["priority"]).lower(), 2)))

    if block_dates:
        min_d, max_d = min(block_dates), max(block_dates)
        range_str = _format_date_short(min_d) if min_d == max_d else f"{_format_date_short(min_d)} - {_format_date_short(max_d)}"
        header_title = f"### Schedule Plan ({range_str})"
    elif day_label:
        header_title = f"### Schedule Plan ({day_label})"
    else:
        header_title = "### Deterministic Schedule Plan"

    lines = [header_title, "| Task | Domain | Scheduled Slot | Due Date | Priority |", "| :--- | :--- | :--- | :--- | :--- |"]
    for r in combined_rows:
        lines.append(f"| {r['title']} | {r['domain'].title()} | {r['slot']} | {r['due_date']} | {r['priority'].capitalize()} |")
    return "\n".join(lines)


def _single_day_answer(
    table_md: str,
    scheduled_blocks: List[Dict[str, Any]],
    target_date: date,
    committed: bool,
    zone: ZoneInfo,
) -> str:
    """Deterministic-only answer for a single-day question; model prose is discarded."""
    on_day = other_days = False
    for b in scheduled_blocks:
        b_dt = _get_block_local_dt(b, zone)
        if b_dt is None:
            continue
        if b_dt.date() == target_date:
            on_day = True
        else:
            other_days = True
    parts = [table_md.strip()]
    if on_day and not committed:
        parts.append("Nothing is saved yet. Say 'commit this plan' to put these blocks on your calendar.")
    elif other_days and not on_day and not committed:
        parts.append('Nothing is saved yet. Say "plan my week" to see a proposal.')
    return "\n\n".join(p for p in parts if p).strip()


def patch_schedule_answer(
    reply: str,
    scheduled_blocks: List[Dict[str, Any]],
    real_tasks: Dict[int, Dict[str, Any]],
    user_goal: str,
    committed: bool = False,
    tz_name: Optional[str] = None,
    allowed_facts: Optional[Sequence[str]] = None,
) -> str:
    """Produce deterministically verified schedule answer with honest commit status."""
    clean_reply = scrub_internal_agent_text(reply)
    zone = _resolve_tz(tz_name)
    target_date, day_label = extract_schedule_target_date(user_goal, tz_name=str(zone))

    table_md = build_deterministic_schedule_table(
        scheduled_blocks, real_tasks, target_date=target_date, day_label=day_label, tz_name=str(zone)
    )

    if target_date is not None:
        return _single_day_answer(table_md, scheduled_blocks, target_date, committed, zone)

    if table_md:
        replaced = _replace_first_table(clean_reply, table_md)
        clean_reply = replaced if replaced is not None else clean_reply.rstrip() + "\n\n" + table_md

    if target_date is not None:
        has_proposed = any(
            _get_block_local_dt(b, zone) and _get_block_local_dt(b, zone).date() == target_date  # type: ignore[union-attr]
            for b in scheduled_blocks
        )
    else:
        has_proposed = bool(scheduled_blocks)

    honest_sentence = "Nothing is saved yet. Say 'commit this plan' to put these blocks on your calendar."
    if has_proposed and not committed:
        if honest_sentence not in clean_reply:
            clean_reply = clean_reply.rstrip() + f"\n\n{honest_sentence}"
    elif not has_proposed:
        clean_reply = clean_reply.replace(honest_sentence, "").strip()

    clean_reply = drop_contradicting_sentences(clean_reply, table_md, real_tasks, allowed_facts=allowed_facts)

    from backend.services.action_claim_guard import guard_unbacked_action_claims
    guarded_reply, _ = guard_unbacked_action_claims(clean_reply, committed)

    if has_proposed and not committed and honest_sentence not in guarded_reply:
        guarded_reply = guarded_reply.rstrip() + f"\n\n{honest_sentence}"

    return guarded_reply.strip()


async def fetch_real_tasks_for_schedule(
    pool: Any, user_id: Optional[str], task_ids: Optional[List[int]] = None, include_demo: bool = False
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
                    WHERE deleted_at IS NULL AND id = ANY($1::int[]) AND ($2::text IS NULL OR lower(user_id) = lower($2::text))
                    """,
                    task_ids, scoped_user,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, title, domain, due_date, due_at, status, priority, duration_minutes
                    FROM tasks
                    WHERE deleted_at IS NULL AND status != 'completed' AND ($1::text IS NULL OR lower(user_id) = lower($1::text))
                      AND ($2::boolean OR COALESCE(trusted_event_url,'') NOT LIKE 'compass://demo-persona/%')
                    ORDER BY due_date ASC NULLS LAST, priority DESC LIMIT 30
                    """,
                    scoped_user, bool(include_demo),
                )
            return {int(r["id"]): dict(r) for r in rows}
    except Exception as e:
        logger.warning(f"[fetch_real_tasks_for_schedule] Query failed: {e}")
        return {}


async def fetch_saved_preferences(pool: Any, user_id: Optional[str]) -> Dict[str, Any]:
    """Fetch saved scheduling preferences from the database, or standard defaults."""
    default_prefs = {"work_start_time": "09:00:00", "work_end_time": "18:00:00", "work_days": [1, 2, 3, 4, 5], "buffer_minutes": 15}
    if not pool:
        return default_prefs
    try:
        from backend.memory.structured import get_scheduling_preferences
        async with pool.acquire() as conn:
            return await get_scheduling_preferences(conn, user_id=user_id or "default_user")
    except Exception as e:
        logger.debug(f"[fetch_saved_preferences] Query failed: {e}")
        return default_prefs


def _parse_dt(value: Any) -> Optional[datetime]:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _hhmm_min(value: Any, default: str) -> int:
    h, m = (str(value or default).split(":") + ["0"])[:2]
    return int(h) * 60 + int(m)


def _working_days(prefs: Dict[str, Any]) -> set:
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    out = set()
    for d in prefs.get("working_days", prefs.get("work_days")) or [1, 2, 3, 4, 5]:
        s = str(d).strip()
        n = int(s) if s.isdigit() else (names.index(s[:3].lower()) + 1 if s[:3].lower() in names else None)
        out.update([] if n is None else [n or 7])
    return out


def validate_proposed_blocks(
    blocks: List[Dict[str, Any]], prefs: Dict[str, Any], tz_name: Optional[str], now_utc: datetime, tasks: Dict[int, Any],
) -> Tuple[bool, List[str]]:
    """Check blocks against working hours/days, the clock, due times and each other."""
    zone, now = _resolve_tz(tz_name), (now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc))
    lo, hi = _hhmm_min(prefs.get("work_start_time"), "09:00"), _hhmm_min(prefs.get("work_end_time"), "18:00")
    days, problems, spans = _working_days(prefs), [], []
    for b in blocks or []:
        title = str(b.get("title") or b.get("task_id") or "block")
        start, end = _parse_dt(b.get("scheduled_start") or b.get("start")), _parse_dt(b.get("scheduled_end") or b.get("end"))
        if start is None or end is None or end <= start:
            problems.append(f"{title}: invalid time range")
            continue
        ls, le = start.astimezone(zone), end.astimezone(zone)
        spans.append((start, end, title))
        if ls.isoweekday() not in days:
            problems.append(f"{title}: on a non-working day")
        if ls.hour * 60 + ls.minute < lo or le.date() != ls.date() or le.hour * 60 + le.minute > hi:
            problems.append(f"{title}: outside working hours")
        problems += [f"{title}: starts in the past"] * (start < now)
        problems += [f"{title}: longer than the working window"] * (end - start > timedelta(minutes=max(hi - lo, 0)))
        task = tasks.get(b.get("task_id")) or {}

        d = _get_task_due_date_obj(task, zone) if not task.get("due_at") and task.get("due_date") else None
        due = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=zone) if d else _parse_dt(task.get("due_at"))
        if due is not None and end > due:
            problems.append(f"{title}: ends after its due time")
    spans.sort(key=lambda s: s[0])
    problems += [f"{p[2]} and {c[2]}: overlap" for p, c in zip(spans, spans[1:]) if c[0] < p[1]]
    return (not problems, problems)


async def repair_plan_blocks(blocks: List[Dict[str, Any]], pool: Any, owner_id: Optional[str],
                             tz_name: Optional[str], tasks: Dict[int, Any]) -> List[Dict[str, Any]]:
    """Return blocks unchanged if valid, else a fresh scheduler proposal. Never raises."""
    try:
        prefs = await fetch_saved_preferences(pool, owner_id)
        ok, problems = validate_proposed_blocks(blocks, prefs, tz_name, datetime.now(timezone.utc), tasks)
        if ok:
            return blocks
        logger.info("Agent plan rejected: %s", "; ".join(problems[:5]))
        from backend.skills.handlers.calendar import handle_propose_schedule
        fresh = ((await handle_propose_schedule({"user_id": owner_id}, pool)).get("data") or {}).get("scheduled") or []
        return [dict(b) for b in fresh] if fresh else blocks
    except Exception:
        return blocks

async def find_pending_agent_run(pool: Any, user_id: Optional[str], conversation_id: Optional[str]) -> Optional[Dict[str, Any]]:
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
                user_id, conversation_id,
            )
            return dict(row) if row else None
    except Exception as e:
        logger.debug(f"Pending agent run lookup failed: {e}")
        return None


async def handle_agent_schedule_synthesis(
    reply: str, goal: str, proposed_blocks: List[Dict[str, Any]], pool: Any, user_id: Optional[str], run_id: str, step_num: int
) -> Tuple[str, List[Dict[str, Any]], List[Any], List[Dict[str, Any]]]:
    """Process agent answer for scheduling: enforce deterministic real task due dates."""
    from backend.agent_types import AgentStep
    from backend.services.task_time import request_timezone

    user_tz = request_timezone.get() or "Asia/Kolkata"
    zone = _resolve_tz(user_tz)
    target_date, day_label = extract_schedule_target_date(goal, tz_name=user_tz)

    is_sched = any(k in goal.lower() for k in ["schedule", "plan", "tomorrow", "calendar", "weekday", "thursday", "friday", "monday", "routine"])
    extra_steps, pending_cf = [], []

    if pool and (proposed_blocks or is_sched):
        is_planning_goal = any(k in goal.lower() for k in ["plan", "reschedule", "replan", "time-block", "schedule my"])
        if not proposed_blocks and is_planning_goal and target_date is None:
            try:
                from backend.skills.handlers.calendar import handle_propose_schedule
                p_res = await handle_propose_schedule({"user_id": user_id}, pool)
                proposed_blocks = p_res.get("data", {}).get("scheduled") or []
            except Exception as ex:
                logger.debug(f"Fallback propose failed: {ex}")

        t_ids = [b["task_id"] for b in proposed_blocks if "task_id" in b] or None
        real_tasks = await fetch_real_tasks_for_schedule(pool, user_id, t_ids, include_demo=False)
        saved_prefs = await fetch_saved_preferences(pool, user_id)
        w_start = str(saved_prefs.get("work_start_time", "09:00:00"))[:5]
        w_end = str(saved_prefs.get("work_end_time", "18:00:00"))[:5]
        buf_min = int(saved_prefs.get("buffer_minutes", 15))
        allowed_facts = [f"{w_start}-{w_end}", f"{buf_min}-minute", f"{buf_min} minute", f"{buf_min} minutes", f"{buf_min} min"]

        clean_reply = patch_schedule_answer(
            reply, proposed_blocks, real_tasks, goal, committed=False, tz_name=user_tz, allowed_facts=allowed_facts
        )

        schedulable_blocks = proposed_blocks
        if target_date is not None:
            schedulable_blocks = [
                b for b in proposed_blocks
                if _get_block_local_dt(b, zone) and _get_block_local_dt(b, zone).date() == target_date  # type: ignore[union-attr]
            ]

        if schedulable_blocks:
            step_num += 1
            c_args = {"assignments": schedulable_blocks, "rationale": "Schedule plan proposed by Compass Agent."}
            c_step = AgentStep(
                type="confirm_request", content="Say 'commit this plan' to put these blocks on your calendar.",
                tool_name="commit_schedule", tool_args=c_args, step_number=step_num, run_id=run_id,
                model_tier="Human Authorization Gate", metadata={"scheduled": schedulable_blocks},
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
    "drop_contradicting_sentences",
    "build_deterministic_schedule_table",
    "patch_schedule_answer",
    "fetch_real_tasks_for_schedule",
    "fetch_saved_preferences",
    "find_pending_agent_run",
    "handle_agent_schedule_synthesis",
]
