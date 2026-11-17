"""
Compass — Application deadline extraction from job-page text (T-018).

Pure functions. A date is returned only when the text states one explicitly, with a year, next to a
deadline cue ("apply by", "closing date", ...). A bare "March 31" is ignored: close dates are never guessed.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_RE = r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)"

_CUE_RE = re.compile(
    r"(apply\s+(?:by|before|until)|applications?\s+(?:close|closes|closing|are\s+due|due|deadline|must\s+be\s+received(?:\s+by)?)"
    r"|applications?\s+(?:are\s+)?(?:open\s+)?(?:until|till)|closing\s+date|close\s+date|closes\s+on|deadline(?:\s+to\s+apply)?"
    r"|last\s+date(?:\s+(?:to|for)\s+(?:apply|application|applications))?|submit\s+(?:your\s+)?application\s+by)",
    re.IGNORECASE,
)

# "March 31, 2026" / "Mar 31st 2026"
_DATE_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*((?:19|20)\d{{2}})\b", re.IGNORECASE)
# "31 March 2026" / "31st March, 2026"
_DATE_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?\s*,?\s*((?:19|20)\d{{2}})\b", re.IGNORECASE)
# "2026-03-31"
_DATE_ISO = re.compile(r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b")
# "31/03/2026" or "31-03-2026": day first, as used in India
_DATE_NUM = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-]((?:19|20)\d{2})\b")

_WINDOW_CHARS = 80


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _first_date(fragment: str) -> Optional[date]:
    """Earliest-positioned explicit date in the fragment."""
    found = []
    for m in _DATE_MDY.finditer(fragment):
        found.append((m.start(), _safe_date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))))
    for m in _DATE_DMY.finditer(fragment):
        found.append((m.start(), _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))))
    for m in _DATE_ISO.finditer(fragment):
        found.append((m.start(), _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))))
    for m in _DATE_NUM.finditer(fragment):
        found.append((m.start(), _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))))
    valid = sorted((pos, d) for pos, d in found if d is not None)
    return valid[0][1] if valid else None


def parse_application_deadline(text: Optional[str], today: Optional[date] = None) -> Optional[date]:
    """First explicit application deadline in `text`, or None.

    Accepts dates from one year ago to two years ahead, so stray years in boilerplate are ignored.
    A past date is returned as-is (the listing is then truthfully shown as closed).
    """
    if not text:
        return None
    ref = today or date.today()
    low, high = ref - timedelta(days=365), ref + timedelta(days=730)
    flat = " ".join(str(text).split())
    for cue in _CUE_RE.finditer(flat):
        d = _first_date(flat[cue.end(): cue.end() + _WINDOW_CHARS])
        if d is not None and low <= d <= high:
            return d
    return None
