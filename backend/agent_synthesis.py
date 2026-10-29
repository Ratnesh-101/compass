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


from datetime import datetime


async def force_final_synthesis(
    client: AsyncOpenAI,
    settings: Any,
    messages: List[Dict[str, Any]],
    step_num: int,
    start_time: float,
    run_id: str,
    active_replan_diff: Optional[Dict[str, Any]],
    tone: Optional[str] = None,
) -> Tuple[AgentStep, float, bool]:
    """Force final synthesis with Nemotron-3 Ultra (550B) with dynamic clock and bounded continuation."""
    now_dt = datetime.now().astimezone()
    today_str = now_dt.strftime("%A, %B %d, %Y (%Z)")

    synth_prompt = (
        "You've gathered enough information. Please produce your final answer now.\n\n"
        f"### Temporal & Completeness Guidelines (Current Date: {today_str}):\n"
        f"- Current reference date is {today_str}. Compare all event dates against this date.\n"
        "- Any event whose submission deadline or end date is in the past MUST be designated as [ENDED] or past; never claim it is 'starting today' or 'one week away'.\n"
        "- For tables, include full rows with complete details and closing markdown pipes (|).\n"
        "- For factual claims, cite the verified source URL and status.\n"
        "- Never emit literal bracketed placeholders such as '[time]' or '[date]'; explicitly state 'time not shown in source' instead."
    )

    clean_tone = (tone or "").strip().lower()
    if clean_tone == "brief":
        synth_tokens = 90
        synth_prompt += (
            "\n\n[TONE CONSTRAINT: STRICTLY BRIEF]\n"
            "Keep your response extremely brief, direct, and concise (1-2 sentences maximum, strictly under 40 words). "
            "State the core answer or count + top item immediately with zero preamble or conversational filler. No follow-up questions."
        )
    elif clean_tone == "balanced":
        synth_tokens = 250
        synth_prompt += (
            "\n\n[TONE CONSTRAINT: BALANCED]\n"
            "Provide a balanced, well-rounded response (2-4 clear sentences, roughly 60-100 words). "
            "Balance brevity with helpful context and next steps."
        )
    elif clean_tone == "exploratory":
        synth_tokens = 1500
        synth_prompt += (
            "\n\n[TONE CONSTRAINT: COMPREHENSIVE EXPLORATION]\n"
            "Provide a comprehensive, in-depth exploration (at least 150 words). "
            "Think out loud, examine nuances, provide context and rationale, and outline forward-looking recommendations."
        )
    else:
        synth_tokens = int(getattr(settings, "MAX_SYNTHESIS_TOKENS", 8192))

    messages.append({
        "role": "user",
        "content": synth_prompt,
    })
    max_continuations = int(getattr(settings, "MAX_CONTINUATION_ATTEMPTS", 2))

    completions = client.chat.completions
    t0 = time.perf_counter()
    response = await completions.create(
        model=str(settings.SYNTHESIS_MODEL),
        messages=cast(Any, messages),
        max_tokens=synth_tokens,
        temperature=0.5,
        stream=False,
    )
    dur_ms = int((time.perf_counter() - t0) * 1000)
    usage = getattr(response, "usage", None)
    p_tok = usage.prompt_tokens if usage else 500
    c_tok = usage.completion_tokens if usage else 200
    record_usage(settings.SYNTHESIS_MODEL, p_tok, c_tok, duration_ms=dur_ms)
    forced_cost = compute_step_cost(settings.SYNTHESIS_MODEL, p_tok, c_tok)

    raw_text = await _extract_content_from_response(response, default_text="Agent completed analysis.")
    first_choice = response.choices[0] if getattr(response, "choices", None) else None
    finish_reason = getattr(first_choice, "finish_reason", None)
    is_truncated = (finish_reason == "length")

    # Bounded continuation if response was cut off by length limit
    continuation_attempts = 0
    while is_truncated and continuation_attempts < max_continuations:
        continuation_attempts += 1
        logger.info(
            "Final synthesis hit length cap (attempt %d/%d). Initiating bounded continuation for run_id=%s",
            continuation_attempts,
            max_continuations,
            run_id,
        )
        cont_messages = list(messages)
        cont_messages.append({"role": "assistant", "content": raw_text})
        cont_messages.append({
            "role": "user",
            "content": "Continue exactly where you left off. Do not repeat previously generated headings, text, or table rows.",
        })
        try:
            t0_cont = time.perf_counter()
            cont_resp = await completions.create(
                model=str(settings.SYNTHESIS_MODEL),
                messages=cast(Any, cont_messages),
                max_tokens=synth_tokens,
                temperature=0.5,
                stream=False,
            )
            c_dur_ms = int((time.perf_counter() - t0_cont) * 1000)
            c_usage = getattr(cont_resp, "usage", None)
            c_p_tok = c_usage.prompt_tokens if c_usage else 500
            c_c_tok = c_usage.completion_tokens if c_usage else 200
            record_usage(settings.SYNTHESIS_MODEL, c_p_tok, c_c_tok, duration_ms=c_dur_ms)
            forced_cost += compute_step_cost(settings.SYNTHESIS_MODEL, c_p_tok, c_c_tok)

            cont_text = await _extract_content_from_response(cont_resp, default_text="")
            cont_choice = cont_resp.choices[0] if getattr(cont_resp, "choices", None) else None
            finish_reason = getattr(cont_choice, "finish_reason", None)
            is_truncated = (finish_reason == "length")

            if cont_text:
                raw_text = raw_text.rstrip() + "\n" + cont_text.lstrip()
            else:
                break
        except Exception as cont_err:
            logger.warning("Continuation request failed: %s; stopping continuation.", cont_err)
            break

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
            "is_truncated": is_truncated,
            "finish_reason": finish_reason,
            "continuation_attempts": continuation_attempts,
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
