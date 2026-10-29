"""Validated IANA timezone resolution for user-facing scheduling (no schema, no regexes)."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "UTC"
MAX_TIMEZONE_LEN = 64
_ALLOWED_PUNCTUATION = frozenset("/_-+")


def _plausible_zone_name(name: str) -> bool:
    """Cheap structural screen before touching the filesystem-backed zoneinfo lookup."""
    if not name or len(name) > MAX_TIMEZONE_LEN:
        return False
    if name.startswith("/") or name.endswith("/") or "//" in name:
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in _ALLOWED_PUNCTUATION) for ch in name)


def resolve_timezone_name(raw: Any) -> str:
    """Return a valid IANA zone name, or "UTC" for missing/unknown/hostile input."""
    if not isinstance(raw, str):
        return DEFAULT_TIMEZONE
    name = raw.strip()
    if not _plausible_zone_name(name):
        return DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except Exception:
        return DEFAULT_TIMEZONE
    return name


def resolve_zone(raw: Any) -> ZoneInfo:
    """Return the ZoneInfo for a user-supplied name, falling back to UTC."""
    return ZoneInfo(resolve_timezone_name(raw))
