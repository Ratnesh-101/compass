"""
Compass — LLM Router using Nemotron-3 Nano.

Dispatches user messages to skills via native OpenAI function calling.
Probed and verified on Nebius Token Factory with nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B.
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional, Dict, Tuple
from openai import OpenAI, AsyncOpenAI
from backend.config import get_settings
from backend.skills import TOOL_DEFINITIONS

logger = logging.getLogger("compass.router")
settings = get_settings()

TOOLS = TOOL_DEFINITIONS

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

DAYS_OF_WEEK = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def get_openai_client() -> AsyncOpenAI:
    """Return configured AsyncOpenAI client for Nebius Token Factory."""
    return AsyncOpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
        timeout=15.0,
    )


def is_explicit_task_creation(message: str) -> bool:
    """Determine whether message represents an explicit command to add a task/deadline/reminder."""
    msg = message.lower().strip()
    if not msg:
        return False

    # Queries, questions, or passive statements must NOT be treated as task creation
    if re.search(r"^(when\s+is|what\s+is|what's|where\s+is|who\s+is|how\s+to|why\s+is|is\s+there|are\s+there|tell\s+me|show\s+me|check\s+the|find\s+the|do\s+i\s+have)\b", msg):
        return False
    if msg.endswith("?"):
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
    if re.search(r"\b(add|create|new|set|schedule|put|track)\b.*\b(deadline|task|todo|reminder)\b", msg):
        return True

    return False


def is_undo_request(message: str) -> bool:
    """Check if message is an undo/revert command."""
    msg = message.lower().strip()
    return msg in ("undo", "undo that", "revert", "revert that", "undo last action", "undo task")



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
        dt = datetime.strptime(time_24, "%H:%M")
        time_12 = dt.strftime("%-I:%M %p") if hasattr(dt, "strftime") else f"{hh}:{mm}"
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
        today = date.today()

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


def _extract_task_creation_args(message: str) -> dict:
    """Extract title, domain, due_date, time_str, and priority from natural language."""
    msg = message.strip()
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
    m_named = re.search(
        r"(?:with the name|named|called|titled)\s+[:\"']?([^\"'\n,;]+?)[:\"']?(?:\s+(?:on|at|due|by|for|in)\b|$)",
        msg,
        re.IGNORECASE,
    )
    if m_named:
        title = m_named.group(1).strip(" .!?:;'\"")

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
            r"^\s*(?:on|at|due|by|in)\s+",
            r"\s+\b(?:on|at|due|by|in)\s*$",
        ]
        for p in patterns:
            t = re.sub(p, "", t, flags=re.IGNORECASE)
        return t.strip(" .!?:;'\"")

    # Strategy C: "remind me to X [by/on/at ...]"
    if not title and "remind me to " in msg_lower:
        idx = msg_lower.find("remind me to ") + len("remind me to ")
        rest = msg[idx:]
        m_split = re.split(r"\b(?:by|on|at|due|before|in|tomorrow|today|yesterday|next\s+[a-z]+|this\s+[a-z]+)\b", rest, flags=re.IGNORECASE)
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
            if msg_lower.startswith(pref):
                rest = msg[len(pref):].strip(" :,-")
                cleaned = _strip_dates_and_times(rest)
                cleaned = re.sub(r"\bdomain[:= ]\s*[a-z0-9_-]+", "", cleaned, flags=re.IGNORECASE).strip(" .!?:;'\"")
                if cleaned and cleaned.lower() not in ("tomorrow", "today", "yesterday"):
                    title = cleaned
                break

    # Strategy E: Fallback clean-up if still empty
    if not title:
        cand = re.sub(r"\b(add|create|new|set|schedule|remind me to|a deadline|deadline|a task|task|todo)\b", "", msg, flags=re.IGNORECASE)
        cand = _strip_dates_and_times(cand)
        cand = cand.strip(" .!?:;'\"")
        date_words = {"tomorrow", "today", "yesterday", "october", "deadline", "task", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
        if len(cand) >= 1 and not any(kw == cand.lower() for kw in date_words):
            title = cand

    # Final guard: if title after stripping dates is empty or was purely date words/digits/time, clear it
    if title:
        residual = _strip_dates_and_times(title)
        if not residual or re.fullmatch(r"[\d:\sAPMapm\.,\-]+", residual):
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
    elif time_24:
        res["time_str"] = time_24
    has_explicit_year = bool(re.search(r"\b20\d{2}\b", msg))
    if parsed_date and not has_explicit_year and parsed_date.year > date.today().year:
        res["roll_forward_note"] = f"(Note: {parsed_date.strftime('%B %-d')} has passed this year; scheduled for {parsed_date.year})"

    return res


def is_task_mutation_request(msg: str) -> bool:
    """Check if a prompt contains intent to add, create, or schedule a task or deadline."""
    return is_explicit_task_creation(msg)


def parse_natural_due_date(text: str) -> Tuple[Optional[str], str]:
    """Parse natural dates like '12th october', '12 oct', '2026-10-12', 'october 12th' from text."""
    pdate, _, _ = _parse_natural_date(text)
    return pdate.isoformat() if pdate else None, text


def message_needs_tools(message: str) -> bool:
    """Determine whether a user message requires tool registry evaluation.

    Classification Logic:
    1. Conversational Fast-Path: Simple chitchat, greetings, and general
       identity queries (e.g. 'hi', 'who are you', 'what can you help with') that contain
       no domain-specific verbs or entities bypass tool serialization.
    2. Comprehensive Domain Keywords: Scans for task, coursework, calendar, code,
       hackathon, search, memory, or feasibility triggers matching any of Compass's 23 tools.
    3. Fail-Safe Default: Any message containing actionable requests or domain entities
       triggers tool evaluation to ensure zero false negatives.
    """
    msg = message.lower().strip()
    if not msg:
        return False

    # Pure chitchat triggers with no actionable domain intent
    pure_conversational = {
        "hi", "hello", "hey", "greetings", "good morning", "good evening",
        "good afternoon", "how are you", "who are you", "what are you",
        "what can you do", "what do you do", "help", "thank you", "thanks",
        "bye", "goodbye", "tell me a joke", "what is compass", "who created you",
        "what can you help with", "what can you help me with", "how are you doing",
        "hey, what can you help with", "hey what can you help with",
    }
    cleaned = msg.strip("!?.,:; ")
    if cleaned in pure_conversational:
        return False

    tool_keywords = (
        # Tasks & Deliverables
        "task", "tasks", "todo", "todos", "due", "deadline", "deadlines",
        "backlog", "work on", "workload", "priority", "status", "pending", "upcoming",
        # Actions & Lifecycle
        "add", "create", "new", "schedule", "reschedule", "postpone", "delete",
        "remove", "edit", "update", "mark", "finish", "complete", "done", "cancel",
        "drop", "move", "push back", "assign", "defer",
        # Queries & Agenda
        "list", "show", "what are", "what do i have", "do i have", "what's on",
        "whats on", "check", "agenda", "today", "tomorrow", "yesterday", "this week", "next week",
        # Coursework & Academics
        "coursework", "course", "assignment", "homework", "syllabus", "notes",
        "lecture", "lab", "exam", "quiz", "test", "midterm", "final", "paper",
        "essay", "study", "reading",
        # Hackathons & Projects
        "hackathon", "project", "projects", "devpost", "submission", "track",
        "prize", "pitch", "demo",
        # Code & Repository
        "code", "repo", "repository", "snippet", "commit", "branch", "pr",
        "pull request", "architecture", "git", "github", "issue", "issues", "bug", "bugs",
        # Calendar & Availability
        "calendar", "event", "events", "meeting", "meetings", "sync",
        "availability", "available", "conflict", "conflicts", "clash", "free time", "busy", "slot", "slots",
        # Research & Web
        "search", "web", "lookup", "research", "verify", "tavily", "online",
        "url", "http", "https", "find", "documentation", "doc", "docs",
        # Feasibility & Triage
        "feasible", "feasibility", "finish in time", "can i finish", "what to drop",
        "what should i drop", "what i drop", "triage", "overload", "overloaded",
        "overcommit", "capacity",
        # Memory & Personal Profile Facts & Parked Thoughts
        "memory", "remember that", "remember my", "remember to", "recall", "stored", "save", "log", "note", "notes",
        "remind", "reminder", "call me", "my name is", "my name's", "prefer",
        "preference", "forget my", "forget that", "forget what i", "my goal",
        "park that", "park it", "park this", "come back to that", "parked shelf", "list parked",
        # Agent & Planner
        "planner", "agent", "plan", "execute",
    )
    return any(k in msg for k in tool_keywords)



def _fallback_route(message: str, history: Optional[list[dict[str, str]]] = None) -> Tuple[Optional[str], Optional[dict[str, Any]], str]:
    msg_lower = message.lower()

    # 1. Personal fact forget: strictly match personal-memory phrases, rejecting negations/idioms
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

    # 4. Park it shelf detection (strictly deferred thoughts/tangents, not car/nature park)
    if any(lp in msg_lower for lp in ("list parked", "show parked", "what is parked", "what's parked", "what did i park", "view parked", "parked shelf")):
        return "list_parked", {}, ""

    import re
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
                extracted = message[idx:].strip(" .!?")
                if extracted:
                    park_text = extracted
                    break
        if park_text.lower().strip(" .!?") in ("park that", "park it", "park this", "let's come back to that", "lets come back to that"):
            if history:
                for h in reversed(history):
                    if h.get("content"):
                        park_text = h.get("content")[:200]
                        break
        return "park_thought", {"text": park_text[:200]}, ""

    if any(term in msg_lower for term in ("feasibility", "can i finish", "what to drop", "what should i drop", "what i drop", "triage", "overloaded", "overcommit", "adversarial")):
        import re
        days_match = re.search(r"\b([0-9]{1,4})\s*days?\b", msg_lower)
        hours_match = re.search(r"\b([0-9]{1,4}(?:\.[0-9]{1,2})?)\s*hours?\b", msg_lower)
        f_days = int(days_match.group(1)) if days_match else 5
        f_hours = float(hours_match.group(1)) if hours_match else 4.0
        return "assess_feasibility", {"days": f_days, "hours_per_day": f_hours}, ""
    if is_undo_request(message):
        return "undo", {"message": message}, ""
    if is_explicit_task_creation(message):
        extracted = _extract_task_creation_args(message)
        if not extracted.get("title"):
            return None, None, "What would you like to name this task? Please provide a title or description."
        return "add_task", extracted, ""
    if history:
        for h in reversed(history):
            content = h.get("content", "")
            if any(term in content.lower() for term in ("task", "deliverable", "due", "demo", "submit", "video")):
                if any(term in msg_lower for term in ("due", "when", "deadline", "date")):
                    return "query_tasks", {}, f"Checking your task due dates based on previous context: {content}"
                return "query_tasks", {}, f"Referencing previous task: {content}"
    if any(term in msg_lower for term in ("task", "due", "deliverable", "deadline", "coursework", "hackathon")):
        return "query_tasks", {}, ""
    if any(term in msg_lower for term in ("help", "what can you", "who are you", "what is compass", "hello", "hi", "hey", "greetings")):
        return None, None, (
            "I am Compass, your AI copilot with long-term memory across hackathons, coursework, "
            "and code repositories. I can help you track tasks, manage deadlines, check schedule feasibility, "
            "search web documentation, and prevent calendar conflicts. How can I help you today?"
        )
    return None, None, "How can I help you today? I'm here to help you manage tasks, coursework, and deadlines."


async def route_message(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    memory_context: Optional[str] = None,
) -> Tuple[Optional[str], Optional[dict[str, Any]], str]:
    """Route a message through Nemotron-3 Nano using native tool calling.

    Returns:
        (skill_name, tool_arguments, text_response)
    """
    if is_undo_request(message):
        return "undo", {"message": message}, ""
    if is_explicit_task_creation(message):
        extracted = _extract_task_creation_args(message)
        if not extracted.get("title"):
            return None, None, "What would you like to name this task? Please provide a title or description."
        return "add_task", extracted, ""

    is_placeholder_key = (
        not settings.NEBIUS_API_KEY
        or settings.NEBIUS_API_KEY.startswith("your_nebius")
        or settings.NEBIUS_API_KEY in ("mock", "mock-key-not-used-in-tests")
    )
    if is_placeholder_key:
        return _fallback_route(message, history)

    client = get_openai_client()
    today_iso = date.today().isoformat()
    system_prompt = (
        f"You are Compass, an intelligent personal assistant with persistent memory across chat sessions. "
        f"Today's date is {today_iso}. When extracting dates without a specified year (e.g. '30th oct' or 'next week'), "
        f"always resolve them relative to today's date ({today_iso}) into the current or upcoming year ({today_iso[:4]}), NEVER a past year. "
        f"You maintain context across conversation history AND prior chats/plans. "
        f"When the user asks follow-up questions about recently created tasks, deadlines, or status, "
        f"either call query_tasks with the relevant domain/project or answer directly from conversation history. "
        f"When the user asks what they asked earlier, recalls past decisions, or asks to plan or schedule without clashing, "
        f"refer to the provided long-term workspace memory and active schedule. "
        f"CRITICAL: When the user requests adding, scheduling, or tracking a task, action item, or deadline, "
        f"you MUST call the add_task tool with properly extracted fields. "
        f"When the user asks whether their open workload is achievable or feasible, what to prioritise, "
        f"what to drop, whether they can finish in time, feels overloaded, or asks for a feasibility review / workload triage, "
        f"call the assess_feasibility tool with extracted days and hours_per_day. "
        f"For general inquiries or conversation, respond directly with helpful text."
    )
    if memory_context:
        system_prompt += f"\n\n[WORKSPACE MEMORY & PAST SESSIONS - USE TO PREVENT SCHEDULE CLASHES & RECALL PAST CONTEXT]:\n{memory_context}"

    messages: Any = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": message})
    needs_tools = message_needs_tools(message)
    tools: Any = TOOLS if needs_tools else None

    try:
        call_kwargs: dict[str, Any] = {
            "model": settings.ROUTER_MODEL,
            "messages": messages,
            "max_tokens": 1024,
            "stream": False,
        }
        if tools:
            call_kwargs["tools"] = tools
            call_kwargs["tool_choice"] = "auto"

        response: Any = await client.chat.completions.create(**call_kwargs)

        from backend.services.usage import record_usage
        usage = getattr(response, "usage", None)
        p_tok = usage.prompt_tokens if usage else max(len(message.split()) * 2, 64)
        c_tok = usage.completion_tokens if usage else 50
        record_usage(settings.ROUTER_MODEL, p_tok, c_tok)

        choice = response.choices[0]
        msg_lower = message.lower()
        is_explicit_add_task = is_explicit_task_creation(message)

        if choice.message.tool_calls:
            tc: Any = choice.message.tool_calls[0]
            func_name = getattr(getattr(tc, "function", None), "name", None) or getattr(tc, "name", "add_task")
            raw_args = getattr(getattr(tc, "function", None), "arguments", "{}") or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception as e:
                logger.warning(f"Failed to parse function arguments JSON ({e}): {raw_args}")
                args = {"title": message}

            # Guard against model misrouting an explicit task creation command to query_tasks or another tool
            if is_explicit_add_task and func_name != "add_task":
                fallback_args = _extract_task_creation_args(message)
                if not fallback_args.get("title"):
                    return None, None, "What would you like to name this task? Please provide a title or description."
                func_name = "add_task"
                args = {**fallback_args, **{k: v for k, v in args.items() if k in ("domain", "due_date", "priority") and v}}

            if func_name == "add_task":
                extracted = _extract_task_creation_args(message)
                if not args.get("title") and extracted.get("title"):
                    args["title"] = extracted["title"]
                if not args.get("due_date") and extracted.get("due_date"):
                    args["due_date"] = extracted["due_date"]
                if extracted.get("time_str"):
                    args["time_str"] = extracted["time_str"]
                if not args.get("title"):
                    return None, None, "What would you like to name this task? Please provide a title or description."

            logger.info(f"Router invoked tool: {func_name} with args: {args}")
            return func_name, args, ""
        else:
            # Fallback if model responded with conversational text to an explicit task creation command
            if is_explicit_add_task:
                extracted = _extract_task_creation_args(message)
                if not extracted.get("title"):
                    return None, None, "What would you like to name this task? Please provide a title or description."
                return "add_task", extracted, ""

            reply = choice.message.content or "How can I help you today?"
            return None, None, reply

    except Exception as e:
        logger.error(f"Nebius router invocation failed: {e}")
        return _fallback_route(message, history)
