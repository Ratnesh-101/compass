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


def _extract_task_creation_args(message: str) -> dict:
    """Extract title, domain, and due_date from an explicit task creation prompt."""
    msg_lower = message.lower()
    title = message
    domain = "general"
    due_date = None
    for prefix in ("add a task:", "add task:", "add a task", "add task", "create task:"):
        if prefix in msg_lower:
            idx = msg_lower.find(prefix) + len(prefix)
            title = message[idx:].strip()
            break

    # Extract due date if present (e.g. "due 2026-10-31" or "due: 2026-10-31")
    if "due" in title.lower():
        parts = title.split()
        new_parts = []
        skip_next = False
        for idx, part in enumerate(parts):
            if skip_next:
                skip_next = False
                continue
            part_clean = part.lower().strip(",;:")
            if part_clean.startswith("due=") or part_clean.startswith("due:"):
                val = part.split("=", 1)[-1].split(":", 1)[-1].strip(",; ")
                if val:
                    due_date = val
            elif part_clean == "due" and idx + 1 < len(parts):
                due_date = parts[idx + 1].strip(",;:= ")
                skip_next = True
            else:
                new_parts.append(part)
        title = " ".join(new_parts).strip(" ,;")

    if "domain" in title.lower():
        parts = title.split()
        new_parts = []
        skip_next = False
        for idx, part in enumerate(parts):
            if skip_next:
                skip_next = False
                continue
            part_clean = part.lower().strip(",;:")
            if part_clean.startswith("domain=") or part_clean.startswith("domain:"):
                val = part.split("=", 1)[-1].split(":", 1)[-1].strip(",; ")
                if val:
                    domain = val.lower()
            elif part_clean == "domain" and idx + 1 < len(parts):
                val = parts[idx + 1].strip(",;:= ")
                if val:
                    domain = val.lower()
                    skip_next = True
            else:
                new_parts.append(part)
        title = " ".join(new_parts).strip(" ,;")

    res: dict[str, Any] = {"title": title, "domain": domain}
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
        is_explicit_add_task = any(term in msg_lower for term in ("add a task", "add task", "new task", "create task"))

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
        if "add task" in msg_lower or "add a task" in msg_lower or "new task" in msg_lower:
            return "add_task", {"title": message.replace("add a task:", "").replace("add task:", "").strip()}, ""
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
