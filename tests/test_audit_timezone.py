"""Audit tests for PR #219: Timezone resolution, formatting, and DST bugs."""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
import pytest

from backend.services.task_time import combine_local, format_due_label


def test_format_due_label_with_invalid_timezone_uses_utc_in_label():
    """Bug: format_due_label calculates local time in UTC for invalid timezones,

    but interpolates the raw invalid tz string (e.g. 'Mars/Phobos') into the label:
    'Fri Oct 30, 12:00 PM (Mars/Phobos)' instead of '(UTC)'.
    """
    day = date(2026, 10, 30)
    due_at = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    invalid_tz = "Mars/Phobos"

    label = format_due_label(day, due_at, invalid_tz)
    assert "(UTC)" in label, f"Expected '(UTC)' in label for fallback, got: {label!r}"
    assert invalid_tz not in label, f"Raw invalid timezone leaked into label: {label!r}"


def test_oversized_timezone_string_is_not_dumped_into_label():
    """Bug: Passing a 10 KB timezone string dumps all 10,000 characters into the user label."""
    day = date(2026, 10, 30)
    due_at = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    huge_tz = "A" * 10000

    label = format_due_label(day, due_at, huge_tz)
    assert len(label) < 100, f"Label contains unbounded raw timezone string: len={len(label)}"


def test_dst_spring_forward_gap_preserves_local_clock_time():
    """Non-existent local clock times during DST spring-forward roll forward to 03:30 EDT (07:30 UTC)."""
    gap_day = date(2026, 3, 8)
    requested_clock = time(2, 30)
    tz_name = "America/New_York"

    due_at = combine_local(gap_day, requested_clock, tz_name)
    assert due_at == datetime(2026, 3, 8, 7, 30, tzinfo=timezone.utc)

    local_dt = due_at.astimezone(ZoneInfo(tz_name))
    assert local_dt.hour == 3 and local_dt.minute == 30
    assert local_dt.tzname() == "EDT"


def test_dst_fall_back_ambiguous_time_pins_first_occurrence_edt():
    """Ambiguous local clock times during DST fall-back pin the first occurrence (EDT / fold=0)."""
    fall_day = date(2026, 11, 1)
    requested_clock = time(1, 30)
    tz_name = "America/New_York"

    due_at = combine_local(fall_day, requested_clock, tz_name)
    assert due_at == datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc)

    local_dt = due_at.astimezone(ZoneInfo(tz_name))
    assert local_dt.hour == 1 and local_dt.minute == 30
    assert local_dt.tzname() == "EDT"
