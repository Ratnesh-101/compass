"""
Compass Agent — Abstention Detection and Web Escalation Logic.

Monitors model reasoning and text replies to detect when stored memory is insufficient,
and triggers disciplined escalation to live web search rather than hallucinating answers.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.agent_types import AgentStep

logger = logging.getLogger("compass.agent.escalation")

_MEMORY_TOOLS = frozenset({
    "query_tasks",
    "query_code_context",
    "query_coursework_notes",
    "query_coursework_tasks",
    "get_hackathon_deadlines",
    "summarize_day",
    "summarize_across_domains",
    "list_projects",
    "detect_deadline_conflicts",
    "delegate_to_specialist",
})

_IMPLICIT_SIGNALS = (
    "don't have",
    "do not have",
    "cannot find",
    "no information",
    "not found",
    "not stored",
    "insufficient",
    "no record",
    "unable to find",
    "no data",
    "haven't found",
    "have not found",
)


def evaluate_abstention_and_web_escalation(
    reply: str,
    tools_used: List[str],
    abstain_first: bool,
    web_escalation_used: bool,
    run_id: str,
    step_start: float,
    step_num: int,
    messages: List[Dict[str, Any]],
) -> Tuple[bool, bool, Optional[AgentStep], int]:
    """Evaluate whether the agent reply signals an abstention and should escalate to Tavily search.

    Returns:
        (should_continue_loop, is_abstained, escalation_step, updated_step_num)
    """
    _memory_tools_called = bool(set(tools_used) & _MEMORY_TOOLS)
    reply_lower = reply.lower()

    _is_implicit = (
        abstain_first
        and not web_escalation_used
        and not _memory_tools_called
        and "search_web" not in tools_used
        and any(sig in reply_lower for sig in _IMPLICIT_SIGNALS)
    )
    _is_explicit = (
        any(k in reply.upper() for k in ("[ABSTAIN]", "[ABSTENTION]", "ABSTAIN:"))
        or reply.strip().startswith("[ABSTAIN]")
    )

    if not (_is_explicit or _is_implicit):
        return False, False, None, step_num

    if not web_escalation_used:
        try:
            from backend.services.tavily import tavily_available
            tavily_ok = tavily_available()
        except Exception:
            tavily_ok = False

        if tavily_ok:
            step_num += 1
            escalate_step = AgentStep(
                type="escalate",
                content="Memory doesn't cover this. Escalating to live web search rather than guessing.",
                step_number=step_num,
                elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                run_id=run_id,
                model_tier="Tavily Web Intelligence",
                step_cost_usd=0.0,
                metadata={"reason": "abstention", "provider": "tavily"},
            )

            messages.append({"role": "assistant", "content": reply})
            messages.append({
                "role": "user",
                "content": (
                    "Stored memory does not cover this question. Please call the 'search_web' tool "
                    "now to retrieve current information from the live web to answer the goal."
                ),
            })
            return True, False, escalate_step, step_num
        else:
            return False, True, None, step_num
    else:
        return False, True, None, step_num
