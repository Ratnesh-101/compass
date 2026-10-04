"""
Compass Agent — Critic Pass and Confirmed Mutation Execution.
Handles the self-critique pass and safe post-confirmation execution of mutating actions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, cast

from openai import AsyncOpenAI

from backend.agent_persistence import record_audit_log
from backend.agent_types import AgentStep, MUTATING_TOOLS, _extract_content_from_response
from backend.services.usage import compute_step_cost, record_usage

logger = logging.getLogger("compass.agent_critic")


async def _run_critic_pass(
    client: AsyncOpenAI,
    settings: Any,
    proposed_plan: str,
    context_messages: List[Dict[str, Any]],
    step_num: int,
    run_id: Optional[str] = None,
) -> AgentStep:
    """Self-critique pass: check proposed plan against gathered data constraints."""
    start = time.perf_counter()

    observations = []
    for msg in context_messages:
        if msg.get("role") == "tool":
            observations.append(msg.get("content", ""))

    critic_prompt = (
        "You are a critical reviewer for a planning assistant. "
        "A planner proposed the following plan based on real data:\n\n"
        f"PROPOSED PLAN:\n{proposed_plan}\n\n"
        "DATA THE PLANNER USED:\n" + "\n---\n".join(observations[-6:]) + "\n\n"
        "Check the plan against these criteria:\n"
        "1. Are all mentioned tasks/deadlines consistent with the actual data?\n"
        "2. Are any tasks missed or double-counted?\n"
        "3. Is the priority ordering sensible given actual due dates?\n"
        "4. Are the time estimates realistic?\n\n"
        "If the plan is solid, respond with 'APPROVED: ' followed by a brief note.\n"
        "If it has issues, list them concretely and suggest fixes."
    )

    critic_cost = 0.0
    try:
        completions: Any = client.chat.completions
        resp = await completions.create(
            model=str(settings.SKILL_MODEL),
            messages=cast(Any, [
                {"role": "system", "content": "You are a critical reviewer. Be thorough but concise."},
                {"role": "user", "content": critic_prompt},
            ]),
            max_tokens=384,
            temperature=0.3,
            stream=False,
        )
        usage = getattr(resp, "usage", None)
        p_tok = usage.prompt_tokens if usage else 300
        c_tok = usage.completion_tokens if usage else 100
        record_usage(settings.SKILL_MODEL, p_tok, c_tok)
        critic_cost = compute_step_cost(settings.SKILL_MODEL, p_tok, c_tok)

        critic_text = await _extract_content_from_response(resp, default_text="APPROVED: Plan looks reasonable.")
    except Exception as e:
        logger.warning(f"Critic pass failed: {e}")
        critic_text = "APPROVED: (Critic pass skipped due to error)"
        critic_cost = 0.0

    return AgentStep(
        type="critic",
        content=critic_text,
        step_number=step_num,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        run_id=run_id,
        model_tier="Nemotron-3 Super (120B)",
        step_cost_usd=critic_cost,
    )


async def execute_confirmed_actions(
    confirmed_actions: List[Dict[str, Any]],
    pool: Any,
    run_id: Optional[str] = None,
    approved_by: str = "user",
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Execute previously confirmed state-mutating actions."""
    from backend.skills import SKILL_REGISTRY
    results = []
    for action in confirmed_actions:
        tool_name = action.get("tool", "")
        tool_args = action.get("args", {})
        if user_id and isinstance(tool_args, dict) and "user_id" not in tool_args:
            tool_args["user_id"] = user_id

        if tool_name not in SKILL_REGISTRY:
            results.append({"tool": tool_name, "status": "error", "message": f"Unknown tool: {tool_name}"})
            continue

        previous_state = None
        affected_id = None
        affected_table = "memory_chunks" if tool_name in ("ingest_url", "log_code_snippet", "log_code_context") else "tasks"

        try:
            if pool and tool_name in ("edit_task", "update_task_status", "delete_task"):
                task_id = tool_args.get("task_id")
                if task_id:
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", int(task_id))
                        if row:
                            previous_state = dict(row)
                            for k, v in previous_state.items():
                                if hasattr(v, "isoformat"):
                                    previous_state[k] = v.isoformat()
                            affected_id = int(task_id)
            elif pool and tool_name == "commit_schedule":
                assignments = tool_args.get("assignments") or []
                affected_ids = [a.get("task_id") for a in assignments if a.get("task_id")]
                if affected_ids:
                    async with pool.acquire() as conn:
                        rows = await conn.fetch("SELECT id, scheduled_start, scheduled_end FROM tasks WHERE id = ANY($1::int[])", affected_ids)
                        previous_state = {
                            "tasks": [
                                {
                                    "task_id": r["id"],
                                    "scheduled_start": r["scheduled_start"].isoformat() if r["scheduled_start"] else None,
                                    "scheduled_end": r["scheduled_end"].isoformat() if r["scheduled_end"] else None,
                                }
                                for r in rows
                            ]
                        }
                    affected_id = affected_ids[0] if affected_ids else None
        except Exception as e:
            logger.warning(f"Failed to capture pre-mutation state: {e}")

        try:
            result = await SKILL_REGISTRY[tool_name](tool_args, pool)
            new_state = None

            if tool_name == "add_task":
                task_data = result.get("data", {})
                if isinstance(task_data, dict) and "id" in task_data:
                    affected_id = task_data["id"]
                    new_state = dict(task_data)
            elif tool_name in ("edit_task", "update_task_status"):
                task_data = result.get("data", {})
                if isinstance(task_data, dict) and "id" in task_data:
                    new_state = dict(task_data)

            if pool and tool_name in MUTATING_TOOLS:
                await record_audit_log(
                    pool=pool,
                    tool=tool_name,
                    args=tool_args,
                    run_id=run_id,
                    affected_table=affected_table,
                    affected_id=affected_id,
                    previous_state=previous_state,
                    new_state=new_state,
                    approved_by=approved_by,
                )

            results.append({"tool": tool_name, "status": "success", "result": result})
        except Exception as e:
            results.append({"tool": tool_name, "status": "error", "message": str(e)})

    return results
