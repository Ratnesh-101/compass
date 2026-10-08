"""
Compass Agent — Step Tool Executor.
Executes individual agent tool calls, handles audit logging, zero-memory epistemic checks, and generates observe steps.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.agent_persistence import record_audit_log
from backend.agent_types import AgentStep, MUTATING_TOOLS

logger = logging.getLogger("compass.agent_step_executor")

_ORIGINAL_MEMORY_TOOLS = frozenset({
    "query_tasks",
    "query_coursework_notes",
    "query_code_context",
})

_WIDENED_MEMORY_TOOLS = frozenset({
    "get_hackathon_deadlines",
    "list_projects",
    "query_coursework_tasks",
    "detect_deadline_conflicts",
    "summarize_day",
    "summarize_across_domains",
})

_MEMORY_QUERY_TOOLS = _ORIGINAL_MEMORY_TOOLS | _WIDENED_MEMORY_TOOLS


async def execute_agent_tool_step(
    func_name: str,
    tool_args: Dict[str, Any],
    raw_args: str,
    tc_id: str,
    step_num: int,
    step_start: float,
    run_id: str,
    pool: Any,
    user_id: Optional[str],
    goal: str,
    abstain_first: bool,
    search_web_unlocked: bool,
    tools_used: List[str],
) -> Tuple[AgentStep, str, bool, Dict[str, Any], Dict[str, Any]]:
    """Execute a skill tool and return the resulting observe step, tool output, and updated web search unlock flag."""
    from backend.skills import SKILL_REGISTRY

    tool_result = ""
    updated_search_web_unlocked = search_web_unlocked

    if func_name in SKILL_REGISTRY:
        from backend.skills.registry import GUEST_DISALLOWED_TOOLS
        is_guest = bool(user_id and str(user_id).startswith("guest_"))
        if is_guest and func_name in GUEST_DISALLOWED_TOOLS:
            denied_msg = f"Permission denied: Guest sessions are forbidden from executing high-risk or external side-effect tool '{func_name}'. Please sign in."
            logger.warning("Blocked guest execution of tool '%s' for identity %s", func_name, user_id)
            return (
                AgentStep(
                    type="observe",
                    content=denied_msg,
                    step_number=step_num,
                    elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                    tool_name=func_name,
                    run_id=run_id,
                    model_tier="Compass Permission Gate",
                    step_cost_usd=0.0,
                ),
                denied_msg,
                updated_search_web_unlocked,
                {},
                {},
            )

        if user_id and isinstance(tool_args, dict) and "user_id" not in tool_args:
            tool_args["user_id"] = user_id
        try:
            prev_state = None
            affected_id = None
            if pool and func_name in MUTATING_TOOLS:
                if func_name in ("edit_task", "update_task_status", "delete_task"):
                    tid = tool_args.get("task_id")
                    if tid:
                        async with pool.acquire() as conn:
                            row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", int(tid))
                            if row:
                                prev_state = dict(row)
                                for k, v in prev_state.items():
                                    if hasattr(v, "isoformat"):
                                        prev_state[k] = v.isoformat()
                                affected_id = int(tid)

            result = await SKILL_REGISTRY[func_name](tool_args, pool)
            tool_result = result.get("response", str(result.get("data", "")))
            tools_used.append(func_name)

            if abstain_first and func_name in _MEMORY_QUERY_TOOLS:
                is_zero = False
                data_field = result.get("data")
                if data_field is None or (isinstance(data_field, (list, dict)) and len(data_field) == 0):
                    is_zero = True
                elif isinstance(data_field, dict):
                    if data_field.get("count") == 0:
                        is_zero = True
                    elif "chunks" in data_field and len(data_field.get("chunks", [])) == 0:
                        is_zero = True
                    elif "tasks" in data_field and len(data_field.get("tasks", [])) == 0:
                        is_zero = True
                    elif "projects" in data_field and len(data_field.get("projects", [])) == 0:
                        is_zero = True
                    elif "notes" in data_field and len(data_field.get("notes", [])) == 0:
                        is_zero = True
                    elif "findings" in data_field and len(data_field.get("findings", {})) == 0:
                        is_zero = True
                    elif data_field.get("status") in ("unavailable", "error"):
                        is_zero = True
                    elif "error" in data_field:
                        is_zero = True

                resp_str = str(result.get("response", "")).lower()
                if any(phrase in resp_str for phrase in (
                    "found 0", "retrieved 0", "0 task", "0 active", "0 deliverable",
                    "0 relevant", "0 result", "0 tracked", "no tracked", "no task",
                    "no active", "no deliverable", "no deadline", "no note", "no relevant",
                    "no matching", "not found", "task_id is required", "error",
                    "failed", "none found"
                )):
                    is_zero = True

                if not is_zero and isinstance(data_field, dict) and "tasks" in data_field:
                    t_list = data_field.get("tasks") or []
                    if t_list and "devpost" in goal.lower():
                        if not any("devpost" in str(t).lower() for t in t_list):
                            is_zero = True

                if tools_used.count(func_name) >= 2:
                    is_zero = True

                if is_zero:
                    if func_name in _ORIGINAL_MEMORY_TOOLS:
                        updated_search_web_unlocked = True
                    else:
                        memory_calls_count = sum(1 for t in tools_used if t in _MEMORY_QUERY_TOOLS)
                        if memory_calls_count >= 2:
                            updated_search_web_unlocked = True

            if pool and func_name in MUTATING_TOOLS:
                new_st = None
                if func_name == "add_task":
                    tdata = result.get("data", {})
                    if isinstance(tdata, dict) and "id" in tdata:
                        affected_id = tdata["id"]
                        new_st = dict(tdata)
                elif func_name in ("edit_task", "update_task_status"):
                    tdata = result.get("data", {})
                    if isinstance(tdata, dict) and "id" in tdata:
                        new_st = dict(tdata)

                await record_audit_log(
                    pool=pool,
                    tool=func_name,
                    args=tool_args,
                    run_id=run_id,
                    affected_table="memory_chunks" if func_name in ("ingest_url", "log_code_snippet", "log_code_context") else "tasks",
                    affected_id=affected_id,
                    previous_state=prev_state,
                    new_state=new_st,
                    approved_by="user",
                )

        except Exception as e:
            tool_result = f"Tool execution error: {e}"
            logger.warning(f"Agent tool {func_name} failed: {e}")
    else:
        tool_result = f"Tool '{func_name}' is not available."

    obs_tier = "Tavily Web Intelligence" if func_name in ("search_web", "ingest_url", "verify_deadline") else "Neon Postgres Engine"
    obs_step = AgentStep(
        type="observe",
        content=tool_result,
        tool_name=func_name,
        step_number=step_num,
        elapsed_ms=int((time.perf_counter() - step_start) * 1000),
        run_id=run_id,
        model_tier=obs_tier,
        step_cost_usd=0.0,
    )

    asst_payload = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": tc_id, "type": "function", "function": {"name": func_name, "arguments": raw_args}}
        ],
    }
    tool_payload = {
        "role": "tool",
        "tool_call_id": tc_id,
        "content": tool_result,
    }

    return obs_step, tool_result, updated_search_web_unlocked, asst_payload, tool_payload
