"""Deterministic extraction of several tasks from one pasted message.

Handles delimited tables (pipe/tab/markdown, with or without a header row) and bulleted or numbered
lists. Every line that looks like an item is either extracted or reported as skipped; nothing is
silently dropped. No model call is involved, so extraction is free, bounded and repeatable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

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
    due_time: Optional[str] = None


def extract_item_due_time(item: Any) -> Optional[str]:
    """Extract a 24-hour HH:MM time string from an intake item or dict, or None if not stated."""
    if not item:
        return None
    for key in ("due_time", "time"):
        raw = item.get(key) if isinstance(item, dict) else getattr(item, key, None)
        if raw:
            s = str(raw).strip()
            m = re.match(r"^(\d{1,2}):(\d{2})$", s)
            if m:
                hh, mm = int(m.group(1)), int(m.group(2))
                if 0 <= hh < 24 and 0 <= mm < 60:
                    return f"{hh:02d}:{mm:02d}"
            t24, _, _, _ = _extract_embedded_time(s)
            if t24:
                return t24
            from backend.router_helpers import _parse_time

            t24_p, _ = _parse_time(s.lower())
            if t24_p:
                return t24_p

    from backend.router_helpers import _parse_time

    for key in ("notes", "due_label", "card_text", "due_text"):
        raw = item.get(key) if isinstance(item, dict) else getattr(item, key, None)
        if raw and isinstance(raw, str):
            s = raw.strip()
            t24, _, _, _ = _extract_embedded_time(s)
            if t24:
                return t24
            t24_p, _ = _parse_time(s.lower())
            if t24_p:
                return t24_p

    return None


@dataclass(frozen=True)
class ParsedIntake:
    items: tuple[IntakeItem, ...]
    total_found: int
    skipped: tuple[str, ...]
    unparsed: tuple[str, ...] = ()
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
            if "general" in part:
                domain = "general"
                matched_any = True
            elif any(k in part for k in ("hack", "devpost")) or part == "hackathon":
                domain = "hackathon"
                matched_any = True
            elif any(k in part for k in ("course", "class", "school", "study", "assign", "exam", "lab")) or part == "coursework":
                domain = "coursework"
                matched_any = True
            elif any(k in part for k in ("code", "dev", "repo", "engineer")):
                domain = "code"
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
    due_time = None
    if due_raw:
        t24, t12, leader, _ = _extract_embedded_time(due_raw)
        if t24 and t12:
            notes = f"by {t12}"
            due_time = t24
            # Keep original label format for rows that already produced a label; never reformat it
            due_text = due_raw
        else:
            t24_t, t12_t, _, raw_match = _extract_embedded_time(clean_title)
            if t24_t and t12_t:
                notes = f"by {t12_t}"
                due_time = t24_t
                due_text = f"{due_raw}, {t12_t}"
                if raw_match and raw_match in title:
                    title = title.replace(raw_match, "").strip(" -–—@,:()")
                    title = re.sub(r"\s+", " ", title).strip()
    else:
        t24_t, t12_t, leader_t, raw_match = _extract_embedded_time(clean_title)
        if t24_t and t12_t:
            notes = f"by {t12_t}"
            due_time = t24_t
            if leader_t in _DATE_WORDS:
                norm_lead = "tomorrow" if leader_t == "tmrw" else leader_t
                due_text = f"{norm_lead} {t12_t}"
            else:
                due_text = f"{t12_t}"
            if raw_match and raw_match in title:
                title = title.replace(raw_match, "").strip(" -–—@,:()")
                title = re.sub(r"\s+", " ", title).strip()
    return IntakeItem(
        title=title,
        domain=domain,
        priority=priority,
        duration_minutes=_parse_duration(fields.get("duration", "")),
        due_text=due_text,
        notes=notes,
        due_time=due_time,
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
        due_time = None

        delimiters = list(_BULLET_DUE_SPLIT.finditer(clean_text))
        bullet_cand = clean_text[delimiters[-1].end():].rstrip(") ").strip() if delimiters else ""
        if bullet_cand and resolve_due(bullet_cand, "UTC").due_date is not None:
            title, due_text = clean_text[:delimiters[-1].start()].rstrip(" (").strip(), bullet_cand
            t24, t12, _, _ = _extract_embedded_time(due_text)
            if t24 and t12:
                notes = f"by {t12}"
                due_time = t24
        else:
            # Check embedded time
            t24, t12, leader, raw_match = _extract_embedded_time(clean_text)
            if t24 and t12:
                notes = f"by {t12}"
                due_time = t24
                if leader in _DATE_WORDS:
                    norm_leader = "tomorrow" if leader == "tmrw" else leader
                    due_text = f"{norm_leader} {t12}"
                else:
                    due_text = f"{t12}"
                if raw_match:
                    title = clean_text.replace(raw_match, "").strip(" -–—@,:()")
                    title = re.sub(r"\s+", " ", title).strip()
            else:
                m_end_date = re.search(r"\b(today|tomorrow|tmrw|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday)$", clean_text, re.IGNORECASE)
                if m_end_date:
                    cand = m_end_date.group(1)
                    if resolve_due(cand, "UTC").due_date is not None:
                        title, due_text = clean_text[:m_end_date.start()].strip(), cand

        if title_problem(title):
            skipped.append(text[:80])
            continue
        items.append(IntakeItem(title=title, domain=item_domain, priority=item_priority, duration_minutes=None, due_text=due_text, notes=notes, due_time=due_time))
    return ParsedIntake(tuple(items), len(bullets), tuple(skipped)) if items else None


_SINGLE_PREFIX_WORDS = frozenset({"please", "add", "create", "new", "a", "task", "to", "remind", "me", "schedule", "todo", "set"})
_TRAILING_JOINERS = frozenset({"at", "by", "on", "for", "due", "and"})


def parse_single_task(message: str) -> Optional[ParsedIntake]:
    """Deterministic one-task parse ("call the bank tomorrow at 5pm"): title, date word, clock time."""
    text = (message or "").strip()[:500]
    if not text or "\n" in text:
        return None
    text, paren_domain, paren_priority = _extract_parenthesised_meta(text)
    t24, t12, _leader, raw_time = _extract_embedded_time(text)
    tokens = text.split()
    if raw_time:
        raw_tokens = raw_time.split()
        for i in range(len(tokens) - len(raw_tokens) + 1):
            if tokens[i:i + len(raw_tokens)] == raw_tokens:
                tokens = tokens[:i] + tokens[i + len(raw_tokens):]
                break
    date_word = ""
    kept: list[str] = []
    for tok in tokens:
        low = tok.lower().strip(",;:.!?")
        if not date_word and low in _DATE_WORDS:
            date_word = "tomorrow" if low == "tmrw" else low
            continue
        kept.append(tok)
    while kept and kept[0].lower().strip(",;:") in _SINGLE_PREFIX_WORDS:
        kept.pop(0)
    while kept and kept[-1].lower().strip(",;:.") in _TRAILING_JOINERS:
        kept.pop()
    title = " ".join(kept).strip(" -–—@,:;.")
    if title_problem(title):
        return None
    due_text = " ".join(p for p in (date_word, t12 or "") if p)
    item = IntakeItem(
        title=title, domain=paren_domain or "general", priority=paren_priority or "medium",
        duration_minutes=None, due_text=due_text, notes=f"by {t12}" if t12 else None, due_time=t24,
    )
    return ParsedIntake((item,), 1, ())


def parse_task_list(message: str) -> Optional[ParsedIntake]:
    """Extract up to MAX_ITEMS tasks from a pasted table or list; None when the text is not one."""
    lines = [ln for ln in (message or "").splitlines() if ln.strip()]
    if len(lines) < MIN_ITEMS:
        return None
    return _parse_table(message, lines) or _parse_bullets(message, lines)


# ---------------------------------------------------------------------------
# Clause splitting: "A Tuesday 5pm, B tomorrow 7am and C due Dec 5" -> three tasks (no model call).
# Token based on purpose: no regex with adjacent or overlapping quantifiers.
# ---------------------------------------------------------------------------
_WEEKDAYS = frozenset({"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"})
_MONTHS = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
})
_REL_DAYS = frozenset({"today", "tonight", "tomorrow", "tmrw", "noon", "midnight", "eod"})
_CONNECTORS = frozenset({"at", "of", "the", "on", ","})
_LEFT_MARKERS = frozenset({"due", "by", "on", "at", "before", "until", "for", "next", "this"})
_JOINERS = frozenset({"at", "by", "on", "for", "due", "and", "before", "until", "to", "the", "in", "under"})
_TIME_TOKEN = re.compile(r"^\d{1,2}(?::\d{2})?(?:am|pm)$")
_NUM_DATE = re.compile(r"^\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?$")
_ORDINAL = re.compile(r"^\d{1,2}(?:st|nd|rd|th)$")
_SMALL_NUM = re.compile(r"^\d{1,2}$")
_YEAR = re.compile(r"^20\d{2}$")
_PREFIX_WORDS = frozenset({"please", "add", "create", "schedule", "new", "task", "tasks", "todo", "to", "remind", "me", "set", "a", "an", "my"})
_PREFIX_STARTERS = frozenset({"please", "add", "create", "schedule", "new", "remind", "set"})
_START_VERBS = frozenset({
    "call", "buy", "email", "submit", "finish", "write", "study", "read", "go", "send", "pay", "book", "prepare",
    "complete", "review", "clean", "do", "make", "meet", "visit", "attend", "plan", "fix", "pick", "get", "take",
    "practice", "revise", "renew", "cook", "water", "check", "update", "reply", "call", "gym", "run", "workout",
})
_AREA_SUFFIX = frozenset({"area", "domain", "category", "project", "list"})
_NOT_AREA = frozenset({"the", "a", "an", "my", "pressure", "control", "review", "way", "time", "pm", "am"})
MAX_CLAUSES = MAX_ITEMS


def _norm_tok(tok: str) -> str:
    return tok.lower().strip(",.;:()!?\"'")


def _date_flags(tokens: list[str]) -> list[bool]:
    n = len(tokens)
    low = [_norm_tok(t) for t in tokens]
    flags = [False] * n
    for i, t in enumerate(low):
        if t in _WEEKDAYS or t in _REL_DAYS or _TIME_TOKEN.match(t) or _NUM_DATE.match(t) or _ORDINAL.match(t):
            flags[i] = True
    for i, t in enumerate(low):
        prev_t = low[i - 1] if i else ""
        next_t = low[i + 1] if i + 1 < n else ""
        if t in _MONTHS:
            if _SMALL_NUM.match(next_t) or _ORDINAL.match(next_t) or _SMALL_NUM.match(prev_t) or _ORDINAL.match(prev_t):
                flags[i] = True
        elif _SMALL_NUM.match(t):
            if prev_t in _MONTHS or next_t in _MONTHS or next_t in ("am", "pm"):
                flags[i] = True
        elif t in ("am", "pm"):
            flags[i] = bool(_SMALL_NUM.match(prev_t))
        elif _YEAR.match(t) and i and flags[i - 1] and (prev_t in _MONTHS or _SMALL_NUM.match(prev_t) or _ORDINAL.match(prev_t)):
            flags[i] = True
    return flags


def _has_date_word(tokens: list[str]) -> bool:
    return any(_date_flags(tokens))


def _has_title_word(tokens: list[str]) -> bool:
    flags = _date_flags(tokens)
    return any(
        not f and _norm_tok(t) not in _LEFT_MARKERS and _norm_tok(t) not in _JOINERS and any(c.isalpha() for c in t)
        for t, f in zip(tokens, flags)
    )


def _strip_prefix(tokens: list[str]) -> list[str]:
    if not tokens or _norm_tok(tokens[0]) not in _PREFIX_STARTERS:
        return tokens
    i = 0
    while i < len(tokens) - 1 and _norm_tok(tokens[i]) in _PREFIX_WORDS:
        i += 1
    return tokens[i:]


def split_task_clauses(message: str) -> list[str]:
    """Candidate task clauses on newlines, ';', sentences, ' and ', ' plus ' and ','; dates stay with their clause."""
    text = (message or "")[:4000]
    out: list[str] = []
    for line in text.splitlines():
        for seg in re.split(r"[;!]|[.](?:\s|$)", line):
            tokens = seg.replace(",", " , ").split()
            pieces: list[list[str]] = [[]]
            for tok in tokens:
                if _norm_tok(tok) in ("and", "plus") or tok == ",":
                    if pieces[-1]:
                        pieces.append([])
                    continue
                pieces[-1].append(tok)
            merged: list[list[str]] = []
            for piece in pieces:
                if not piece:
                    continue
                starts_new = (
                    not merged
                    or not any(c.isalpha() for c in " ".join(piece))
                    or (_has_date_word(piece) and _has_title_word(piece))
                    or _norm_tok(piece[0]) in _START_VERBS
                )
                if starts_new:
                    merged.append(piece)
                else:
                    merged[-1] = merged[-1] + ["and"] + piece
            out.extend(" ".join(p) for p in merged)
    return [c.strip() for c in out if c.strip()][:MAX_CLAUSES]


def _area_slug(name: str) -> str:
    low = " ".join((name or "").lower().split())
    built_in = _normalize_domain(low)
    if built_in != "general" or low == "general":
        return built_in
    slug = "".join(ch if (ch.isalnum() or ch in "_-") else "-" for ch in low)
    return slug.strip("-")[:32] or "general"


def _take_area(tokens: list[str]) -> tuple[list[str], Optional[str]]:
    """Area/domain named by '(health)', 'in the Health area' or 'under Health'; returns (tokens_left, area)."""
    joined = " ".join(tokens)
    open_i = joined.find("(")
    close_i = joined.find(")", open_i + 1) if open_i >= 0 else -1
    if 0 <= open_i < close_i:
        inner = joined[open_i + 1:close_i].strip()
        words = inner.split()
        if 1 <= len(words) <= 3 and all(w.isalpha() for w in words) and _PRIORITY_WORDS.get(inner.lower()) is None:
            return (joined[:open_i] + " " + joined[close_i + 1:]).split(), inner
    low = [_norm_tok(t) for t in tokens]
    for i, t in enumerate(low):
        if t not in ("in", "under"):
            continue
        j = i + 2 if (i + 1 < len(low) and low[i + 1] == "the") else i + 1
        if j >= len(low) or low[j] in _NOT_AREA or not tokens[j].isalpha():
            continue
        has_suffix = j + 1 < len(low) and low[j + 1] in _AREA_SUFFIX
        if has_suffix or (t == "under" and tokens[j][:1].isupper()):
            end = j + 2 if has_suffix else j + 1
            return tokens[:i] + tokens[end:], tokens[j]
    return tokens, None


def parse_clause(clause: str) -> Optional[IntakeItem]:
    """One clause -> IntakeItem (title, due text/time, area); None when no usable title remains."""
    tokens = _strip_prefix(clause.strip().strip(".!").split())
    cleaned, paren_domain, paren_priority = _extract_parenthesised_meta(" ".join(tokens))
    tokens = cleaned.split()
    tokens, area = _take_area(tokens)
    flags = _date_flags(tokens)
    n = len(tokens)
    in_run = list(flags)
    for i, t in enumerate(tokens):
        if not flags[i] and _norm_tok(t) in _CONNECTORS and 0 < i < n - 1 and in_run[i - 1] and flags[i + 1]:
            in_run[i] = True
    due_tokens: list[str] = []
    for i, t in enumerate(tokens):
        if in_run[i]:
            due_tokens.append(t.strip(","))
    # markers that led into a date ("due Dec 5", "by Friday") belong to the date, not the title
    first_due = next((i for i, f in enumerate(in_run) if f), None)
    drop: set[int] = set()
    if first_due is not None:
        i = first_due - 1
        while i >= 0 and not in_run[i] and _norm_tok(tokens[i]) in _LEFT_MARKERS:
            drop.add(i)
            if _norm_tok(tokens[i]) in ("next", "this"):
                due_tokens.insert(0, tokens[i])
            i -= 1
    title_tokens = [t for i, t in enumerate(tokens) if not in_run[i] and i not in drop]
    while title_tokens and _norm_tok(title_tokens[-1]) in _JOINERS:
        title_tokens.pop()
    while title_tokens and _norm_tok(title_tokens[0]) in _JOINERS:
        title_tokens.pop(0)
    title = " ".join(title_tokens).strip(" -–—@,:;.")
    if title_problem(title) or not any(c.isalpha() for c in title):
        return None
    due_text = " ".join(due_tokens)
    clock, notes = None, None
    t24, t12, _, _ = _extract_embedded_time(f"at {due_text}") if due_text else (None, None, None, None)
    if t24 and t12:
        clock, notes = t24, f"by {t12}"
    domain = _area_slug(area) if area else (paren_domain or "general")
    return IntakeItem(
        title=title, domain=domain, priority=paren_priority or "medium", duration_minutes=None,
        due_text=due_text, notes=notes, due_time=clock,
    )


def parse_clauses(message: str) -> tuple[list[IntakeItem], list[str]]:
    """Deterministic multi-task parse: (items, unparsed fragments). Fewer than two clauses -> ([], [])."""
    clauses = split_task_clauses(message)
    if len(clauses) < MIN_ITEMS:
        return [], []
    items: list[IntakeItem] = []
    unparsed: list[str] = []
    for clause in clauses:
        item = parse_clause(clause)
        if item:
            items.append(item)
        else:
            unparsed.append(clause[:120])
    return items, unparsed


def _title_key(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 1}


def same_task(a: str, b: str) -> bool:
    ka, kb = _title_key(a), _title_key(b)
    if not ka or not kb:
        return False
    return len(ka & kb) / min(len(ka), len(kb)) >= 0.6


def merge_missing(primary: list[IntakeItem], deterministic: list[IntakeItem]) -> list[IntakeItem]:
    """Keep the model's items; add every deterministic clause the model missed; fill dates it left empty."""
    if not deterministic:
        return list(primary)
    swallowed = any(sum(1 for d in deterministic if _title_key(d.title) <= _title_key(p.title)) >= 2 for p in primary)
    if swallowed:  # one model item swallowed several clauses: the clause split is the better reading
        return list(deterministic)[:MAX_ITEMS]
    result = list(primary)
    for i, p in enumerate(result):
        d = next((d for d in deterministic if same_task(p.title, d.title)), None)
        if d and not p.due_text and d.due_text:
            result[i] = IntakeItem(p.title, p.domain, p.priority, p.duration_minutes, d.due_text, p.project,
                                   p.notes or d.notes, p.due_time or d.due_time)
    for d in deterministic:
        if not any(same_task(p.title, d.title) for p in result):
            result.append(d)
    return result[:MAX_ITEMS]
