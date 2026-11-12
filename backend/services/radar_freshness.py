"""
Compass — Internship Radar Freshness Service.

Pure functions and domain rules governing opportunity verification freshness.

Product Decision (College-Student Internship Radar, Honesty First):
1. A listing counts as "verified open / Active now" ONLY if current_status is OPEN_CONFIRMED
   AND it was verified within the last 14 days (RECENCY_FRESH_DAYS = 14).
2. Verification recency uses last_verified_at, falling back to last_checked_at.
3. OPEN_CONFIRMED listings older than 14 days stay in the list but are labelled "needs re-check".
4. Future dates count as fresh=false only if unparsable; parsable future dates are fresh.
5. No verification date at all = NOT fresh.
6. Never infer or invent close dates.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from backend.models_radar import OpportunityStatus

RECENCY_FRESH_DAYS: int = 14


def _parse_to_date(val: Any) -> Optional[date]:
    """Parse date, datetime, ISO string, or timestamp into a date object. Return None if unparsable."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, (int, float)):
        try:
            ts = val / 1000.0 if val > 1e11 else float(val)
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except Exception:
            return None
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned or cleaned.lower() in ("none", "null", "undefined", "nan", ""):
            return None
        iso_str = cleaned.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(iso_str).date()
        except Exception:
            pass
        try:
            return date.fromisoformat(cleaned[:10])
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(cleaned[:10], fmt).date()
            except Exception:
                pass
        return None
    return None


def _get_field(opp_or_row: Any, field_name: str) -> Any:
    """Retrieve field value from dict, mapping, or model instance."""
    if opp_or_row is None:
        return None
    if isinstance(opp_or_row, dict):
        return opp_or_row.get(field_name)
    if hasattr(opp_or_row, "__getitem__"):
        try:
            return opp_or_row[field_name]
        except (KeyError, TypeError, IndexError):
            pass
    return getattr(opp_or_row, field_name, None)


def _extract_verification_date(opp_or_row: Any) -> Optional[date]:
    """Extract verification date, checking last_verified_at then last_checked_at then sources."""
    if opp_or_row is None:
        return None
    if isinstance(opp_or_row, (datetime, date)):
        return opp_or_row.date() if isinstance(opp_or_row, datetime) else opp_or_row
    if isinstance(opp_or_row, str):
        return _parse_to_date(opp_or_row)

    # 1. Check last_verified_at
    v_val = _get_field(opp_or_row, "last_verified_at")
    v_date = _parse_to_date(v_val)
    if v_date is not None:
        return v_date

    # 2. Check last_checked_at
    c_val = _get_field(opp_or_row, "last_checked_at")
    c_date = _parse_to_date(c_val)
    if c_date is not None:
        return c_date

    # 3. Check sources if available
    sources = _get_field(opp_or_row, "sources")
    if sources and isinstance(sources, list):
        best_date: Optional[date] = None
        for s in sources:
            s_val = _get_field(s, "last_checked_at")
            if s_val is None:
                s_val = _get_field(s, "discovered_at")
            s_date = _parse_to_date(s_val)
            if s_date is not None:
                if best_date is None or s_date > best_date:
                    best_date = s_date
        if best_date is not None:
            return best_date

    return None


def verification_age_days(opp_or_row: Any, today: Optional[date] = None) -> Optional[int]:
    """
    Computes whole days since last_verified_at (falling back to last_checked_at).
    Returns None if no parsable verification date exists.
    Future dates yield 0 whole days (not rejected unless unparsable).
    """
    v_date = _extract_verification_date(opp_or_row)
    if v_date is None:
        return None

    ref_date = today.date() if isinstance(today, datetime) else (today or date.today())
    diff = (ref_date - v_date).days
    return max(0, diff)


def is_fresh_open(opp_or_row: Any, today: Optional[date] = None) -> bool:
    """
    Determines if an opportunity is verified open / Active now.
    Returns True ONLY if current_status is OPEN_CONFIRMED, confirmed_close_date has not passed,
    and verified within RECENCY_FRESH_DAYS (14 days).
    """
    ref_date = today.date() if isinstance(today, datetime) else (today or date.today())
    status = _get_field(opp_or_row, "current_status")
    if not status or str(status).upper() != OpportunityStatus.OPEN_CONFIRMED:
        return False

    close_date = _parse_to_date(_get_field(opp_or_row, "confirmed_close_date"))
    if close_date and close_date < ref_date:
        return False

    age = verification_age_days(opp_or_row, today=ref_date)
    return age is not None and age <= RECENCY_FRESH_DAYS


def needs_recheck(opp_or_row: Any, today: Optional[date] = None) -> bool:
    """
    Returns True if an OPEN_CONFIRMED opportunity has expired recency (>14 days or no verification date).
    Returns False for non-OPEN_CONFIRMED opportunities or closed listings.
    """
    ref_date = today.date() if isinstance(today, datetime) else (today or date.today())
    status = _get_field(opp_or_row, "current_status")
    if not status or str(status).upper() != OpportunityStatus.OPEN_CONFIRMED:
        return False

    close_date = _parse_to_date(_get_field(opp_or_row, "confirmed_close_date"))
    if close_date and close_date < ref_date:
        return False

    age = verification_age_days(opp_or_row, today=ref_date)
    return age is None or age > RECENCY_FRESH_DAYS
