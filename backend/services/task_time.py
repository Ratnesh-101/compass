"""Timezone-aware due-date resolution for chat task intake.

Relative dates ("today", "tomorrow", "in 4 days") and clock times are resolved in the user's IANA
zone (request > stored profile > UTC) and stored as UTC instants. Nothing is guessed: text that
cannot be read as a date resolves to "no due date" and is flagged as unparsed.
"""

from __future__ import annotations

import contextvars
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from backend.services.user_timezone import DEFAULT_TIMEZONE, resolve_timezone_name

logger = logging.getLogger("compass.services.task_time")

# Set by the orchestrator for the duration of one chat request so date helpers that default to
# "today" use the user's calendar day instead of the server's.
request_timezone: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "compass_request_timezone", default=None
)


def is_valid_timezone(raw: Any) -> bool:
    """True only for a real IANA zone name (UTC fallback in resolve_timezone_name is not 'valid')."""
    return isinstance(raw, str) and bool(raw.strip()) and resolve_timezone_name(raw) == raw.strip()


def pick_timezone(request_tz: Any, profile_tz: Any) -> str:
    """Request zone, else the stored profile zone, else UTC. Invalid values are skipped."""
    for candidate in (request_tz, profile_tz):
        if is_valid_timezone(candidate):
            return candidate.strip()
    return DEFAULT_TIMEZONE


async def resolve_effective_timezone(pool: Any, owner_identity: Optional[str], request_tz: Any) -> str:
    """Resolve the zone for a request; only touches the database when the request zone is unusable."""
    if is_valid_timezone(request_tz):
        return request_tz.strip()
    profile_tz = None
    if pool is not None and owner_identity:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT value FROM user_profile_facts WHERE user_id = $1 AND key = 'timezone'",
                    owner_identity,
                )
            profile_tz = row["value"] if row else None
        except Exception as e:
            logger.debug("Profile timezone lookup failed (falling back to UTC): %s", e)
    return pick_timezone(request_tz, profile_tz)


def local_today(tz_name: Optional[str], now_utc: Optional[datetime] = None) -> date:
    """The calendar date right now in the given zone (UTC when unusable)."""
    zone = ZoneInfo(pick_timezone(tz_name, None))
    return (now_utc or datetime.now(timezone.utc)).astimezone(zone).date()


def combine_local(day: date, clock: Optional[time], tz_name: str) -> Optional[datetime]:
    """UTC instant for a local date + time in tz_name; None when there is no clock time."""
    if clock is None:
        return None
    local = datetime.combine(day, clock, tzinfo=ZoneInfo(pick_timezone(tz_name, None)))
    return local.astimezone(timezone.utc)


def clock_from_24h(value: Optional[str]) -> Optional[time]:
    """Parse 'HH:MM' (as produced by the chat time parser) into a time."""
    if not value:
        return None
    try:
        hh, mm = value.split(":")[:2]
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return None


def extract_clock(due_str: Any, time_str: Any, message: Any) -> Optional[time]:
    """Clock time stated for a task: inside the due string, else the time hint, else the message."""
    from backend.router_helpers import _parse_time

    if due_str:
        m = re.search(r"[T ](\d{1,2}:\d{2})", str(due_str))
        if m:
            return clock_from_24h(m.group(1))
    for source in (time_str, message):
        time_24 = _parse_time(str(source or "").lower())[0]
        if time_24:
            return clock_from_24h(time_24)
    return None


def format_clock(clock: time) -> str:
    return f"{clock.hour % 12 or 12}:{clock.minute:02d} {'PM' if clock.hour >= 12 else 'AM'}"


def format_due_label(day: Optional[date], due_at: Optional[datetime], tz_name: str) -> str:
    """Human label in the user's zone, e.g. 'Thu Oct 29, 9:00 PM (Asia/Calcutta)'."""
    if day is None:
        return "no due date"
    label = f"{day.strftime('%a %b')} {day.day}"
    if due_at is None:
        return label
    valid_tz = pick_timezone(tz_name, None)
    local = due_at.astimezone(ZoneInfo(valid_tz))
    return f"{label}, {format_clock(local.timetz())} ({valid_tz})"


_NUMERIC_DATE = re.compile(r"^\d{1,4}[/.\-]\d{1,2}([/.\-]\d{1,4})?$")
MAX_DUE_HORIZON_DAYS = 800


def _fallback_date(text: str, tz_name: str, now_utc: Optional[datetime]) -> Optional[date]:
    """Date from the dateparser library for phrasings our own parser does not know ("the 3rd", "in two weeks").

    Only an explicit day is accepted (a bare time is never turned into "today"), ambiguous numeric
    dates like 10/11 are refused, and results far in the past or future are discarded.
    """
    if _NUMERIC_DATE.match(text.strip()):
        return None  # day/month order is ambiguous; ask instead of guessing
    try:
        import dateparser

        zone = ZoneInfo(tz_name)
        now_local = (now_utc or datetime.now(timezone.utc)).astimezone(zone)
        parsed = dateparser.parse(
            text,
            languages=["en"],
            settings={
                "TIMEZONE": tz_name,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now_local.replace(tzinfo=None),
                "REQUIRE_PARTS": ["day"],
            },
        )
    except Exception as e:
        logger.debug("dateparser fallback failed for %r: %s", text, e)
        return None
    if parsed is None:
        return None
    day = parsed.astimezone(zone).date()
    today = now_local.date()
    return day if today - timedelta(days=1) <= day <= today + timedelta(days=MAX_DUE_HORIZON_DAYS) else None


@dataclass(frozen=True)
class ResolvedDue:
    due_date: Optional[date]
    due_at: Optional[datetime]  # timezone-aware UTC, or None for a date-only due
    label: str
    unparsed_text: Optional[str]  # non-empty input that could not be read as a date


def resolve_due(text: Optional[str], tz_name: str, now_utc: Optional[datetime] = None) -> ResolvedDue:
    """Resolve free-form due text ("Today, 9:00 PM", "Tomorrow", "In 4 days") in tz_name."""
    from backend.router_helpers import _parse_natural_date, _parse_time

    clean = (text or "").strip()
    zone_name = pick_timezone(tz_name, None)
    if not clean:
        return ResolvedDue(None, None, "no due date", None)
    day, time_24, _ = _parse_natural_date(clean, today=local_today(zone_name, now_utc))
    if day is None:
        day = _fallback_date(clean, zone_name, now_utc)
        time_24 = _parse_time(clean.lower())[0] if day else None
    if day is None:
        return ResolvedDue(None, None, "no due date", clean)
    clock = clock_from_24h(time_24)
    due_at = combine_local(day, clock, zone_name)
    return ResolvedDue(day, due_at, format_due_label(day, due_at, zone_name), None)
