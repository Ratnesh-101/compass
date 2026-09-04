"""
Compass — LLM Router using Nemotron-3 Nano.

Dispatches user messages to skills via native OpenAI function calling.
Probed and verified on Nebius Token Factory with nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B.
"""

import json
import logging
from typing import Any, Optional, Dict, Tuple
from openai import OpenAI
from backend.config import get_settings

logger = logging.getLogger("compass.router")
settings = get_settings()

ADD_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_task",
        "description": "Add a new task or action item to the user's structured task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title or action item description of the task",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Domain category",
                },
                "project": {
                    "type": "string",
                    "description": "Optional name of the project this task belongs to",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format (if specified or inferred)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Priority level of the task",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional context or details for the task",
                },
            },
            "required": ["title"],
        },
    },
}

from backend.skills import TOOL_DEFINITIONS

TOOLS = TOOL_DEFINITIONS


def get_openai_client() -> OpenAI:
    """Return configured OpenAI client for Nebius Token Factory."""
    return OpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
    )


async def route_message(
    message: str,
    history: Optional[list[dict[str, str]]] = None,
) -> Tuple[Optional[str], Optional[dict[str, Any]], str]:
    """Route a message through Nemotron-3 Nano using native tool calling.

    Returns:
        (skill_name, tool_arguments, text_response)
        - If a tool was chosen: ('add_task', {'title': ...}, '')
        - If regular chat: (None, None, 'Assistant text response')
    """
    client = get_openai_client()
    messages: Any = [
        {
            "role": "system",
            "content": (
                "You are Compass, an intelligent personal assistant. "
                "When the user requests adding, scheduling, or tracking a task, action item, or deadline, "
                "call the add_task tool with properly extracted fields. "
                "For general inquiries or conversation, respond directly with helpful text."
            ),
        }
    ]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": message})
    tools: Any = TOOLS

    try:
        response = client.chat.completions.create(
            model=settings.ROUTER_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=256,
        )

        choice = response.choices[0]
        if choice.message.tool_calls:
            tc: Any = choice.message.tool_calls[0]
            func_name = getattr(getattr(tc, "function", None), "name", None) or getattr(tc, "name", "add_task")
            raw_args = getattr(getattr(tc, "function", None), "arguments", "{}") or "{}"

            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except Exception as e:
                logger.warning(f"Failed to parse function arguments JSON ({e}): {raw_args}")
                args = {"title": message}

            logger.info(f"Router invoked tool: {func_name} with args: {args}")
            return func_name, args, ""
        else:
            reply = choice.message.content or "How can I help you today?"
            return None, None, reply

    except Exception as e:
        logger.error(f"Nebius router invocation failed: {e}")
        # Fallback keyword routing for robustness
        msg_lower = message.lower()
        if "add task" in msg_lower or "add a task" in msg_lower or "new task" in msg_lower:
            return "add_task", {"title": message.replace("add a task:", "").replace("add task:", "").strip()}, ""
        return None, None, f"I encountered an error routing your request: {e}"
