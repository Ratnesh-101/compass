"""
Compass Agent — Types, Constants, and Helper Functions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("compass.agent_types")

# Tools that mutate state require human confirmation before execution
MUTATING_TOOLS = frozenset({
    "add_task",
    "edit_task",
    "update_task_status",
    "delete_task",
    "log_code_snippet",
    "log_code_context",
    "ingest_url",
    "apply_triage_plan",
    "commit_schedule",
})

READ_ONLY_TOOLS = frozenset({
    "query_tasks",
    "query_code_context",
    "query_coursework_tasks",
    "get_hackathon_deadlines",
    "summarize_day",
    "search_web",
    "list_projects",
    "query_coursework_notes",
    "chat",
    "summarize_across_domains",
    "verify_deadline",
    "assess_feasibility",
    "detect_deadline_conflicts",
    "get_calendar_availability",
    "propose_schedule",
    "detect_schedule_conflicts",
    "delegate_to_specialist",
})

# In-memory registry for live SSE confirmation events: run_id -> (asyncio.Event, outcome_dict)
_PENDING_CONFIRMATION_EVENTS: Dict[str, Tuple[asyncio.Event, Dict[str, Any]]] = {}


@dataclass
class AgentStep:
    """One step in the agent's reasoning trace."""
    type: str  # "think" | "tool_call" | "observe" | "confirm_request" | "confirm_ack" | "critic" | "synthesize" | "error" | "done" | "timeout" | "escalate"
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    step_number: int = 0
    elapsed_ms: int = 0
    run_id: Optional[str] = None
    model_tier: Optional[str] = None
    step_cost_usd: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_sse(self) -> str:
        """Serialize to SSE data line."""
        payload: Dict[str, Any] = {
            "type": self.type,
            "content": self.content,
            "step": self.step_number,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.tool_name:
            payload["tool"] = self.tool_name
        if self.tool_args:
            payload["args"] = self.tool_args
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.model_tier:
            payload["model_tier"] = self.model_tier
        if self.step_cost_usd is not None:
            payload["step_cost_usd"] = self.step_cost_usd
        if self.metadata:
            payload["metadata"] = self.metadata
        return f"data: {json.dumps(payload)}\n\n"


def _clean_synthesis_text(text: str) -> str:
    """Filter out raw LLM/search citation markers (e.g. 【{"id":0,...}】 or 【...】)."""
    if not text:
        return ""
    cleaned = re.sub(r'[\u3010][^\u3011]*[\u3011]', '', text)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r' +([.,;:!?])', r'\1', cleaned)
    return cleaned.strip()


async def _extract_content_from_response(response: Any, default_text: str = "") -> str:
    """Safely extract text content from either a ChatCompletion or an AsyncStream."""
    if hasattr(response, "choices") and response.choices:
        msg = getattr(response.choices[0], "message", None)
        if msg and getattr(msg, "content", None):
            return msg.content
        return default_text
    elif hasattr(response, "__aiter__"):
        content_parts = []
        async for chunk in response:
            ch_choices = getattr(chunk, "choices", None) or []
            if ch_choices:
                delta = getattr(ch_choices[0], "delta", None)
                if delta and getattr(delta, "content", None):
                    content_parts.append(delta.content)
        return "".join(content_parts) or default_text
    return default_text


def _build_agent_system_prompt(tool_names: List[str], abstain_first: bool = False) -> str:
    """Build the system prompt that makes Super behave as a ReAct agent."""
    tool_list = ", ".join(tool_names)
    prompt = (
        "You are Compass Agent, an autonomous planning and scheduling assistant. "
        "You help users manage tasks, deadlines, and code context across hackathon, coursework, and code domains.\n\n"
        "You have access to these tools: " + tool_list + ".\n\n"
        "### Operational Instructions:\n"
        "1. For each step, decide whether to call a tool or produce a final answer.\n"
        "2. If calling a tool, specify the tool name and valid arguments.\n"
        "3. After observing tool results, either call another tool or synthesize your final response.\n"
        "4. Always explain your reasoning before calling tools.\n"
        "5. State-mutating tools (add_task, edit_task, update_task_status, delete_task, log_code_snippet, log_code_context, ingest_url, apply_triage_plan, commit_schedule) "
        "will request user confirmation before modifying data. Plan cleanly.\n"
        "6. Focus on grounded facts from stored memory and tools.\n"
    )
    if abstain_first:
        prompt += (
            "\n### Epistemic Abstention Policy (Active):\n"
            "- When asked a question, check internal memory tools first.\n"
            "- If memory does NOT contain the necessary information, reply with '[ABSTAIN]' rather than guessing.\n"
            "- When web search is available, you may use it to find missing facts.\n"
        )
    return prompt
