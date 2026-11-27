"""Schema-validated extraction of several tasks from free-form prose ("add tasks: finish the lab
report by Friday, call mom tomorrow and buy milk").

Same technique as the `instructor` library (forced tool call, Pydantic validation, one retry with the
validation error), implemented directly so the pinned `openai` version is untouched. One bounded
call; the result is only ever shown as a preview, nothing is written here. Due text must be a
verbatim quote of the user's message, so the model cannot invent a deadline.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from backend.services.task_context import enrich_title, infer_domain
from backend.services.task_intake_parse import (
    MAX_ITEMS,
    _DATE_WORDS,
    IntakeItem,
    _extract_embedded_time,
    _extract_parenthesised_meta,
    parse_single_task,
)
from backend.services.task_intent import is_question_framed, mentions_task_creation, title_problem

logger = logging.getLogger("compass.services.task_intake_llm")

EXTRACTION_MAX_TOKENS = 1500  # fixed: never capped by the tone/style settings
LLM_EXTRACT_TIMEOUT_SECONDS = 12.0  # hard budget for any model call on the add-task preview path
MAX_PROSE_CHARS = 4000
_PLURAL_TASK_NOUN = re.compile(r"\b(?:tasks|deadlines|reminders|todos|to-dos)\b", re.IGNORECASE)
_ITEM_SEPARATOR = re.compile(r"[,;\n]|\band\b", re.IGNORECASE)
_TOOL_NAME = "extract_tasks"
_PLACEHOLDER_KEY_PREFIXES = ("your_nebius", "mock")


class TaskDraft(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="Short task name taken from the message")
    domain: Literal["hackathon", "coursework", "code", "general"] = "general"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    duration_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    due_text: str = Field(default="", max_length=80, description="The user's own words for the due date/time, verbatim; empty if none was stated")


class TaskDraftList(BaseModel):
    tasks: List[TaskDraft] = Field(max_length=MAX_ITEMS)


SYSTEM_PROMPT = (
    "Extract the tasks the user explicitly asks to add. Never invent tasks, dates or details. "
    "Copy due_text verbatim from the message (empty string if the user gave no date or time). "
    "Use priority 'medium' unless the message says otherwise. "
    "When a task specifies a domain or category (such as in parentheses like '(general)' or '(coursework)'), "
    "assign that domain strictly to that task and strip the category label from the title. "
    "Never leak one item's domain to another item. "
    "Keep the user's context in each title: when the message says what the tasks are for "
    "(for example 'for my data structures exam'), name them like 'Study arrays - Data Structures exam', "
    "not just 'arrays'. Use domain 'coursework' for studying, exams, classes and assignments, "
    "'hackathon' for hackathon work, 'code' for programming and repositories, otherwise 'general'."
)


def looks_like_prose_task_list(message: str) -> bool:
    """Cheap gate: an add-several-tasks request in prose (no table), so the model call is worth making."""
    text = (message or "").strip()
    if not text or len(text) > MAX_PROSE_CHARS or is_question_framed(text):
        return False
    return (
        mentions_task_creation(text)
        and bool(_PLURAL_TASK_NOUN.search(text))
        and len(_ITEM_SEPARATOR.findall(text)) >= 2
    )


def llm_available(api_key: Optional[str]) -> bool:
    key = (api_key or "").strip()
    return bool(key) and not key.startswith(_PLACEHOLDER_KEY_PREFIXES)


def _to_items(drafts: List[TaskDraft], message: str) -> List[IntakeItem]:
    lowered = message.lower()
    items: List[IntakeItem] = []
    for d in drafts[:MAX_ITEMS]:
        raw_title = re.sub(r"\s+", " ", d.title).strip()
        title, paren_domain, paren_priority = _extract_parenthesised_meta(raw_title)
        if title_problem(title):
            continue
        due_text = d.due_text.strip()
        if due_text and due_text.lower() not in lowered:
            due_text = ""  # not a quote of the user's words: drop it rather than trust it

        # Check embedded time in due_text first, then raw_title
        notes = None
        t24, t12, leader, _ = _extract_embedded_time(due_text) if due_text else (None, None, None, None)
        if t24 and t12:
            notes = f"by {t12}"
            # Keep original label format; never reformat existing due_text
        else:
            t24_t, t12_t, leader_t, raw_match_t = _extract_embedded_time(raw_title)
            if t24_t and t12_t:
                notes = f"by {t12_t}"
                if due_text:
                    due_text = f"{due_text}, {t12_t}"
                else:
                    if leader_t in _DATE_WORDS:
                        norm_lead = "tomorrow" if leader_t == "tmrw" else leader_t
                        due_text = f"{norm_lead} {t12_t}"
                    else:
                        due_text = f"{t12_t}"
                if raw_match_t and raw_match_t in title:
                    title = title.replace(raw_match_t, "").strip(" -–—@,:()")
                    title = re.sub(r"\s+", " ", title).strip()

        # Honour parenthesised category per item and keep categories strictly separate
        if paren_domain:
            domain = paren_domain
        elif "domain" in d.model_fields_set and (d.domain != "general" or "general" in lowered):
            domain = d.domain
        else:
            domain = infer_domain(d.domain, message)
        priority = paren_priority or d.priority

        title = enrich_title(title, message)
        items.append(IntakeItem(title, domain, priority, d.duration_minutes, due_text, notes=notes))
    return items


async def _extract_prose_tasks_call(client: Any, model: str, message: str) -> List[IntakeItem]:
    """Validated task drafts from prose; [] when the model returns nothing usable."""
    messages: List[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    tool = {
        "type": "function",
        "function": {"name": _TOOL_NAME, "description": "Record the tasks the user asked to add.",
                     "parameters": TaskDraftList.model_json_schema()},
    }
    for attempt in (1, 2):
        response = await client.chat.completions.create(
            model=model, messages=messages, tools=[tool], temperature=0, stream=False,
            tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
            max_tokens=EXTRACTION_MAX_TOKENS,
        )
        try:
            call = response.choices[0].message.tool_calls[0]
            parsed = TaskDraftList.model_validate_json(call.function.arguments)
            return _to_items(parsed.tasks, message)
        except (ValidationError, AttributeError, IndexError, TypeError, ValueError) as e:
            logger.warning("Task extraction attempt %d returned invalid output: %s", attempt, type(e).__name__)
            if attempt == 2:
                return []
            messages.append({"role": "user", "content": f"That output was invalid ({str(e)[:300]}). Call {_TOOL_NAME} again with valid arguments."})
    return []


def deterministic_items(message: str) -> List[IntakeItem]:
    """No-model fallback: one item per separated clause, each read by the deterministic single-task parser."""
    items: List[IntakeItem] = []
    text = message or ""
    head, sep, tail = text.partition(":")
    if sep and len(head) <= 40 and mentions_task_creation(head):
        text = tail
    plural = bool(_PLURAL_TASK_NOUN.search(message or "")) and not is_question_framed(message or "")
    clauses = [c.strip() for c in _ITEM_SEPARATOR.split(text)] if plural else [text]
    for clause in clauses[:MAX_ITEMS]:
        parsed = parse_single_task(clause)
        if parsed:
            items.extend(parsed.items)
    return items


async def llm_extract_items(message: str) -> List[IntakeItem]:
    """One model extraction call for a task message (patched in tests; always run through extract_items_bounded)."""
    from backend.config import get_settings
    from backend.router import get_openai_client

    settings = get_settings()
    if not llm_available(settings.NEBIUS_API_KEY):
        return []
    return await _extract_prose_tasks_call(get_openai_client(), settings.ROUTER_MODEL, message)


async def extract_items_bounded(message: str) -> List[IntakeItem]:
    """Model extraction under LLM_EXTRACT_TIMEOUT_SECONDS; on timeout, error or empty result use the deterministic parser."""
    try:
        items = await asyncio.wait_for(llm_extract_items(message), timeout=LLM_EXTRACT_TIMEOUT_SECONDS)
        if items:
            return list(items)
        logger.warning("Task extraction returned nothing; using deterministic parser")
    except asyncio.TimeoutError:
        logger.warning("Task extraction timed out after %.1fs; using deterministic parser", LLM_EXTRACT_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning("Task extraction failed (%s); using deterministic parser", type(e).__name__)
    return deterministic_items(message)


async def extract_prose_tasks(client: Any, model: str, message: str) -> List[IntakeItem]:
    """Bounded prose extraction for the router: a timeout or error returns the deterministic items, never hangs."""
    try:
        return await asyncio.wait_for(_extract_prose_tasks_call(client, model, message), timeout=LLM_EXTRACT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("Prose task extraction timed out after %.1fs; using deterministic parser", LLM_EXTRACT_TIMEOUT_SECONDS)
    except Exception as e:
        logger.warning("Prose task extraction failed (%s); using deterministic parser", type(e).__name__)
    return deterministic_items(message)
