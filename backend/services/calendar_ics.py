"""
Compass — RFC 5545 iCalendar (.ics) feed generator.

Split out of ``services.calendar`` (still re-exported there). Rules implemented:
- Tasks with a scheduled slot become timed UTC events.
- Tasks with only a due date become ALL-DAY events (DTSTART/DTEND;VALUE=DATE, end = next day).
- TEXT values escape backslash, semicolon, comma and newlines (RFC 5545 section 3.3.11).
- Content lines are folded at 75 octets (section 3.1).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from backend.services.scheduler import _ensure_utc

ICS_MAX_LINE_OCTETS = 75
DEFAULT_EVENT_MINUTES = 60


def _format_ics_dt(dt: datetime | str | date) -> str:
    """Format datetime as UTC iCalendar string (YYYYMMDDTHHMMSSZ)."""
    utc_dt = _ensure_utc(dt)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")


def escape_ics_text(value: Any) -> str:
    """Escape a TEXT value: backslash first, then ; , and line breaks."""
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def fold_ics_line(line: str) -> str:
    """Fold one content line at 75 octets, never splitting a UTF-8 character."""
    if len(line.encode("utf-8")) <= ICS_MAX_LINE_OCTETS:
        return line
    parts: List[str] = []
    current = ""
    current_octets = 0
    limit = ICS_MAX_LINE_OCTETS
    for ch in line:
        size = len(ch.encode("utf-8"))
        if current_octets + size > limit:
            parts.append(current)
            current, current_octets = ch, size
            limit = ICS_MAX_LINE_OCTETS - 1  # continuation lines carry a leading space
        else:
            current += ch
            current_octets += size
    parts.append(current)
    return "\r\n ".join(parts)


def date_only_value(value: Any) -> Optional[date]:
    """Return the calendar date for a date-only deadline, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _task_time_fields(t: Dict[str, Any]) -> Optional[List[str]]:
    """DTSTART/DTEND lines for a task, or None when it has no usable time."""
    s_start = t.get("scheduled_start")
    s_end = t.get("scheduled_end")
    if s_start:
        start_dt = _ensure_utc(s_start)
        if s_end:
            end_dt = _ensure_utc(s_end)
        else:
            end_dt = start_dt + timedelta(minutes=int(t.get("duration_minutes") or DEFAULT_EVENT_MINUTES))
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=DEFAULT_EVENT_MINUTES)
        return [f"DTSTART:{_format_ics_dt(start_dt)}", f"DTEND:{_format_ics_dt(end_dt)}"]
    due = date_only_value(t.get("due_date"))
    if due is None:
        return None
    nxt = due + timedelta(days=1)
    return [
        f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{nxt.strftime('%Y%m%d')}",
    ]


def generate_ics_feed(
    tasks: Sequence[Dict[str, Any]],
    calendar_name: str = "Compass Focus Schedule",
) -> str:
    """Generate RFC 5545 compliant iCalendar string for calendar export."""
    now_stamp = _format_ics_dt(datetime.now(timezone.utc))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Compass Autonomous Agent//Dynamic Scheduler 2.0//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(calendar_name)}",
        "X-WR-TIMEZONE:UTC",
    ]

    for t in tasks:
        time_lines = _task_time_fields(t)
        if time_lines is None:
            continue

        task_id = t.get("id") or uuid.uuid4().hex[:8]
        title = escape_ics_text(t.get("title") or "Untitled Task")
        domain = str(t.get("domain") or "general")
        priority = t.get("priority") or "medium"
        notes = t.get("notes") or ""
        desc = f"Domain: {domain}\nPriority: {priority}"
        if notes:
            desc += f"\nNotes: {notes}"

        lines.extend(["BEGIN:VEVENT", f"UID:compass-task-{task_id}@compass.ai", f"DTSTAMP:{now_stamp}"])
        lines.extend(time_lines)
        lines.extend([
            f"SUMMARY:[{escape_ics_text(domain.upper())}] {title}",
            f"DESCRIPTION:{escape_ics_text(desc)}",
            "STATUS:CONFIRMED",
            f"CATEGORIES:{escape_ics_text(domain.upper())}",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics_line(ln) for ln in lines) + "\r\n"
