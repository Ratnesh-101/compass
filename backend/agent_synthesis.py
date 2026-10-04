"""
Compass Agent — Synthesis and Final Report Card Builder.
Handles forced final synthesis with Nemotron-3 Ultra (550B) and comprehensive report card generation.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, cast

from openai import AsyncOpenAI

from backend.agent_types import AgentStep, _clean_synthesis_text, _extract_content_from_response
from backend.services.usage import compute_step_cost, record_usage

logger = logging.getLogger("compass.agent_synthesis")


async def force_final_synthesis(
    client: AsyncOpenAI,
    settings: Any,
    messages: List[Dict[str, Any]],
    step_num: int,
    start_time: float,
    run_id: str,
    active_replan_diff: Optional[Dict[str, Any]],
) -> Tuple[AgentStep, float, bool]:
    """Force final synthesis with Nemotron-3 Ultra (550B) when hitting max_steps."""
    messages.append({
        "role": "user",
        "content": (
            "You've gathered enough information. Please produce your final comprehensive answer now. "
            "Never emit literal bracketed placeholders such as '[time]' or '[date]' if an exact value was not shown in the source text; "
            "explicitly state 'time not shown in the retrieved excerpt' instead."
        ),
    })
    completions = client.chat.completions
    response = await completions.create(
        model=str(settings.SYNTHESIS_MODEL),
        messages=cast(Any, messages),
        max_tokens=1024,
        temperature=0.5,
        stream=False,
    )
    usage = getattr(response, "usage", None)
    p_tok = usage.prompt_tokens if usage else 500
    c_tok = usage.completion_tokens if usage else 200
    record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok)
    forced_cost = compute_step_cost(settings.SYNTHESIS_MODEL, p_tok, c_tok)

    raw_text = await _extract_content_from_response(response, default_text="Agent completed analysis.")
    is_abstained = any(k in raw_text.upper() for k in ("[ABSTAIN]", "[ABSTENTION]", "ABSTAIN:")) or raw_text.strip().startswith("[ABSTAIN]")
    final_text = _clean_synthesis_text(raw_text)

    forced_synth = AgentStep(
        type="synthesize",
        content=final_text,
        step_number=step_num,
        elapsed_ms=int((time.perf_counter() - start_time) * 1000),
        run_id=run_id,
        model_tier="Nemotron-3 Ultra (550B)",
        step_cost_usd=forced_cost,
        metadata={
            "abstained": is_abstained,
            "replan_diff": active_replan_diff,
        },
    )
    return forced_synth, forced_cost, is_abstained


def build_done_step(
    run_id: str,
    step_num: int,
    start_time: float,
    tools_used: List[str],
    critique_rounds: int,
    total_run_cost_usd: float,
    is_abstained: bool,
    web_escalation_used: bool,
    abstain_first: bool,
    active_replan_diff: Optional[Dict[str, Any]],
    pending_confirmations: List[Dict[str, Any]],
    accumulated_steps: List[AgentStep],
) -> AgentStep:
    """Build the final DONE step containing full metrics report card."""
    total_elapsed = int((time.perf_counter() - start_time) * 1000)
    tier_breakdown = {
        "Nemotron-3 Super (120B)": sum(s.step_cost_usd or 0.0 for s in accumulated_steps if s.model_tier and "Super" in s.model_tier),
        "Nemotron-3 Ultra (550B)": sum(s.step_cost_usd or 0.0 for s in accumulated_steps if s.model_tier and "Ultra" in s.model_tier),
        "Neon Postgres Engine": 0.0,
    }
    if is_abstained:
        run_source = "abstained"
    elif any(t in tools_used for t in ("search_web", "ingest_url", "verify_deadline")) or web_escalation_used:
        run_source = "web"
    else:
        run_source = "memory"

    report_card = {
        "run_id": run_id,
        "status": "completed",
        "total_steps": step_num,
        "elapsed_ms": total_elapsed,
        "tools_used": list(set(tools_used)),
        "critique_rounds": critique_rounds,
        "total_cost_usd": round(total_run_cost_usd, 6),
        "abstained": is_abstained,
        "source": run_source,
        "sources": [run_source],
        "web_escalation_used": web_escalation_used,
        "tavily_abstain_first": abstain_first,
        "replan_diff": active_replan_diff,
        "tier_breakdown": {k: round(v, 6) for k, v in tier_breakdown.items()},
    }
    done_payload = {
        "run_id": run_id,
        "total_steps": step_num,
        "tools_used": list(set(tools_used)),
        "pending_confirmations": pending_confirmations,
        "report_card": report_card,
    }
    return AgentStep(
        type="done",
        content=json.dumps(done_payload),
        step_number=step_num + 1,
        elapsed_ms=total_elapsed,
        run_id=run_id,
        model_tier="Compass System",
        step_cost_usd=0.0,
        metadata={"report_card": report_card, "abstained": is_abstained, "replan_diff": active_replan_diff},
    )
