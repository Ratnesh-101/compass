"""
Compass — Router Helper Utilities and Parsing Logic.

Extracted parsing, keyword detection, date processing, and fallback routing for Nemotron-3 Nano LLM Router.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional, Tuple

from backend.services.task_intent import blocks_task_creation, normalize_task_intent_text, title_problem
from backend.services.task_time import local_today, request_timezone

logger = logging.getLogger("compass.router.helpers")

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

MONTHS_MAP = MONTH_MAP

DAYS_OF_WEEK = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _current_today() -> date:
    """Today in the request's timezone (server date outside a chat request or when tests patch router.date)."""
    try:
        import sys
        mod = sys.modules.get("backend.router")
        patched = getattr(mod, "date", date) if mod else date
        if patched is not date:
            cand = patched.today()
            if hasattr(cand, "year"):
                return cand
    except Exception:
        pass
    tz_name = request_timezone.get()
    return local_today(tz_name) if tz_name else date.today()


def parse_natural_due_date(text: str) -> Tuple[Optional[str], str]:
    """Parse natural dates like '12th october', '12 oct', '2026-10-12', 'october 12th' from text.
    Returns (iso_date_string, cleaned_text).
    """
    text_lower = text.lower()
    today = _current_today()

    if "day after tomorrow" in text_lower:
        d = today + timedelta(days=2)
        return d.isoformat(), re.sub(r"\bday\s+after\s+tomorrow\b", "", text, flags=re.IGNORECASE).strip()
    if "tomorrow" in text_lower:
        d = today + timedelta(days=1)
        return d.isoformat(), re.sub(r"\btomorrow\b", "", text, flags=re.IGNORECASE).strip()
    if "today" in text_lower:
        return today.isoformat(), re.sub(r"\btoday\b", "", text, flags=re.IGNORECASE).strip()

    # YYYY-MM-DD
    iso_match = re.search(r"\b(202[4-9]-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))\b", text)
    if iso_match:
        return iso_match.group(1), text.replace(iso_match.group(0), "").strip()

    # "12th october", "12 oct", "12th of october"
    day_month = re.search(
        r"\b([0-2]?[0-9]|3[01])(?:st|nd|rd|th)?\s+(?:of\s+)?(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|sept|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(202[4-9]))?\b",
        text,
        re.IGNORECASE,
    )
    if day_month:
        day = int(day_month.group(1))
        m_str = day_month.group(2).lower()
        month = MONTHS_MAP.get(m_str, 10)
        year = int(day_month.group(3)) if day_month.group(3) else today.year
        iso_val = f"{year:04d}-{month:02d}-{day:02d}"
        clean_text = text.replace(day_month.group(0), "").strip()
        return iso_val, clean_text

    # "october 12th", "oct 12"
    month_day = re.search(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|sept|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+([0-2]?[0-9]|3[01])(?:st|nd|rd|th)?(?:\s+(202[4-9]))?\b",
        text,
        re.IGNORECASE,
    )
    if month_day:
        m_str = month_day.group(1).lower()
        month = MONTHS_MAP.get(m_str, 10)
        day = int(month_day.group(2))
        year = int(month_day.group(3)) if month_day.group(3) else today.year
        iso_val = f"{year:04d}-{month:02d}-{day:02d}"
        clean_text = text.replace(month_day.group(0), "").strip()
        return iso_val, clean_text

    return None, text


def is_task_mutation_request(msg: str) -> bool:
    """Check if a prompt contains intent to add, create, or schedule a task or deadline."""
    if not msg:
        return False
    norm = normalize_task_intent_text(msg)
    msg_l = norm.lower()
    if blocks_task_creation(msg) or blocks_task_creation(norm):
        return False
    mutation_keywords = (
        "add a task", "add task", "new task", "create task",
        "add a deadline", "add deadline", "set deadline", "set a deadline",
        "add deliverable", "create deliverable", "schedule deadline", "new deadline",
        "add a due date", "set due date", "add due date"
    )
    return any(k in msg_l for k in mutation_keywords)


def is_explicit_task_creation(message: str) -> bool:
    """Determine whether message represents an explicit command to add a task/deadline/reminder."""
    if not message:
        return False
    if blocks_task_creation(message):
        return False
    norm = normalize_task_intent_text(message)
    if blocks_task_creation(norm):
        return False
    msg = norm.lower().strip()
    if not msg:
        return False

    # Queries, questions, or passive statements must NOT be treated as task creation
    if re.search(r"^(when\s+is|what\s+is|what's|where\s+is|who\s+is|how\s+to|why\s+is|is\s+there|are\s+there|tell\s+me|show\s+me|check\s+the|find\s+the|do\s+i\s+have)\b", msg):
        return False
    if blocks_task_creation(message):
        return False

    # Declarative sentences describing existing deadlines (e.g. "The deadline for X is ...") are NOT creation commands
    if re.search(r"^(the|my|our|their|this)\s+(submission\s+)?(deadline|task|due\s+date)\b", msg):
        return False

    task_phrases = (
        "add a task", "add task", "new task", "create task", "create a task",
        "schedule a task", "schedule task",
        "add a deadline", "add deadline", "new deadline", "create deadline",
        "create a deadline", "set a deadline", "set deadline",
        "schedule a deadline", "schedule deadline",
        "remind me to",
        "add a reminder", "add reminder", "create a reminder", "set a reminder",
    )
    if any(p in msg for p in task_phrases):
        return True

    # Imperative verbs followed by task/deadline/todo/reminder
    verbs = ("add", "create", "new", "set", "schedule", "put", "track")
    nouns = ("deadline", "task", "todo", "reminder")
    for v in verbs:
        # Whole-word verb ("address"/"upset" must not match add/set); "track my tasks" is a query.
        v_rx = rf"\b{v}\b" if v != "track" else r"\btrack\b(?!\s+(?:my|all|the|our)\b)"
        m_v = re.search(v_rx, msg)
        if m_v:
            for n in nouns:
                if msg.find(n, m_v.end()) != -1:
                    return True

    return False


def is_undo_request(message: str) -> bool:
    """Check if message is an undo/revert command."""
    msg = message.lower().strip().rstrip(".!?")
    return msg in (
        "undo", "undo that", "revert", "revert that", "undo last action",
        "undo task", "undo delete", "restore", "restore deleted", "restore task",
        "restore tasks", "undo my delete", "undo the delete",
    )


# Numbered replies to a delete-candidate list ("Please reply with the number").
# Only meaningful for a delete_task_disambiguation pending action.
ORDINAL_REPLIES = frozenset({
    "2", "3", "second one", "the second one", "third one", "the third one",
})


# "confirm ..." / "yes, ..." / "cancel ..." / "no, ..." only count as answers to a pending
# action when the rest is just filler ("confirm my meeting time is 3pm" is a normal request).
_CONFIRM_TAIL = frozenset({
    "yes", "delete", "deletion", "it", "that", "this", "the", "please", "do", "go", "ahead", "now",
    "first", "one", "sure", "confirm", "action", "thanks", "i", "am",
})
_CANCEL_TAIL = frozenset({
    "it", "that", "this", "the", "action", "delete", "deletion", "please", "now", "don't", "dont",
    "stop", "thanks", "thank", "you", "no", "never", "mind",
})


def _only_words(rest: list, allowed: frozenset) -> bool:
    words = rest[0].split() if rest else []
    return all(w in allowed for w in words)


def is_pending_action_confirm(message: str) -> bool:
    """Check if message is an explicit confirmation of a pending action."""
    msg = message.lower().strip().rstrip(".!?")
    exact_matches = (
        "yes", "confirm", "yes confirm", "confirm delete", "delete it", "yes delete it",
        "do it", "sure", "proceed", "1", "first one", "the first one",
        "delete the first one", "complete the first one", "yes, delete the first one",
        "yes delete the first one", "yes please", "yeah", "yep",
    )
    if msg in exact_matches or msg in ORDINAL_REPLIES:
        return True
    if msg.startswith("yes,") or msg.startswith("confirm "):
        return _only_words(msg.replace(",", " ").split(None, 1)[1:], _CONFIRM_TAIL)
    return False


def is_pending_action_cancel(message: str) -> bool:
    """Check if message is an explicit cancellation of a pending action."""
    msg = message.lower().strip().rstrip(".!?")
    exact_matches = (
        "no", "cancel", "stop", "abort", "don't delete", "dont delete",
        "never mind", "nevermind", "no cancel", "cancel action",
        "no don't delete", "no dont delete",
    )
    if msg in exact_matches:
        return True
    if msg.startswith("cancel ") or msg.startswith("no,"):
        return _only_words(msg.replace(",", " ").split(None, 1)[1:], _CANCEL_TAIL)
    return False


_POLITE_LEADS = (
    "please ", "pls ", "can you ", "could you ", "would you ", "will you ", "go ahead and ",
    "i want to ", "i'd like to ", "i would like to ", "i need to ",
)


def _looks_like_non_task_target(target: str) -> bool:
    """"remove the bug from my code" / "drop me a summary" are not task deletions."""
    padded = f" {target} "
    return " from " in padded or target.startswith(("me ", "it ", "i ", "us "))


def is_chat_delete_intent(message: str) -> Tuple[bool, bool, str]:
    """Detect if message is an intent to delete/remove tasks or clear schedule.
    
    Returns (is_delete, is_clear_all, target_query).
    """
    msg = message.lower().strip().rstrip(".!?")
    
    for lead in _POLITE_LEADS:
        if msg.startswith(lead):
            msg = msg[len(lead):].strip()
            break
    for tail in (" please", " for me"):
        if msg.endswith(tail):
            msg = msg[:-len(tail)].strip()

    # 1. Clear entire schedule
    clear_all_phrases = (
        "clear all my schedule", "clear my schedule", "clear schedule",
        "delete all tasks", "delete all my tasks", "remove all tasks",
        "clear all tasks", "delete everything in schedule", "clear all my tasks",
    )
    if any(phrase == msg or msg.startswith(phrase) for phrase in clear_all_phrases):
        return True, True, ""

    # 2. Delete / remove specific task query (deterministic parsing without regex backtracking)
    for prefix in ("delete", "remove", "drop"):
        if msg == prefix:
            continue
        if msg.startswith(prefix + " "):
            remainder = msg[len(prefix):].strip()
            if remainder.startswith("the "):
                remainder = remainder[4:].strip()
            if remainder.startswith("task "):
                remainder = remainder[5:].strip()
            if remainder.endswith(" task"):
                remainder = remainder[:-5].strip()
            target = remainder.strip("'\"").strip()
            if _looks_like_non_task_target(target):
                continue
            if target and target not in ("first one", "the first one", "it", "this"):
                return True, False, target

    return False, False, ""


def _parse_time(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract (24h_time_str, 12h_formatted_str) e.g. ('23:59', '11:59 PM')."""
    # 1. HH:MM (am/pm)?
    m = re.search(r"\b([01]?[0-9]|2[0-3]):([0-5][0-9])\s*(am|pm)?\b", text, re.IGNORECASE)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ampm = m.group(3)
        if ampm:
            ampm_lower = ampm.lower()
            if ampm_lower == "pm" and hh < 12:
                hh += 12
            elif ampm_lower == "am" and hh == 12:
                hh = 0
        time_24 = f"{hh:02d}:{mm:02d}"
        display_hh = hh % 12 or 12
        display_ampm = "PM" if hh >= 12 else "AM"
        time_12 = f"{display_hh}:{mm:02d} {display_ampm}"
        return time_24, time_12

    # 2. at 5pm / 5 pm
    m2 = re.search(r"\b(?:at\s+)?([1-9]|1[0-2])\s*(am|pm)\b", text, re.IGNORECASE)
    if m2:
        hh = int(m2.group(1))
        ampm = m2.group(2).lower()
        if ampm == "pm" and hh < 12:
            hh += 12
        elif ampm == "am" and hh == 12:
            hh = 0
        time_24 = f"{hh:02d}:00"
        time_12 = f"{m2.group(1)} {ampm.upper()}"
        return time_24, time_12

    return None, None


def _parse_natural_date(text: str, today: Optional[date] = None) -> Tuple[Optional[date], Optional[str], Optional[str]]:
    """Extract (target_date, time_24, time_12) from text."""
    if today is None:
        today = _current_today()

    msg = text.lower()
    time_24, time_12 = _parse_time(msg)

    # Relative days
    if "day after tomorrow" in msg:
        return today + timedelta(days=2), time_24, time_12
    if "tomorrow" in msg:
        return today + timedelta(days=1), time_24, time_12
    if "today" in msg or "tonight" in msg:
        return today, time_24, time_12

    # "in N days"
    m_in_days = re.search(r"\bin\s+(\d+)\s+days?\b", msg)
    if m_in_days:
        return today + timedelta(days=int(m_in_days.group(1))), time_24, time_12

    # "in N weeks"
    m_in_weeks = re.search(r"\bin\s+(\d+)\s+weeks?\b", msg)
    if m_in_weeks:
        return today + timedelta(days=7 * int(m_in_weeks.group(1))), time_24, time_12

    # Day of week (e.g. "next monday", "this friday", "friday")
    for day_name, target_weekday in DAYS_OF_WEEK.items():
        pattern = rf"\b(?:next\s+|this\s+)?{day_name}\b"
        if re.search(pattern, msg):
            days_ahead = (target_weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + timedelta(days=days_ahead), time_24, time_12

    # ISO date (YYYY-MM-DD)
    m_iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", msg)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if y < today.year:
            y = today.year
        try:
            return date(y, m, d), time_24, time_12
        except ValueError:
            pass

    # Month and day patterns:
    month_regex = "|".join(MONTH_MAP.keys())
    m_day_month = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_regex})\b(?:\s+(20\d{{2}}))?",
        msg,
    )
    if m_day_month:
        d = int(m_day_month.group(1))
        m_str = m_day_month.group(2)
        m = MONTH_MAP[m_str]
        y_str = m_day_month.group(3)
        y = int(y_str) if y_str else today.year
        if y < today.year:
            y = today.year
        try:
            cand = date(y, m, d)
            if not y_str and cand < today:
                cand = date(y + 1, m, d)
            return cand, time_24, time_12
        except ValueError:
            pass

    m_month_day = re.search(
        rf"\b({month_regex})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:\s+(20\d{{2}}))?",
        msg,
    )
    if m_month_day:
        m_str = m_month_day.group(1)
        m = MONTH_MAP[m_str]
        d = int(m_month_day.group(2))
        y_str = m_month_day.group(3)
        y = int(y_str) if y_str else today.year
        if y < today.year:
            y = today.year
        try:
            cand = date(y, m, d)
            if not y_str and cand < today:
                cand = date(y + 1, m, d)
            return cand, time_24, time_12
        except ValueError:
            pass

    return None, time_24, time_12


_AFTER_CREATION_PHRASE = re.compile(
    r"\b(?:add|create|make|set(?:\s+up)?|schedule|put|new|track)\b\s+(?:me\s+)?(?:an?\s+|the\s+|another\s+)?(?:new\s+)?"
    r"(?:tasks?|todos?|to-dos?|deadlines?|reminders?)\b\s*(?:(?:for\s+me|please)\b\s*)*"
    r"(?:[:\-\u2013]|\b(?:to|for|called|named|titled|about|on)\b)?\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _extract_task_creation_args(message: str) -> dict:
    """Extract title, domain, due_date, time_str, and priority from natural language."""
    norm = normalize_task_intent_text(message)
    msg = norm.strip()
    msg_lower = msg.lower()

    # 1. Domain detection
    domain = "general"
    if any(k in msg_lower for k in ("hackathon", "devpost", "pitch", "demo")):
        domain = "hackathon"
    elif any(k in msg_lower for k in ("coursework", "assignment", "homework", "exam", "quiz", "lecture", "cs101")):
        domain = "coursework"
    elif any(k in msg_lower for k in ("code", "repo", "repository", "bug", "pr", "branch", "refactor")):
        domain = "code"

    m_dom = re.search(r"\bdomain[:= ]\s*([a-z0-9_-]+)", msg_lower)
    if m_dom:
        d_val = m_dom.group(1).lower()
        if d_val in ("hackathon", "coursework", "code", "general"):
            domain = d_val

    # 2. Date & Time
    parsed_date, time_24, time_12 = _parse_natural_date(msg)
    due_str = None
    if parsed_date:
        if time_24:
            due_str = f"{parsed_date.isoformat()} {time_24}"
        else:
            due_str = parsed_date.isoformat()

    # 3. Title Extraction
    title = ""

    # Strategy A: Explicit name indicators: "with the name X", "named X", "called X", "titled X"
    for indicator in ("with the name", "named", "called", "titled"):
        pattern = rf"\b{indicator}\s+[:\"']?([^\"'\n,;]+)"
        m_named = re.search(pattern, msg, re.IGNORECASE)
        if m_named:
            cand = m_named.group(1)
            m_stop = re.search(r"\s(?:on|at|due|by|for|in)(?!\w)", cand, re.IGNORECASE)
            if m_stop:
                cand = cand[:m_stop.start()]
            cand = cand.strip(" .!?:;'\"")
            if cand:
                title = cand
                break

    # Strategy B: Quotes: "add a deadline ... 'title'" or "task 'title'"
    if not title:
        m_quote = re.search(r"['\"]([^'\"]{3,})['\"]", msg)
        if m_quote:
            title = m_quote.group(1).strip(" .!?:;'\"")

    # Helper to strip date patterns from candidate title
    def _strip_dates_and_times(text_cand: str) -> str:
        if not text_cand:
            return ""
        t = text_cand.strip(" .!?:;'\"")
        month_rx = "|".join(MONTH_MAP.keys())
        patterns = [
            rf"\b(?:on|at|due|by|for|in)?\s*\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?({month_rx})\b(?:\s+\d{{4}})?",
            rf"\b(?:on|at|due|by|for|in)?\s*({month_rx})\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:\s+\d{{4}})?",
            r"\b(?:on|at|due|by|for|in)?\s*(?:today|tomorrow|yesterday)\b",
            r"\b(?:next|this)?\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b(?:at\s+)?(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\s*(?:am|pm)?\b",
            r"\b(?:at\s+)?(?:1[0-2]|0?[1-9])\s*(?:am|pm)\b",
            r"\b(?:at\s+)?(?:midnight|noon)\b",
            r"^\s*(?:on|at|due|by|in|for)\s+",
            r"\s+(?:on|at|due|by|in|for)\s*$",
        ]
        for p in patterns:
            t = re.sub(p, "", t, flags=re.IGNORECASE)
        return t.strip(" .!?:;'\"")

    # Strategy C: "remind me to X [by/on/at ...]"
    if not title and "remind me to " in msg_lower:
        idx = msg_lower.find("remind me to ") + len("remind me to ")
        rest = msg[idx:]
        m_split = re.split(r"\b(?:by|on|at|due|before|in\s+(?:\d+|a|an|one|two|three|the\s+(?:morning|afternoon|evening))|tomorrow|today|yesterday|next\s+[a-z]+|this\s+[a-z]+)\b", rest, flags=re.IGNORECASE)
        title = m_split[0].strip(" .!?:;'\"")

    # Strategy D: Prefix removal for standard forms:
    if not title:
        prefixes = (
            "add a deadline on", "add a deadline for", "add a deadline:", "add a deadline", "add deadline on", "add deadline for", "add deadline:", "add deadline",
            "set a deadline for", "set a deadline on", "set a deadline:", "set a deadline", "create a deadline for", "create a deadline on", "create a deadline:", "create a deadline",
            "add a task for", "add a task on", "add a task:", "add a task", "add task for", "add task on", "add task:", "add task",
            "create a task for", "create a task on", "create a task:", "create a task", "create task for", "create task on", "create task:", "create task", "new task:", "new task", "new deadline:", "new deadline",
        )
        for pref in prefixes:
            if msg_lower.startswith(pref) and not msg_lower[len(pref):len(pref) + 1].isalnum():
                rest = msg[len(pref):].strip(" :,-")
                rest = re.sub(r"^(?:please\s*[:\-\u2013]?|for\s+me\s*[:\-\u2013]?)\s*", "", rest, flags=re.IGNORECASE)
                cleaned = _strip_dates_and_times(rest)
                cleaned = re.sub(r"\bdomain[:= ]\s*[a-z0-9_-]+", "", cleaned, flags=re.IGNORECASE).strip(" .!?:;'\"")
                if cleaned and cleaned.lower() not in ("tomorrow", "today", "yesterday"):
                    title = cleaned
                break

    # Strategy E: the text that follows the creation phrase ("please create a task: write report by friday")
    if not title:
        m_after = _AFTER_CREATION_PHRASE.search(msg)
        if m_after:
            title = _strip_dates_and_times(m_after.group(1)).strip(" .!?:;'\"")

    # Final guard: if title after stripping dates is empty or was purely date words/digits/time, clear it
    if title:
        residual = _strip_dates_and_times(title)
        if not residual or re.fullmatch(r"[\d:\sAPMapm\.,\-]+", residual) or title_problem(residual):
            title = ""
        else:
            title = residual

    if title:
        if title.islower():
            title = title[0].upper() + title[1:]

    res: dict[str, Any] = {"title": title, "domain": domain}
    if due_str:
        res["due_date"] = due_str
    if time_12:
        res["time_str"] = time_12
    has_explicit_year = bool(re.search(r"\b20\d{2}\b", msg))
    if parsed_date and not has_explicit_year and parsed_date.year > _current_today().year:
        res["roll_forward_note"] = f"(Note: {parsed_date.strftime('%B %d')} has passed this year; scheduled for {parsed_date.year})"
    return res


_PURE_CONVERSATIONAL = {
    "hi", "hello", "hey", "greetings", "good morning", "good evening",
    "good afternoon", "how are you", "who are you", "what are you",
    "what can you do", "what do you do", "help", "thank you", "thanks",
    "bye", "goodbye", "tell me a joke", "what is compass", "who created you",
    "what can you help with", "what can you help me with", "how are you doing",
    "hey, what can you help with", "hey what can you help with",
}

_TOOL_KEYWORDS = (
    "task", "tasks", "todo", "todos", "due", "deadline", "deadlines",
    "backlog", "work on", "workload", "priority", "status", "pending", "upcoming",
    "add", "create", "new", "schedule", "reschedule", "postpone", "delete",
    "remove", "edit", "update", "mark", "finish", "complete", "done", "cancel",
    "drop", "move", "push back", "assign", "defer",
    "list", "show", "what do i have", "do i have", "what's on",
    "whats on", "check", "agenda", "today", "tomorrow", "yesterday", "this week", "next week",
    "coursework", "course", "assignment", "homework", "syllabus", "notes",
    "lecture", "lab", "exam", "quiz", "test", "midterm", "final", "paper",
    "essay", "study", "reading",
    "hackathon", "project", "projects", "devpost", "submission", "track",
    "prize", "pitch", "demo",
    "code", "repo", "repository", "snippet", "commit", "branch", "pr",
    "pull request", "architecture", "git", "github", "issue", "issues", "bug", "bugs",
    "calendar", "event", "events", "meeting", "meetings", "sync",
    "availability", "available", "conflict", "conflicts", "clash", "free time", "busy", "slot", "slots",
    "search", "web", "lookup", "research", "verify", "tavily", "online",
    "url", "http", "https", "find", "documentation", "doc", "docs",
    "feasible", "feasibility", "finish in time", "can i finish", "what to drop",
    "what should i drop", "what i drop", "triage", "overload", "overloaded",
    "overcommit", "capacity",
    "memory", "remember that", "remember my", "remember to", "recall", "stored", "save", "log", "note", "notes",
    "remind", "reminder", "call me", "my name is", "my name's", "prefer",
    "preference", "forget my", "forget that", "forget what i", "my goal",
    "park that", "park it", "park this", "come back to that", "parked shelf", "list parked",
    "planner", "agent", "plan", "execute",
)

_TOOL_KEYWORDS_REGEX = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in sorted(_TOOL_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


LONG_FORM_CUES = (
    "hour-by-hour", "hour by hour", "step-by-step", "step by step", "detailed", "in detail",
    "in depth", "in-depth", "comprehensive", "full plan", "a plan for", "give me a plan",
    "concrete plan", "roadmap for", "outline", "checklist", "as a table", "in a table",
    "with a table", "table of", "write a ", "draft a ", "essay", "walk me through", "compare",
    "pros and cons", "migration plan", "action plan", "timeline for", "schedule for the",
)


def is_long_form_request(message: str) -> bool:
    """Return True when the message asks for a long structured deliverable (plan, table, outline...)."""
    lowered = (message or "").lower()
    return any(cue in lowered for cue in LONG_FORM_CUES)


def message_needs_tools(message: str) -> bool:
    """Determine whether a user message requires tool registry evaluation.
    Uses whole-word matching to avoid false positives (e.g. 'pr' in 'protocol', 'git' in 'digital').
    """
    msg = message.lower().strip()
    if not msg:
        return False

    cleaned = msg.strip("!?.,:; ")
    if cleaned in _PURE_CONVERSATIONAL:
        return False

    return bool(_TOOL_KEYWORDS_REGEX.search(msg))


def is_greeting_intent(message: str) -> bool:
    """Determine whether message is strictly a greeting or orientation inquiry.
    Must NEVER match actionable task, calendar, schedule, conflict, or domain queries.
    """
    if not message or not message.strip():
        return True

    msg_lower = message.lower().strip()
    clean_msg = msg_lower.strip("!@#$%^&*()-_=+[]{}|;:'\",.<>?/`~ \t\n\r")

    # Domain / Action guard: if it mentions tasks, schedule, code, etc. it is NEVER a greeting
    action_words = (
        "task", "tasks", "todo", "todos", "deadline", "deadlines", "due",
        "schedule", "scheduling", "calendar", "conflict", "conflicts", "clash", "clashes",
        "propose", "plan", "planning", "review", "focus", "weekend", "week",
        "coursework", "hackathon", "devpost", "repo", "code", "bug", "pr", "commit",
        "feasibility", "triage", "overload", "capacity", "remember", "forget", "park",
    )
    if any(w in clean_msg for w in action_words):
        return False

    exact_greetings = {
        "hi", "hello", "hey", "howdy", "greetings", "good morning", "good afternoon",
        "good evening", "good day", "morning", "evening", "afternoon",
        "help", "help me", "start", "getting started",
        "hello compass", "hi compass", "hey compass",
        "hey there", "hello there", "hi there",
    }
    if clean_msg in exact_greetings:
        return True

    greeting_phrases = (
        "who are you", "what are you", "what is compass", "what can you do",
        "what can compass do", "how does this work", "how do you work",
        "how can you help", "tell me about yourself",
    )
    return any(p in clean_msg for p in greeting_phrases)


def is_tavily_verification_intent(message: str) -> bool:
    """Determine whether message is an explicit request to verify facts, deadlines, or claims with Tavily.

    Recognizes:
    - Direct button commands: 'Verify with Tavily', 'Verify this with Tavily', 'Verify it with Tavily'
    - Conversational queries: 'Can you verify that?', 'Verify the claim you just made', 'Fact-check the previous answer'
    - Targeted event verification: 'Verify the Nebius deadline with Tavily', 'Check this deadline with Tavily'
    """
    if not message or not message.strip():
        return False
    msg_l = message.lower().strip()

    # Direct Tavily mentions + verification verbs
    if "tavily" in msg_l and any(k in msg_l for k in ("verify", "fact-check", "fact check", "factcheck", "check", "confirm", "investigate", "research")):
        return True

    # Explicit conversational verification intents referring to prior claims/answers
    conversational_verify_patterns = (
        "verify this with tavily",
        "verify it with tavily",
        "verify that with tavily",
        "verify with tavily",
        "check this deadline with tavily",
        "check this with tavily",
        "check it with tavily",
        "fact-check this answer using tavily",
        "fact check this answer using tavily",
        "fact-check this using tavily",
        "fact check this using tavily",
        "fact-check with tavily",
        "fact check with tavily",
        "can you verify that",
        "can you verify this",
        "can you verify it",
        "can you fact-check that",
        "can you fact check that",
        "can you fact-check this",
        "can you fact check this",
        "verify this",
        "verify that",
        "verify it",
        "verify the claim you just made",
        "verify what you just said",
        "verify your claim",
        "fact-check the previous answer",
        "fact check the previous answer",
        "fact-check the previous claim",
        "fact check the previous claim",
        "fact-check your answer",
        "fact check your answer",
        "fact-check this answer",
        "fact check this answer",
        "check this deadline",
        "check that deadline",
    )
    # Match if any exact pattern matches or message starts with / ends with pattern
    clean_msg = re.sub(r"[^\w\s-]", "", msg_l).strip()
    for p in conversational_verify_patterns:
        clean_p = re.sub(r"[^\w\s-]", "", p).strip()
        if clean_p in clean_msg or clean_msg.startswith(clean_p) or clean_msg.endswith(clean_p):
            return True

    if re.search(r"\bverify\s+(?:the\s+)?(?:[\w-]+\s+)?deadline\b", msg_l):
        return True

    return False


def extract_claim_and_entity_from_text(text: str, user_query: str = "") -> Tuple[str, Optional[str]]:
    """Extract specific factual assertions, entity, and deadline details from candidate text.

    Returns:
        (claim_to_investigate, target_entity)
    """
    if not text or not text.strip():
        return "", None

    clean_text = text.strip()
    if is_tavily_verification_intent(clean_text):
        return "", None

    # Strip [[modes...]] markers if present without backtracking
    clean_text = re.sub(r"\[\[[^\[\]\n]*\]\]", "", clean_text).strip()

    # 1. Identify Target Entity
    target_entity: Optional[str] = None
    query_lower = (user_query or "").lower()

    # Check if user query mentions a specific entity
    known_event_tokens = ("nebius", "nvidia", "chroma", "devpost", "google", "hackathon", "buildathon", "kaggle")
    for tok in known_event_tokens:
        if tok in query_lower:
            m_entity = re.search(rf"\b({tok}(?:\s+(?:[xX&]\s+)?[\w-]+){{0,5}}\s+(?:hackathon|buildathon|awards|challenge|competition|grant))\b", clean_text, re.IGNORECASE)
            if m_entity:
                target_entity = m_entity.group(1).strip()
                break
            if tok in ("nebius", "nvidia") and ("nebius" in clean_text.lower() or "nvidia" in clean_text.lower()):
                m_neb = re.search(r"\b(Nebius(?:\s+[xX&]\s+NVIDIA)?(?:\s+Global)?(?:\s+AI)?\s+Hackathon)\b", clean_text, re.IGNORECASE)
                if m_neb:
                    target_entity = m_neb.group(1).strip()
                    break

    if not target_entity:
        # Search for full event or organization names in the candidate text (bounded non-overlapping repetition)
        event_match = re.search(
            r"\b([A-Z][a-zA-Z0-9_-]*(?:\s+(?:[xX&]\s+)?[A-Z][a-zA-Z0-9_-]*){0,5}\s+(?:Hackathon|Buildathon|Awards|Challenge|Competition|Fellowship|Internship|Grant|Program))\b",
            clean_text,
        )
        if event_match:
            target_entity = event_match.group(1).strip()
        else:
            # Fallback to capitalized brand name
            brand_match = re.search(r"\b(Nebius|NVIDIA|Chroma|Devpost|ElevenLabs|Google Cloud|OpenAI|Anthropic)\b", clean_text)
            if brand_match:
                target_entity = brand_match.group(1).strip()

    # 2. Extract Deadline Assertion Sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", clean_text) if s.strip()]

    deadline_keywords = (
        "submission deadline", "submissions close", "submission period",
        "deadline is", "deadline:", "due on", "due by", "closes on", "closes at",
        "deadline", "due date", "submission", "due",
    )
    date_regex = re.compile(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|\d{1,2}(?:st|nd|rd|th)?)\b",
        re.IGNORECASE,
    )

    candidate_sentence = None
    for s in sentences:
        s_low = s.lower()
        if any(dk in s_low for dk in deadline_keywords) and date_regex.search(s):
            candidate_sentence = s
            break

    if not candidate_sentence:
        # Check for any sentence containing both a deadline keyword and numbers/dates
        for s in sentences:
            s_low = s.lower()
            if any(dk in s_low for dk in deadline_keywords) and re.search(r"\b\d{1,4}\b", s):
                candidate_sentence = s
                break

    if candidate_sentence:
        # Clean markdown formatting from the candidate sentence
        clean_sentence = re.sub(r"[*_`#>-]", "", candidate_sentence).strip()
        clean_sentence = re.sub(r"\s+", " ", clean_sentence).strip()

        # If the sentence does NOT mention the target entity, integrate it for clarity
        if target_entity and target_entity.lower() not in clean_sentence.lower():
            claim = f"The {target_entity}'s {clean_sentence[0].lower() + clean_sentence[1:] if clean_sentence.startswith('S') or clean_sentence.startswith('D') else clean_sentence}"
        else:
            claim = clean_sentence
        return claim, target_entity

    # 3. Fallback: If no deadline sentence found, take the first informative factual sentence
    for s in sentences:
        clean_s = re.sub(r"[*_`#>-]", "", s).strip()
        if len(clean_s) > 20 and not clean_s.lower().startswith(("how can i", "sure", "here is", "let me know")):
            if target_entity and target_entity.lower() not in clean_s.lower():
                return f"{target_entity}: {clean_s}", target_entity
            return clean_s, target_entity

    # Final fallback: return trimmed clean text with entity
    if target_entity:
        return f"{target_entity} submission deadline", target_entity
    return clean_text[:200].strip(), None


async def resolve_verification_claim_and_entity(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    target_message_id: Optional[str] = None,
    target_message_content: Optional[str] = None,
    pool: Optional[Any] = None,
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    recent_history: Optional[list[dict[str, str]]] = None,
) -> Tuple[str, Optional[str]]:
    """Resolve the specific claim and entity to verify, strictly enforcing tenant isolation and conversation boundaries."""
    effective_history = history or recent_history
    # 1. Server-authoritative target message check:
    # When target_message_id is present, load the message text from the DB after ownership verification.
    # IGNORE client-sent target_message_content in that case. If foreign or invalid ID, REJECT.
    if target_message_id:
        effective_uid = user_id or guest_id
        if pool is None:
            try:
                from backend.memory.db import get_pool
                pool = await get_pool()
            except Exception:
                pool = None

        if pool and effective_uid:
            try:
                async with pool.acquire() as conn:
                    mid = int(target_message_id) if str(target_message_id).isdigit() else None
                    if mid is not None:
                        row = await conn.fetchrow(
                            """
                            SELECT m.content
                            FROM messages m
                            JOIN conversations c ON m.conversation_id = c.id
                            WHERE m.id = $1 AND (c.user_id = $2 OR c.guest_id = $2)
                            """,
                            mid,
                            effective_uid,
                        )
                        if row and row["content"]:
                            claim, entity = extract_claim_and_entity_from_text(row["content"], user_query=message)
                            if claim and not is_tavily_verification_intent(claim):
                                return claim, entity
                            return "", None
                        else:
                            logger.warning("Target message ID %s not found or foreign tenant access for user %s: REJECTED", target_message_id, effective_uid)
                            return "", None
                    else:
                        logger.warning("Invalid target message ID %s: REJECTED", target_message_id)
                        return "", None
            except Exception as e:
                logger.warning("Error fetching target message by ID %s: %s; rejecting", target_message_id, e)
                return "", None
        else:
            # If target_message_id was supplied but no pool/user_id available to verify ownership, reject
            logger.warning("Target message ID %s supplied without db pool or user_id for verification: REJECTED", target_message_id)
            return "", None

    # 2. Fallback for unpersisted messages: Use client-sent content ONLY when target_message_id is absent.
    # Cap length at 4000 chars, strip control characters, and treat it as untrusted.
    if target_message_content and target_message_content.strip():
        untrusted = target_message_content[:4000]
        sanitized_content = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", untrusted).strip()
        if sanitized_content:
            claim, entity = extract_claim_and_entity_from_text(sanitized_content, user_query=message)
            if claim and not is_tavily_verification_intent(claim):
                return claim, entity

    # 3. Check if user provided an explicit claim inside their message (e.g. 'Verify with Tavily: claim text')
    msg_clean = message.strip()
    m_direct = re.search(
        r"(?:verify(?:\s+it|\s+this)?\s+with\s+tavily|fact-?check(?:\s+this\s+answer|\s+this)?\s+using\s+tavily|check\s+(?:this\s+deadline|this|it)\s+with\s+tavily)[:\s]+(?:that\s+)?(.+)",
        msg_clean,
        re.IGNORECASE,
    )
    if m_direct and m_direct.group(1).strip():
        extracted = m_direct.group(1).strip().strip('"\'')
        # Ensure extracted is not another generic intent
        if len(extracted) > 6 and not is_tavily_verification_intent(extracted):
            # Check for entity inside extracted
            _, entity = extract_claim_and_entity_from_text(extracted, user_query=message)
            return extracted, entity

    # 4. Resolve against conversation history (most recent assistant message)
    if effective_history:
        for prev in reversed(effective_history):
            if isinstance(prev, dict) and prev.get("role") == "assistant":
                content = (prev.get("content") or "").strip()
                if content and not is_tavily_verification_intent(content):
                    claim, entity = extract_claim_and_entity_from_text(content, user_query=message)
                    if claim and not is_tavily_verification_intent(claim):
                        return claim, entity

    # 5. Security & Invariant Guard: NEVER return the verification instruction itself as the claim
    if is_tavily_verification_intent(msg_clean):
        # Extract entity if mentioned in query (e.g. 'Verify the Nebius deadline with Tavily')
        m_ent = re.search(r"\b(Nebius|NVIDIA|Chroma|Devpost|Google)\b", msg_clean, re.IGNORECASE)
        if m_ent:
            ent = m_ent.group(1).capitalize()
            return f"{ent} deadline", ent
        return "", None

    return msg_clean, None


def extract_verification_target(message: str, history: Optional[list[dict[str, str]]] = None) -> str:
    """Extract the specific statement or claim to verify, resolving 'it'/'this' against prior assistant messages."""
    # Synchronous wrapper for backward-compatibility with tests
    msg_clean = message.strip()
    m_direct = re.search(
        r"(?:verify(?:\s+it|\s+this)?\s+with\s+tavily|fact-?check(?:\s+this\s+answer|\s+this)?\s+using\s+tavily|check\s+(?:this\s+deadline|this|it)\s+with\s+tavily)[:\s]+(?:that\s+)?(.+)",
        msg_clean,
        re.IGNORECASE,
    )
    if m_direct and m_direct.group(1).strip():
        extracted = m_direct.group(1).strip().strip('"\'')
        if len(extracted) > 6 and not is_tavily_verification_intent(extracted):
            return extracted

    if history:
        for prev in reversed(history):
            if isinstance(prev, dict) and prev.get("role") == "assistant":
                content = (prev.get("content") or "").strip()
                if content:
                    claim, _ = extract_claim_and_entity_from_text(content, user_query=message)
                    if claim and not is_tavily_verification_intent(claim):
                        return claim

    if is_tavily_verification_intent(msg_clean):
        m_ent = re.search(r"\b(Nebius|NVIDIA|Chroma|Devpost|Google)\b", msg_clean, re.IGNORECASE)
        if m_ent:
            return f"{m_ent.group(1).capitalize()} submission deadline"
        return "submission deadline"

    return msg_clean


def is_schedule_or_agent_intent(message: str) -> bool:
    """Determine whether message is an autonomous calendar schedule, slot allocation, or conflict rebalancing intent."""
    if not message or not message.strip():
        return False

    msg_lower = message.lower().strip()

    # Informational or definitional queries about roadmaps should NOT be treated as scheduling/agent intent
    informational_patterns = (
        "what is a roadmap", "what is a product roadmap", "what is roadmap",
        "define roadmap", "definition of roadmap", "explain roadmap", "tell me about roadmap",
        "explain what a roadmap is", "what does roadmap mean",
    )
    if any(inf in msg_lower for inf in informational_patterns):
        return False

    schedule_phrases = (
        "propose a focus schedule", "propose schedule", "focus schedule",
        "propose a schedule", "propose my schedule", "suggest a schedule",
        "check my weekend schedule", "weekend schedule", "schedule for conflicts",
        "check schedule conflicts", "schedule conflicts", "calendar conflicts",
        "deadline conflicts", "conflict across", "conflicts across",
        "calendar clash", "calendar clashes", "schedule clash", "schedule clashes",
        "plan my week", "plan my weekend", "plan this week",
        "focus schedule for this week", "schedule for this week", "schedule for tomorrow",
        "what is my schedule", "check my schedule",
        "roadmap", "what should i do today", "prioritize my tasks",
        "prioritize tasks", "prioritize my day", "prioritize my deliverables",
    )
    if any(phrase in msg_lower for phrase in schedule_phrases):
        return True

    # Check for calendar/schedule + conflict combination or slot allocation
    if "schedule" in msg_lower and any(w in msg_lower for w in ("conflict", "conflicts", "clash", "clashes", "propose", "rebalance", "tomorrow", "weekend", "week", "allocation")):
        return True

    return False


PERSONAL_SCOPE_TRIGGERS = (
    "my ", "mine", "i have", "i need", "assigned to me", "show my", "list my",
    "what should i", "my task", "my tasks", "my deadline", "my deadlines",
    "work on first", "my coursework", "my hackathon", "tracked", "what do i",
    "homework", "assignment", "exam", "quiz", "lecture", "essay",
)

PUBLIC_EVENT_INDICATORS = (
    "when is the", "what is the deadline for", "what is the submission deadline for",
    "submission deadline for", "official deadline", "global ai hackathon",
    "nebius", "hackathon deadline for", "date of the", "rules for", "when does the"
)


def should_route_to_query_tasks(message: str) -> bool:
    """Evaluate whether message should route to query_tasks internal database queries.

    Public-event questions (e.g. Nebius deadline) return False.
    Personal scope questions ('show my hackathon tasks') return True.
    """
    msg_l = message.lower()
    is_public = any(ind in msg_l for ind in PUBLIC_EVENT_INDICATORS)
    has_personal = any(p in msg_l for p in PERSONAL_SCOPE_TRIGGERS)
    if is_public and not has_personal:
        return False
    has_task_terms = any(term in msg_l for term in ("task", "tasks", "due", "deliverable", "deadline", "coursework", "hackathon", "work on", "start with", "first", "roadmap", "prioritize"))
    return has_task_terms and has_personal


PERSONAL_TRACKED_CUES = (
    "my task", "my tasks", "my deadline", "my deadlines", "my schedule", "my todo",
    "my list", "my plate", "my coursework", "my hackathon tasks",
    "what should i work on", "what should i do today", "what should i tackle",
    "work on first", "start with", "overdue", "tracked", "show my", "list my",
    "prioritize my", "plan my day", "plan my week", "this week's tasks",
)

EXTERNAL_PROJECT_CUES = (
    "we want to build", "we're building", "we are building", "i want to build",
    "i'm building", "i am building", "our project", "our team", "our app",
    "team of", "my project", "hour-by-hour", "for a hackathon", "for my hackathon",
    "hackathon project", "tech stack", "architecture", "should i use", "should we use",
    "pitch", "recommend", "tradeoff", "trade-off", "compare", " vs ",
    "how do i build", "how should we", "help me write", "mvp",
)


def is_external_project_request(message: str) -> bool:
    """Return True for a general planning/advice/writing request about a project the user describes.

    Such a request has at least one external-project cue and no cue that it is about the
    user's own tracked tasks. Plain substring checks only (no regexes).
    """
    msg_l = message.lower()
    if any(cue in msg_l for cue in PERSONAL_TRACKED_CUES):
        return False
    return any(cue in msg_l for cue in EXTERNAL_PROJECT_CUES)


def _fallback_route(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    tone: Optional[str] = None,
) -> Tuple[Optional[str], Optional[dict[str, Any]], str]:
    """Fallback route logic when LLM router is unavailable or in mock mode."""
    msg_lower = message.lower()

    # 1. Personal fact forget
    is_negative_or_idiomatic_forget = any(
        neg in msg_lower for neg in (
            "don't forget", "dont forget", "do not forget", "never forget",
            "forget about it", "forget it", "i forgot", "forgot to"
        )
    )
    if not is_negative_or_idiomatic_forget:
        for prefix in ("forget my ", "forget that i ", "forget what i said about ", "forget what i said regarding "):
            if prefix in msg_lower:
                target = msg_lower.split(prefix, 1)[-1].strip(".!? ")
                if target:
                    return "forget_fact", {"key": target.replace(" ", "_")[:40]}, ""

    # 2. Check personal name and/or goal
    if any(k in msg_lower for k in ("call me ", "my name is ", "my name's ")):
        for prefix in ("call me ", "my name is ", "my name's "):
            if prefix in msg_lower:
                rest = message[msg_lower.find(prefix) + len(prefix):]
                if " and my goal" in rest.lower():
                    name_val = rest[:rest.lower().find(" and my goal")].strip(" .!?,;")
                else:
                    name_val = rest.strip(" .!?")
                if name_val:
                    return "remember_fact", {"key": "name", "value": name_val[:200]}, ""

    if any(prefix in msg_lower for prefix in ("my goal is ", "my goal: ")):
        for prefix in ("my goal is ", "my goal: "):
            if prefix in msg_lower:
                goal_val = message[msg_lower.find(prefix) + len(prefix):].strip(" .!?")
                if goal_val:
                    return "remember_fact", {"key": "goal", "value": goal_val[:200]}, ""

    # 3. Remember personal preference/fact (only when NOT task/deadline oriented)
    has_task_terms = any(term in msg_lower for term in (
        "due", "deadline", "task", "deliverable", "submit", "submission",
        "demo", "presentation", "meeting", "exam", "assignment", "homework", "milestone"
    ))
    if ("remember that " in msg_lower or "remember my " in msg_lower) and not has_task_terms:
        for prefix in ("remember that i prefer ", "remember that i like ", "remember that my goal is ", "remember that i ", "remember that "):
            if prefix in msg_lower:
                fact_val = message[msg_lower.find(prefix) + len(prefix):].strip(" .!?")
                if fact_val:
                    key = "preference" if "prefer" in prefix or "like" in prefix else "user_fact"
                    return "remember_fact", {"key": key, "value": fact_val[:200]}, ""

    # 4. Park it shelf detection
    if any(lp in msg_lower for lp in ("list parked", "show parked", "what is parked", "what's parked", "what did i park", "view parked", "parked shelf")):
        return "list_parked", {}, ""

    res_match = re.search(r"(?:resolve parked|mark parked|done with parked|finish parked)\s*#?(\d+)", msg_lower)
    if res_match:
        return "resolve_parked", {"thought_id": int(res_match.group(1))}, ""

    park_triggers = ("park that", "park it", "park this for later", "park this", "let's come back to that", "lets come back to that", "come back to that later")
    is_park_action = any(trigger in msg_lower for trigger in park_triggers)
    is_ordinary_park = any(term in msg_lower for term in ("car", "vehicle", "parking", "garage", "lot", "national park", "amusement park", "in the park", "to the park", "at the park", "walk in the park", "dog park"))
    if is_park_action and not is_ordinary_park:
        park_text = message
        for trig in (
            "park that:", "park that -", "park that ",
            "park this for later:", "park this for later ",
            "park this:", "park this ",
            "let's come back to that:", "let's come back to that ",
            "lets come back to that:", "lets come back to that ",
        ):
            if trig in msg_lower:
                idx = msg_lower.find(trig) + len(trig)
                extracted_text = message[idx:].strip(" .!?")
                if extracted_text:
                    park_text = extracted_text
                    break
        if park_text.lower().strip(" .!?") in ("park that", "park it", "park this", "let's come back to that", "lets come back to that"):
            if history:
                for h in reversed(history):
                    h_content = h.get("content")
                    if h_content:
                        park_text = h_content[:200]
                        break
        return "park_thought", {"text": park_text[:200]}, ""

    # 5. Schedule & Task Autonomous Intent Detection
    if is_schedule_or_agent_intent(message):
        return "agent", {"goal": message}, ""

    # 6. Career Copilot & Resume Studio Intent Detection
    if any(term in msg_lower for term in ("cover letter", "draft a cover letter", "draft cover letter", "write a cover letter", "application response")):
        return "draft_cover_letter", {"target_company": message}, ""

    if any(term in msg_lower for term in ("tailor resume", "tailor my resume", "tailor cv", "tailor my cv", "prepare my resume", "prepare resume")):
        return "tailor_resume", {"target_company": message}, ""

    if any(term in msg_lower for term in ("prepare application", "prepare my application", "prepare job application")):
        return "prepare_application", {"opportunity_id": 1001}, ""

    if any(term in msg_lower for term in ("submit approved", "submit batch", "submit my applications", "submit approved applications")):
        return "submit_approved_application_batch", {"batch_id": "latest"}, ""

    if any(term in msg_lower for term in (
        "application deadline", "application deadlines", "which deadlines are approaching",
        "deadlines approaching", "closing soon", "upcoming application deadlines",
        "internship deadlines", "radar deadlines"
    )):
        return "check_application_deadlines", {"days_ahead": 30}, ""

    if any(term in msg_lower for term in ("already submitted", "have i submitted", "i have submitted")):
        return "track_career_applications", {"status": "SUBMITTED"}, ""

    if any(term in msg_lower for term in ("need my review", "needs review", "ready for review")):
        return "track_career_applications", {"status": "READY_FOR_REVIEW"}, ""

    if any(term in msg_lower for term in ("my applications", "track applications", "application status", "tracked applications", "applications pending")):
        return "track_career_applications", {}, ""

    # 7. Internship Radar Intent Detection
    if any(term in msg_lower for term in ("internship", "internships", "research fellowship", "research program", "early-career program", "step intern", "radar", "eligible for", "am i eligible", "eligibility", "academic year")):
        category = "ai_ml" if any(k in msg_lower for k in ("ai", "ml", "machine learning", "deep learning")) else (
            "research" if "research" in msg_lower else None
        )
        status = "OPEN_CONFIRMED" if any(k in msg_lower for k in ("open", "today", "now", "apply now", "currently")) else None
        return "query_internship_radar", {"query": message, "category": category, "status": status, "india_only": True}, ""

    if any(term in msg_lower for term in ("feasibility", "can i finish", "what to drop", "what should i drop", "what i drop", "triage", "overloaded", "overcommit", "adversarial")):
        days_match = re.search(r"\b([0-9]{1,4})\s*days?\b", msg_lower)
        hours_match = re.search(r"\b([0-9]{1,4}(?:\.[0-9]{1,2})?)\s*hours?\b", msg_lower)
        f_days = int(days_match.group(1)) if days_match else 5
        f_hours = float(hours_match.group(1)) if hours_match else 4.0
        return "assess_feasibility", {"days": f_days, "hours_per_day": f_hours}, ""
    if is_pending_action_confirm(message):
        return "pending_action_confirm", {"message": message}, ""
    if is_pending_action_cancel(message):
        return "pending_action_cancel", {"message": message}, ""
    is_del, is_clear, del_target = is_chat_delete_intent(message)
    if is_del:
        return "chat_delete_task", {"query": del_target, "clear_all": is_clear}, ""
    if is_undo_request(message):
        return "undo", {"message": message}, ""
    if is_explicit_task_creation(message):
        task_args = _extract_task_creation_args(message)
        if not task_args.get("title"):
            return None, None, "What would you like to name this task? Please provide a title or description."
        return "add_task", task_args, ""

    is_public = any(ind in msg_lower for ind in PUBLIC_EVENT_INDICATORS)
    has_personal = any(p in msg_lower for p in PERSONAL_SCOPE_TRIGGERS)

    if is_public and not has_personal:
        return "search_web", {"query": message}, ""

    if not (is_public and not has_personal) and not is_external_project_request(message):
        if history:
            for h in reversed(history):
                content = h.get("content", "")
                if any(term in content.lower() for term in ("task", "deliverable", "due", "demo", "submit", "video")):
                    return "query_tasks", {"user_message": message, "query": message}, ""
        if should_route_to_query_tasks(message) or any(term in msg_lower for term in ("task", "tasks", "due", "deliverable", "deadline", "coursework", "hackathon", "roadmap", "prioritize")):
            query_args: dict[str, Any] = {"query": message, "user_message": message}
            if any(w in msg_lower for w in ("roadmap", "plan", "today", "prioritize", "attention", "step-by-step", "step by step", "work on first", "start with")):
                query_args["intent"] = "roadmap"
            return "query_tasks", query_args, ""
    if is_greeting_intent(message):
        from backend.persona import format_greeting_by_tone
        return None, None, format_greeting_by_tone(tone)

    return None, None, ""
