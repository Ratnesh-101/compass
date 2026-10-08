"""
Compass — LLM Router using Nemotron-3 Nano.

Dispatches user messages to skills via native OpenAI function calling.
Probed and verified on Nebius Token Factory with nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B.
"""

import json
import logging
from datetime import date
from typing import Any, Optional, Tuple
from openai import AsyncOpenAI
from backend.config import get_settings
from backend.skills import TOOL_DEFINITIONS
from backend.router_helpers import (
    MONTH_MAP,
    MONTHS_MAP,
    DAYS_OF_WEEK,
    parse_natural_due_date,
    is_task_mutation_request,
    is_explicit_task_creation,
    is_undo_request,
    _parse_time,
    _parse_natural_date,
    _extract_task_creation_args,
    message_needs_tools,
    _fallback_route,
)

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
        is_explicit_add_task = is_task_mutation_request(message) or is_explicit_task_creation(message)

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
        if is_task_mutation_request(message) or is_explicit_task_creation(message):
            return "add_task", _extract_task_creation_args(message), ""
        return _fallback_route(message, history)
