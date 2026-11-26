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
_DATE_WORDS = frozenset({"today", "tonight", "tmrw", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"})
_MARKERS = frozenset({"at", "by"})
_LEADERS = _DATE_WORDS | _MARKERS

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
    project: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class ParsedIntake:
    items: tuple[IntakeItem, ...]
    total_found: int
    skipped: tuple[str, ...]

    @property
    def truncated(self) -> bool:
        return self.total_found > len(self.items) + len(self.skipped)

class _ParenSpan:
    """Minimal match-like object for a parenthesised span."""

    def __init__(self, start: int, end: int, inner: str) -> None:
        self._start, self._end, self._inner = start, end, inner

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end

    def group(self, _n: int = 0) -> str:
        return self._inner


def _extract_parenthesised_meta(text: str) -> tuple[str, Optional[str], Optional[str]]:
    """Extract (clean_text, domain, priority) from parenthesised clauses like '(coursework, high priority)'."""
    domain: Optional[str] = None
    priority: Optional[str] = None
    text = text[:2000]
    open_i = text.find("(")
    close_i = text.find(")", open_i + 1) if open_i >= 0 else -1
    m = None
    if close_i > open_i + 1:
        # Linear scan instead of a regex: no backtracking on strings full of "(".
        inner_start = text.rfind("(", open_i, close_i) + 1
        m = _ParenSpan(inner_start - 1, close_i + 1, text[inner_start:close_i])
    cleaned = text
    if m:
        content = m.group(1).strip()
        parts = [p.strip().lower() for p in content.split(",")]
        matched_any = False
        for part in parts:
            for pw, mapped in _PRIORITY_WORDS.items():
                if re.search(rf"\b{pw}\b", part):
                    priority = mapped
                    matched_any = True
                    break
            if part in ("general", "coursework", "hackathon", "code", "other") or any(
                k in part for k in ("hack", "devpost", "course", "class", "school", "study", "assign", "exam", "code", "dev", "repo")
            ):
                domain = "general" if part == "other" else _normalize_domain(part)
                matched_any = True
        if matched_any:
            cleaned = (text[:m.start()] + text[m.end():]).strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, domain, priority


def _extract_embedded_time(text: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Extract (time_24, time_12, leader_word, matched_substr) from text where time follows a date word or at/by."""
    tokens = text.split()
    for i, tok in enumerate(tokens):
        w = tok.lower().strip(",;:()")
        if w in _LEADERS and i + 1 < len(tokens):
            next_tok = tokens[i + 1].strip(",;:()").lower()
            m_hm = re.match(r"^(\d{1,2}):(\d{2})(am|pm)?$", next_tok)
            if m_hm:
                hh, mm, ampm = int(m_hm.group(1)), int(m_hm.group(2)), m_hm.group(3)
                if not ampm and i + 2 < len(tokens) and tokens[i + 2].lower().strip(",;:()") in ("am", "pm"):
                    ampm = tokens[i + 2].lower().strip(",;:()")
                if ampm == "pm" and hh < 12:
                    hh += 12
                elif ampm == "am" and hh == 12:
                    hh = 0
                d_hh = hh % 12 or 12
                d_ampm = "PM" if hh >= 12 else "AM"
                raw = tok + " " + tokens[i + 1] + ((" " + tokens[i + 2]) if ampm and not m_hm.group(3) else "")
                return f"{hh:02d}:{mm:02d}", f"{d_hh}:{mm:02d} {d_ampm}", w, raw
            m_ampm = re.match(r"^(\d{1,2})(am|pm)$", next_tok)
            if m_ampm:
                hh, ampm = int(m_ampm.group(1)), m_ampm.group(2)
                if 1 <= hh <= 12:
                    if ampm == "pm" and hh < 12:
                        hh += 12
                    elif ampm == "am" and hh == 12:
                        hh = 0
                    d_hh = hh % 12 or 12
                    d_ampm = "PM" if hh >= 12 else "AM"
                    return f"{hh:02d}:00", f"{d_hh}:00 {d_ampm}", w, tok + " " + tokens[i + 1]
            if next_tok.isdigit() and 1 <= int(next_tok) <= 12:
                hh = int(next_tok)
                if i + 2 < len(tokens) and tokens[i + 2].lower().strip(",;:()") in ("am", "pm"):
                    ampm = tokens[i + 2].lower().strip(",;:()")
                    if ampm == "pm" and hh < 12:
                        hh += 12
                    elif ampm == "am" and hh == 12:
                        hh = 0
                    d_hh = hh % 12 or 12
                    d_ampm = "PM" if hh >= 12 else "AM"
                    return f"{hh:02d}:00", f"{d_hh}:00 {d_ampm}", w, tok + " " + tokens[i + 1] + " " + tokens[i + 2]
                if 1 <= hh <= 7:
                    return f"{hh + 12:02d}:00", f"{hh}:00 PM", w, tok + " " + tokens[i + 1]
                else:
                    h24 = 0 if hh == 12 else hh
                    return f"{h24:02d}:00", f"{hh}:00 AM", w, tok + " " + tokens[i + 1]
    return None, None, None, None


def _normalize_domain(raw: str) -> str:
    low = (raw or "").strip().lower()
    if low in VALID_DOMAINS:
        return low
    if any(k in low for k in ("hack", "devpost")):
        return "hackathon"
    if any(k in low for k in ("course", "class", "school", "study", "assign", "exam", "lab")):
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
    raw_title = fields.get("title", "")
    clean_title, paren_domain, paren_priority = _extract_parenthesised_meta(raw_title)
    title = re.sub(r"\s+", " ", clean_title).strip()
    if title_problem(title):
        return None
    raw_domain = fields.get("domain", "")
    domain = _normalize_domain(raw_domain) if raw_domain else (paren_domain or "general")
    prio_raw = fields.get("priority", "").strip().lower()
    priority = _PRIORITY_WORDS.get(prio_raw) or paren_priority or "medium"
    due_raw = fields.get("due", "").strip()
    due_text, notes = due_raw, None
    if due_raw:
        t24, t12, leader, _ = _extract_embedded_time(due_raw)
        if t24 and t12:
            notes = f"by {t12}"
            if leader in _DATE_WORDS:
                norm_lead = "tomorrow" if leader == "tmrw" else leader
                due_text = f"{norm_lead} {t12}"
            else:
                due_text = f"{t12}"
    return IntakeItem(
        title=title,
        domain=domain,
        priority=priority,
        duration_minutes=_parse_duration(fields.get("duration", "")),
        due_text=due_text,
        notes=notes,
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
        clean_text, paren_domain, paren_priority = _extract_parenthesised_meta(text)
        item_domain = paren_domain or _normalize_domain(clean_text)
        item_priority = paren_priority or "medium"
        title, due_text, notes = clean_text, "", None

        # Check embedded time
        t24, t12, leader, raw_match = _extract_embedded_time(clean_text)
        if t24 and t12:
            notes = f"by {t12}"
            if leader in _DATE_WORDS:
                norm_leader = "tomorrow" if leader == "tmrw" else leader
                due_text = f"{norm_leader} {t12}"
            else:
                due_text = f"{t12}"
            if raw_match:
                title = clean_text.replace(raw_match, "").strip(" -–—@,:()")
                title = re.sub(r"\s+", " ", title).strip()
        else:
            delimiters = list(_BULLET_DUE_SPLIT.finditer(clean_text))
            if delimiters:
                last = delimiters[-1]
                candidate = clean_text[last.end():].rstrip(") ").strip()
                if candidate and resolve_due(candidate, "UTC").due_date is not None:
                    title, due_text = clean_text[:last.start()].rstrip(" (").strip(), candidate
            else:
                m_end_date = re.search(r"\b(today|tomorrow|tmrw|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$", clean_text, re.IGNORECASE)
                if m_end_date:
                    cand = m_end_date.group(1)
                    if resolve_due(cand, "UTC").due_date is not None:
                        title, due_text = clean_text[:m_end_date.start()].strip(), cand

        if title_problem(title):
            skipped.append(text[:80])
            continue
        items.append(IntakeItem(title=title, domain=item_domain, priority=item_priority, duration_minutes=None, due_text=due_text, notes=notes))
    return ParsedIntake(tuple(items), len(bullets), tuple(skipped)) if items else None


def parse_task_list(message: str) -> Optional[ParsedIntake]:
    """Extract up to MAX_ITEMS tasks from a pasted table or list; None when the text is not one."""
    lines = [ln for ln in (message or "").splitlines() if ln.strip()]
    if len(lines) < MIN_ITEMS:
        return None
    return _parse_table(message, lines) or _parse_bullets(message, lines)
