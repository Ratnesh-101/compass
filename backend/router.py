"""
Compass — LLM Router using Nemotron-3 Nano.

Dispatches user messages to skills via native OpenAI function calling.
Probed and verified on Nebius Token Factory with nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B.
"""

import json
import logging
from datetime import date
from typing import Any, Optional, Dict, Tuple
from openai import OpenAI, AsyncOpenAI
from backend.config import get_settings
from backend.skills import TOOL_DEFINITIONS

logger = logging.getLogger("compass.router")
settings = get_settings()

TOOLS = TOOL_DEFINITIONS


def get_openai_client() -> AsyncOpenAI:
    """Return configured AsyncOpenAI client for Nebius Token Factory."""
    return AsyncOpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
        timeout=15.0,
    )


MONTHS_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "sept": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_natural_due_date(text: str) -> Tuple[Optional[str], str]:
    """Parse natural dates like '12th october', '12 oct', '2026-10-12', 'october 12th' from text.
    Returns (iso_date_string, cleaned_text).
    """
    import re
    from datetime import date, timedelta

    text_lower = text.lower()
    today = date.today()

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
    msg_l = (msg or "").lower()
    mutation_keywords = (
        "add a task", "add task", "new task", "create task",
        "add a deadline", "add deadline", "set deadline", "set a deadline",
        "add deliverable", "create deliverable", "schedule deadline", "new deadline",
        "add a due date", "set due date", "add due date"
    )
    return any(k in msg_l for k in mutation_keywords)


def _extract_task_creation_args(message: str) -> dict:
    """Extract title, domain, due_date, and priority from any task/deadline creation prompt."""
    import re

    msg_clean = message
    # Strip leading specialist tags like [research], [coursework], etc.
    msg_clean = re.sub(r"^\s*\[(research|coursework|calendar|memory|general)\]\s*", "", msg_clean, flags=re.IGNORECASE)
    msg_clean = re.sub(r"^\s*/(research|coursework|calendar|memory|general)\s*", "", msg_clean, flags=re.IGNORECASE)

    msg_lower = msg_clean.lower()

    # Domain inference
    domain = "general"
    if any(k in msg_lower for k in ("hackathon", "nvidia", "nvdia", "devpost", "nebius")):
        domain = "hackathon"
    elif any(k in msg_lower for k in ("cs 61c", "cs61c", "coursework", "lab", "homework", "hw", "exam", "midterm")):
        domain = "coursework"
    elif any(k in msg_lower for k in ("code", "bug", "pyright", "refactor", "repo", "git", "api")):
        domain = "code"

    # Due date parsing
    due_date, text_without_date = parse_natural_due_date(msg_clean)

    # Priority inference
    priority = "medium"
    if any(k in msg_lower for k in ("critical", "p0", "urgent", "high", "asap", "hackathon", "deadline")):
        priority = "urgent" if any(k in msg_lower for k in ("critical", "urgent", "p0", "hackathon", "deadline")) else "high"

    # Title extraction
    title = text_without_date
    for prefix in (
        "add a deadline of", "add a deadline for", "add deadline of", "add deadline for",
        "add a deadline:", "add deadline:", "add a deadline", "add deadline",
        "set deadline of", "set deadline for", "set deadline:", "set deadline",
        "add a deliverable:", "add deliverable:", "add deliverable",
        "add a task:", "add task:", "add a task", "add task", "create task:", "create task"
    ):
        if prefix in msg_lower:
            idx = msg_lower.find(prefix) + len(prefix)
            title = text_without_date[idx:].strip(" :,-;")
            break

    # Clean title prefixes
    title = re.sub(r"^\s*(of|for|to|with)\s+", "", title, flags=re.IGNORECASE).strip(" :,-;")
    if not title or len(title) < 2:
        title = msg_clean

    if title:
        title = title[0].upper() + title[1:]

    res: dict[str, Any] = {
        "title": title,
        "domain": domain,
        "priority": priority,
        "status": "open",
    }
    if due_date:
        res["due_date"] = due_date
    return res


async def route_message(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    memory_context: Optional[str] = None,
) -> Tuple[Optional[str], Optional[dict[str, Any]], str]:
    """Route a message through Nemotron-3 Nano using native tool calling.

    Returns:
        (skill_name, tool_arguments, text_response)
        - If a tool was chosen: ('add_task', {'title': ...}, '')
        - If regular chat: (None, None, 'Assistant text response')
    """
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
    tools: Any = TOOLS

    try:
        response: Any = await client.chat.completions.create(
            model=settings.ROUTER_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=1024,
            stream=False,
        )

        from backend.services.usage import record_usage
        usage = getattr(response, "usage", None)
        p_tok = usage.prompt_tokens if usage else max(len(message.split()) * 2, 64)
        c_tok = usage.completion_tokens if usage else 50
        record_usage(settings.ROUTER_MODEL, p_tok, c_tok)

        choice = response.choices[0]
        msg_lower = message.lower()
        is_explicit_add_task = is_task_mutation_request(message)

        if choice.message.tool_calls:
            tc: Any = choice.message.tool_calls[0]
            func_name = getattr(getattr(tc, "function", None), "name", None) or getattr(tc, "name", "add_task")
            raw_args = getattr(getattr(tc, "function", None), "arguments", "{}") or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception as e:
                logger.warning(f"Failed to parse function arguments JSON ({e}): {raw_args}")
                args = {"title": message}

            # Guard against model misrouting an explicit task creation command to query_tasks
            if func_name == "query_tasks" and is_explicit_add_task:
                fallback_args = _extract_task_creation_args(message)
                func_name = "add_task"
                args = {**fallback_args, **{k: v for k, v in args.items() if k in ("domain", "due_date", "priority")}}

            logger.info(f"Router invoked tool: {func_name} with args: {args}")
            return func_name, args, ""
        else:
            # Fallback if model responded with conversational text to an explicit task creation command
            if is_explicit_add_task:
                return "add_task", _extract_task_creation_args(message), ""

            reply = choice.message.content or "How can I help you today?"
            return None, None, reply

    except Exception as e:
        logger.error(f"Nebius router invocation failed: {e}")
        # Fallback keyword routing for robustness
        msg_lower = message.lower()
        if any(term in msg_lower for term in ("feasibility", "can i finish", "what to drop", "what should i drop", "what i drop", "triage", "overloaded", "overcommit", "adversarial")):
            import re
            days_match = re.search(r"\b([0-9]{1,4})\s*days?\b", msg_lower)
            hours_match = re.search(r"\b([0-9]{1,4}(?:\.[0-9]{1,2})?)\s*hours?\b", msg_lower)
            f_days = int(days_match.group(1)) if days_match else 5
            f_hours = float(hours_match.group(1)) if hours_match else 4.0
            return "assess_feasibility", {"days": f_days, "hours_per_day": f_hours}, ""
        if is_task_mutation_request(message):
            return "add_task", _extract_task_creation_args(message), ""
        if history:
            for h in reversed(history):
                content = h.get("content", "")
                if any(term in content.lower() for term in ("task", "deliverable", "due", "demo", "submit", "video")):
                    if any(term in msg_lower for term in ("due", "when", "deadline", "date")):
                        return "query_tasks", {}, f"Checking your task due dates based on previous context: {content}"
                    return "query_tasks", {}, f"Referencing previous task: {content}"
        if any(term in msg_lower for term in ("task", "due", "deliverable", "deadline")):
            return "query_tasks", {}, ""
        return None, None, "I'm having a moment — could you try that again? I'm here to help!"
