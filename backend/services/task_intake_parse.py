"""Deterministic extraction of several tasks from one pasted message.

Handles delimited tables (pipe/tab/markdown, with or without a header row) and bulleted or numbered
lists. Every line that looks like an item is either extracted or reported as skipped; nothing is
silently dropped. No model call is involved, so extraction is free, bounded and repeatable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from backend.services.task_intent import title_problem

MAX_ITEMS = 20
MIN_ITEMS = 2
VALID_DOMAINS = ("hackathon", "coursework", "code", "general")

_PRIORITY_WORDS = {
    "urgent": "urgent", "critical": "urgent", "p0": "urgent", "asap": "urgent",
    "high": "high", "p1": "high", "important": "high",
    "medium": "medium", "normal": "medium", "p2": "medium", "moderate": "medium",
    "low": "low", "p3": "low", "minor": "low",
}
_HEADER_FIELDS = {
    "title": "title", "task": "title", "name": "title", "item": "title",
    "domain": "domain", "category": "domain", "project": "domain",
    "due": "due", "deadline": "due", "due date": "due", "when": "due", "date": "due",
    "priority": "priority", "prio": "priority",
    "duration": "duration", "estimate": "duration", "est": "duration", "effort": "duration",
}
_POSITIONAL_FIELDS = ("title", "domain", "due", "priority", "duration")
_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(\S.*)$")
_LIST_INTENT = re.compile(r"\b(?:add|create|schedule|track|remind)\b|\bto-?dos?\b", re.IGNORECASE)
_DURATION_HOURS = re.compile(r"^(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)$", re.IGNORECASE)
_DURATION_MINUTES = re.compile(r"^(\d+)\s*(?:m|min|mins|minute|minutes)$", re.IGNORECASE)
_BULLET_DUE_SPLIT = re.compile(r"\s[-–—@]\s|\s(?:by|due|on)\s|[(,]", re.IGNORECASE)


@dataclass(frozen=True)
class IntakeItem:
    title: str
    domain: str
    priority: str
    duration_minutes: Optional[int]
    due_text: str


@dataclass(frozen=True)
class ParsedIntake:
    items: tuple[IntakeItem, ...]
    total_found: int
    skipped: tuple[str, ...]

    @property
    def truncated(self) -> bool:
        return self.total_found > len(self.items) + len(self.skipped)


def _normalize_domain(raw: str) -> str:
    low = (raw or "").strip().lower()
    if low in VALID_DOMAINS:
        return low
    if any(k in low for k in ("hack", "devpost")):
        return "hackathon"
    if any(k in low for k in ("course", "class", "school", "study", "assign", "exam")):
        return "coursework"
    if any(k in low for k in ("code", "dev", "repo", "engineer")):
        return "code"
    return "general"


def _parse_duration(raw: str) -> Optional[int]:
    text = (raw or "").strip()
    if m := _DURATION_HOURS.match(text):
        return round(float(m.group(1)) * 60)
    if m := _DURATION_MINUTES.match(text):
        return int(m.group(1))
    return None


def _split_row(line: str) -> list[str]:
    """Cells of a pipe/tab delimited row; [] when the line is not a table row."""
    stripped = line.strip("\r\n")
    if "|" in stripped:
        cells = [c.strip() for c in stripped.strip().strip("|").split("|")]
    elif "\t" in stripped:
        cells = [c.strip() for c in stripped.split("\t")]
    else:
        return []
    return cells if any(cells) else []


def _is_separator(cells: list[str]) -> bool:
    return all(_SEPARATOR_CELL.match(c) or not c for c in cells)


def _header_map(cells: list[str]) -> Optional[dict[int, str]]:
    """Column mapping for a header row: a title column plus at least one other known column."""
    mapping = {i: _HEADER_FIELDS[c.lower()] for i, c in enumerate(cells) if c.lower() in _HEADER_FIELDS}
    return mapping if "title" in mapping.values() and len(set(mapping.values())) >= 2 else None


def _item_from_cells(cells: list[str], mapping: dict[int, str]) -> Optional[IntakeItem]:
    fields = {name: cells[i] for i, name in mapping.items() if i < len(cells)}
    title = re.sub(r"\s+", " ", fields.get("title", "")).strip()
    if title_problem(title):
        return None
    prio_raw = fields.get("priority", "").strip().lower()
    return IntakeItem(
        title=title,
        domain=_normalize_domain(fields.get("domain", "")),
        priority=_PRIORITY_WORDS.get(prio_raw, "medium"),
        duration_minutes=_parse_duration(fields.get("duration", "")),
        due_text=fields.get("due", "").strip(),
    )


def _parse_table(message: str, lines: list[str]) -> Optional[ParsedIntake]:
    rows = [(line, _split_row(line)) for line in lines]
    rows = [(line, cells) for line, cells in rows if cells and not _is_separator(cells)]
    if not rows:
        return None
    mapping = _header_map(rows[0][1])
    if not mapping and not _LIST_INTENT.search(message):
        return None  # a headerless pipe/tab block is only a task list when the user asks to add tasks
    data_rows = rows[1:] if mapping else rows
    mapping = mapping or {i: name for i, name in enumerate(_POSITIONAL_FIELDS)}
    if len(data_rows) < MIN_ITEMS:
        return None
    items: list[IntakeItem] = []
    skipped: list[str] = []
    for line, cells in data_rows[:MAX_ITEMS]:
        item = _item_from_cells(cells, mapping)
        if item:
            items.append(item)
        else:
            skipped.append(line.strip()[:80])
    return ParsedIntake(tuple(items), len(data_rows), tuple(skipped)) if items else None


def _parse_bullets(message: str, lines: list[str]) -> Optional[ParsedIntake]:
    bullets = [m.group(1).strip() for line in lines if (m := _BULLET.match(line))]
    if len(bullets) < MIN_ITEMS or not _LIST_INTENT.search(message):
        return None
    from backend.services.task_time import resolve_due

    items: list[IntakeItem] = []
    skipped: list[str] = []
    for text in bullets[:MAX_ITEMS]:
        title, due_text = text, ""
        delimiters = list(_BULLET_DUE_SPLIT.finditer(text))
        if delimiters:
            last = delimiters[-1]
            candidate = text[last.end():].rstrip(") ").strip()
            if candidate and resolve_due(candidate, "UTC").due_date is not None:
                title, due_text = text[:last.start()].rstrip(" (").strip(), candidate
        if title_problem(title):
            skipped.append(text[:80])
            continue
        items.append(IntakeItem(title, "general", "medium", None, due_text))
    return ParsedIntake(tuple(items), len(bullets), tuple(skipped)) if items else None


def parse_task_list(message: str) -> Optional[ParsedIntake]:
    """Extract up to MAX_ITEMS tasks from a pasted table or list; None when the text is not one."""
    lines = [ln for ln in (message or "").splitlines() if ln.strip()]
    if len(lines) < MIN_ITEMS:
        return None
    return _parse_table(message, lines) or _parse_bullets(message, lines)
