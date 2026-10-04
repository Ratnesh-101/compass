"""
Compass Agent — ReAct-style autonomous multi-step reasoning engine.

Runs a Think→Act→Observe loop using Nemotron-3 Super (120B) for reasoning
and existing SKILL_REGISTRY tools for actions. Final synthesis via Ultra (550B).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, cast

from openai import AsyncOpenAI

from backend.agent_critic import _run_critic_pass, execute_confirmed_actions
from backend.agent_escalation import evaluate_abstention_and_web_escalation
from backend.agent_persistence import (
    MAX_CONCURRENT_AGENT_RUNS,
    count_active_agent_runs,
    get_agent_run,
    get_critique_stats,
    record_audit_log,
    save_agent_run,
    undo_last_agent_action,
)
from backend.agent_step_executor import execute_agent_tool_step
from backend.agent_synthesis import build_done_step, force_final_synthesis
from backend.agent_types import (
    AgentStep,
    MUTATING_TOOLS,
    READ_ONLY_TOOLS,
    _PENDING_CONFIRMATION_EVENTS,
    _build_agent_system_prompt,
    _clean_synthesis_text,
    _extract_content_from_response,
)
from backend.config import get_settings
from backend.services.usage import compute_step_cost, record_usage

logger = logging.getLogger("compass.agent")


async def run_agent(
    goal: str,
    pool: Any = None,
    max_steps: int = 8,
    enable_critic: bool = True,
    confirmed_actions: Optional[List[Dict[str, Any]]] = None,
    run_id: Optional[str] = None,
    action: Optional[str] = None,
    feedback: Optional[str] = None,
    confirm_timeout_seconds: float = 300.0,
    wait_for_confirmation: bool = False,
    client: Optional[AsyncOpenAI] = None,
    settings: Any = None,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> AsyncGenerator[AgentStep, None]:
    """Core ReAct agent loop yielding AgentStep objects for real-time SSE streaming."""
    if settings is None:
        settings = get_settings()
    step_num = 0
    start_time = time.perf_counter()
    tools_used: List[str] = []
    pending_confirmations: List[Dict[str, Any]] = []
    accumulated_steps: List[AgentStep] = []
    messages: List[Dict[str, Any]] = []
    critique_rounds: int = 0

    run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

    from backend.skills import get_tool_definitions

    if client is None:
        client = AsyncOpenAI(
            api_key=settings.NEBIUS_API_KEY,
            base_url=settings.NEBIUS_BASE_URL,
            timeout=30.0,
        )

    agent_tools = get_tool_definitions()

    confirmed_actions = confirmed_actions or []
    confirmed_set = {
        (a.get("tool"), json.dumps(a.get("args", {}), sort_keys=True))
        for a in confirmed_actions
    }

    total_run_cost_usd: float = 0.0
    is_abstained: bool = False
    web_escalation_used: bool = False
    forced_tool_choice: Optional[Any] = None
    active_replan_diff: Optional[Dict[str, Any]] = None
    abstain_first: bool = getattr(settings, "TAVILY_ABSTAIN_FIRST", False)
    search_web_unlocked: bool = not abstain_first
    logger.info("SETTINGS.TAVILY_ABSTAIN_FIRST loaded inside run_agent: %s (run_id=%s)", abstain_first, run_id)

    existing_run = await get_agent_run(pool, run_id) if pool else None

    if action in ("approve", "reject"):
        if existing_run:
            goal = existing_run.get("goal", goal)
            if existing_run.get("conversation_id") and not conversation_id:
                conversation_id = existing_run.get("conversation_id")
            messages = existing_run.get("messages", [])
            pending_confirmations = existing_run.get("pending_actions", [])
            step_num = len(existing_run.get("accumulated_steps", []))

            for s in existing_run.get("accumulated_steps", []):
                cost_val = s.get("step_cost_usd")
                if cost_val is not None:
                    total_run_cost_usd += float(cost_val)
                accumulated_steps.append(AgentStep(
                    type=s.get("type", "think"),
                    content=s.get("content", ""),
                    tool_name=s.get("tool_name"),
                    tool_args=s.get("tool_args"),
                    step_number=s.get("step_number", 0),
                    elapsed_ms=s.get("elapsed_ms", 0),
                    run_id=run_id,
                    model_tier=s.get("model_tier"),
                    step_cost_usd=s.get("step_cost_usd"),
                    metadata=s.get("metadata"),
                ))
        else:
            messages = cast(List[Dict[str, Any]], [
                {"role": "system", "content": _build_agent_system_prompt([t["function"]["name"] for t in agent_tools if "function" in t])},
                {"role": "user", "content": goal},
            ])

        if action == "reject":
            declined_action = pending_confirmations[0] if pending_confirmations else {}
            active_replan_diff = {
                "declined_action": declined_action,
                "feedback": feedback or "User declined proposed action",
                "replan_status": "re_planning_alternative",
            }
            rej_content = (
                f"User declined: {feedback or 'do not execute this action'}. "
                "Please re-plan without modifying this data or propose an alternative approach."
            )
            tc_id = "call_rejected"
            if messages and isinstance(messages[-1], dict) and isinstance(messages[-1].get("tool_calls"), list) and messages[-1]["tool_calls"]:
                first_tc = messages[-1]["tool_calls"][0]
                if isinstance(first_tc, dict) and "id" in first_tc:
                    tc_id = str(first_tc["id"])
                elif hasattr(first_tc, "id"):
                    tc_id = str(getattr(first_tc, "id", "call_rejected"))

            messages.append({"role": "tool", "tool_call_id": tc_id, "content": rej_content})
            step_num += 1
            obs_step = AgentStep(
                type="observe",
                content=rej_content,
                tool_name=pending_confirmations[0]["tool"] if pending_confirmations else None,
                step_number=step_num,
                elapsed_ms=0,
                run_id=run_id,
                model_tier="Human Authorization Gate",
                step_cost_usd=0.0,
                metadata={"replan_diff": active_replan_diff},
            )
            yield obs_step
            accumulated_steps.append(obs_step)
            pending_confirmations.clear()
            if pool:
                await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations, conversation_id=conversation_id)

        elif action == "approve" and pending_confirmations:
            step_num += 1
            ack_step = AgentStep(
                type="confirm_ack",
                content=f"Actions approved by user: {json.dumps(pending_confirmations)}",
                step_number=step_num,
                elapsed_ms=0,
                run_id=run_id,
                model_tier="Human Authorization Gate",
                step_cost_usd=0.0,
            )
            yield ack_step
            accumulated_steps.append(ack_step)

            exec_results = await execute_confirmed_actions(
                confirmed_actions=pending_confirmations,
                pool=pool,
                run_id=run_id,
                approved_by="user",
                user_id=user_id,
            )

            tc_id = "call_approved"
            if messages and isinstance(messages[-1], dict) and isinstance(messages[-1].get("tool_calls"), list) and messages[-1]["tool_calls"]:
                first_tc = messages[-1]["tool_calls"][0]
                if isinstance(first_tc, dict) and "id" in first_tc:
                    tc_id = str(first_tc["id"])
                elif hasattr(first_tc, "id"):
                    tc_id = str(getattr(first_tc, "id", "call_approved"))

            tool_content = json.dumps(exec_results, default=str)
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": tool_content})
            step_num += 1
            obs_step = AgentStep(
                type="observe",
                content=tool_content,
                tool_name=pending_confirmations[0]["tool"] if pending_confirmations else None,
                step_number=step_num,
                elapsed_ms=0,
                run_id=run_id,
                model_tier="Neon Postgres Engine",
                step_cost_usd=0.0,
            )
            yield obs_step
            accumulated_steps.append(obs_step)

            for a in pending_confirmations:
                tools_used.append(a.get("tool", ""))
            pending_confirmations.clear()
            if pool:
                await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations, conversation_id=conversation_id)

    elif existing_run and existing_run.get("status") == "paused":
        return

    else:
        conv_context = ""
        if conversation_id and pool:
            try:
                from backend.memory import conversations
                async with pool.acquire() as conn:
                    recent_msgs = await conversations.get_recent_messages(conn, conversation_id, limit=5)
                if recent_msgs:
                    history_lines = [f"{m['role'].upper()}: {m['content']}" for m in recent_msgs]
                    conv_context = "\n\nRecent User Conversation Context:\n" + "\n".join(history_lines)
            except Exception as e:
                logger.debug(f"Could not load conversation context: {e}")

        user_content = f"{goal}{conv_context}" if conv_context else goal
        system_content = _build_agent_system_prompt(
            [t["function"]["name"] for t in agent_tools if "function" in t],
            abstain_first=abstain_first,
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        if pool:
            await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations, conversation_id=conversation_id)

    for iteration in range(max_steps):
        step_start = time.perf_counter()

        filtered_tools = agent_tools
        if abstain_first and not search_web_unlocked:
            filtered_tools = [t for t in agent_tools if t.get("function", {}).get("name") != "search_web"]

        tool_choice_param: Any = forced_tool_choice if forced_tool_choice is not None else ("auto" if filtered_tools else "none")
        forced_tool_choice = None

        try:
            reasoning_model = str(getattr(settings, "REASONING_MODEL", getattr(settings, "SKILL_MODEL", "nvidia/nemotron-3-super-120b-a12b")))
            completions: Any = client.chat.completions
            response = await completions.create(
                model=reasoning_model,
                messages=cast(Any, messages),
                tools=filtered_tools or None,
                tool_choice=tool_choice_param,
                temperature=0.2,
                max_tokens=1024,
                stream=False,
            )

            if response is None:
                step_num += 1
                mock_step = AgentStep(
                    type="done",
                    content="Mock mode: API key not configured.",
                    step_number=step_num,
                    elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                    run_id=run_id,
                    model_tier="Mock",
                    step_cost_usd=0.0,
                )
                yield mock_step
                accumulated_steps.append(mock_step)
                break

            choice = response.choices[0]
            usage = getattr(response, "usage", None)
            p_tok = usage.prompt_tokens if usage else 200
            c_tok = usage.completion_tokens if usage else 80
            record_usage(reasoning_model, p_tok, c_tok)
            step_cost = compute_step_cost(reasoning_model, p_tok, c_tok)
            total_run_cost_usd += step_cost
            elapsed = int((time.perf_counter() - step_start) * 1000)

            # Check if model chose a tool call
            if choice.message.tool_calls:
                tc = choice.message.tool_calls[0]
                tc_id = tc.id
                func_name = tc.function.name
                raw_args = tc.function.arguments

                if abstain_first and not search_web_unlocked and func_name == "search_web":
                    func_name = "query_tasks"
                    raw_args = json.dumps({"query": goal[:100]})

                if (
                    func_name not in ("search_web", "ingest_url", "verify_deadline")
                    and not web_escalation_used
                    and iteration >= max_steps - 2
                ):
                    try:
                        from backend.services.tavily import tavily_available
                        tavily_ok = tavily_available()
                    except Exception:
                        tavily_ok = False
                    if tavily_ok:
                        web_escalation_used = True
                        search_web_unlocked = True
                        forced_tool_choice = {"type": "function", "function": {"name": "search_web"}}
                        step_num += 1
                        escalate_step = AgentStep(
                            type="escalate",
                            content="Approaching step limit without an answer from stored memory. Escalating to live web search.",
                            step_number=step_num,
                            elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                            run_id=run_id,
                            model_tier="Tavily Web Intelligence",
                            step_cost_usd=0.0,
                            metadata={"reason": "step_limit_fallback", "provider": "tavily"},
                        )
                        yield escalate_step
                        accumulated_steps.append(escalate_step)

                        messages.append({"role": "assistant", "content": "[ABSTAIN] Memory does not contain the required information."})
                        messages.append({
                            "role": "user",
                            "content": (
                                "Stored memory does not cover this question. Please call the 'search_web' tool "
                                "now to retrieve current information from the live web to answer the goal."
                            ),
                        })
                        continue
                    else:
                        is_abstained = True

                try:
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except Exception:
                    tool_args = {}

                if choice.message.content:
                    think_step = AgentStep(
                        type="think",
                        content=choice.message.content,
                        step_number=step_num,
                        elapsed_ms=elapsed,
                        run_id=run_id,
                        model_tier="Nemotron-3 Super (120B)",
                        step_cost_usd=step_cost,
                    )
                    yield think_step
                    accumulated_steps.append(think_step)
                    step_num += 1

                tc_step = AgentStep(
                    type="tool_call",
                    content=f"Calling {func_name}",
                    tool_name=func_name,
                    tool_args=tool_args,
                    step_number=step_num,
                    elapsed_ms=elapsed,
                    run_id=run_id,
                    model_tier="Nemotron-3 Super (120B)",
                    step_cost_usd=step_cost if not choice.message.content else 0.0,
                )
                yield tc_step
                accumulated_steps.append(tc_step)

                # --- Confirmation gate for mutating tools ---
                if func_name in MUTATING_TOOLS:
                    action_key = (func_name, json.dumps(tool_args, sort_keys=True))
                    if action_key not in confirmed_set:
                        step_num += 1
                        confirm_step = AgentStep(
                            type="confirm_request",
                            content=f"Agent wants to execute: {func_name}({json.dumps(tool_args)}). This will modify your data. Please confirm.",
                            tool_name=func_name,
                            tool_args=tool_args,
                            step_number=step_num,
                            elapsed_ms=0,
                            run_id=run_id,
                            model_tier="Human Authorization Gate",
                            step_cost_usd=0.0,
                        )
                        yield confirm_step
                        accumulated_steps.append(confirm_step)
                        act_id = None
                        if pool:
                            from backend.agent_pending import register_pending_action
                            act_id = await register_pending_action(
                                pool, run_id, user_id or "default_user", func_name, tool_args, confirm_timeout_seconds
                            )
                        pending_confirmations.append({"action_id": act_id, "tool": func_name, "args": tool_args})

                        asst_payload: Dict[str, Any] = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {"id": tc_id, "type": "function", "function": {"name": func_name, "arguments": raw_args}}
                            ]
                        }
                        cast(List[Any], messages).append(asst_payload)

                        if pool:
                            await save_agent_run(
                                pool, run_id, goal, "paused",
                                accumulated_steps, messages, pending_confirmations,
                                conversation_id=conversation_id,
                            )

                        if wait_for_confirmation:
                            evt = asyncio.Event()
                            outcome: Dict[str, Any] = {}
                            _PENDING_CONFIRMATION_EVENTS[run_id] = (evt, outcome)

                            try:
                                from backend.agent_pending import wait_for_pending_action
                                res_action, res_feedback = await wait_for_pending_action(
                                    pool, run_id, evt, outcome, timeout_seconds=confirm_timeout_seconds
                                )
                            except asyncio.TimeoutError:
                                if pool:
                                    await save_agent_run(
                                        pool, run_id, goal, "expired",
                                        accumulated_steps, messages, pending_confirmations,
                                        conversation_id=conversation_id,
                                    )
                                step_num += 1
                                timeout_step = AgentStep(
                                    type="done",
                                    content=json.dumps({
                                        "status": "expired",
                                        "draft_saved": True,
                                        "run_id": run_id,
                                        "message": f"Confirmation timed out after {int(confirm_timeout_seconds)}s. Partial run saved as draft.",
                                    }),
                                    step_number=step_num,
                                    elapsed_ms=int((time.perf_counter() - start_time) * 1000),
                                    run_id=run_id,
                                    model_tier="Compass Timeout Watcher",
                                    step_cost_usd=0.0,
                                )
                                yield timeout_step
                                return
                            finally:
                                _PENDING_CONFIRMATION_EVENTS.pop(run_id, None)

                            if res_action == "reject":
                                active_replan_diff = {
                                    "declined_action": {"tool": func_name, "args": tool_args},
                                    "feedback": res_feedback or f"do not execute {func_name}",
                                    "replan_status": "re_planning_alternative",
                                }
                                rej_msg = (
                                    f"User declined: {res_feedback or f'do not execute {func_name}'}. "
                                    "Please re-plan without modifying this data."
                                )
                                messages.append({"role": "tool", "tool_call_id": tc.id, "content": rej_msg})
                                step_num += 1
                                rej_step = AgentStep(
                                    type="observe",
                                    content=rej_msg,
                                    tool_name=func_name,
                                    step_number=step_num,
                                    elapsed_ms=0,
                                    run_id=run_id,
                                    model_tier="Human Authorization Gate",
                                    step_cost_usd=0.0,
                                    metadata={"replan_diff": active_replan_diff},
                                )
                                yield rej_step
                                accumulated_steps.append(rej_step)
                                pending_confirmations.clear()
                                if pool:
                                    await save_agent_run(pool, run_id, goal, "running", accumulated_steps, messages, pending_confirmations, conversation_id=conversation_id)
                                continue
                            else:
                                confirmed_set.add(action_key)
                        else:
                            return

                # Execute tool using step executor
                obs_step, tool_result, search_web_unlocked, a_pay, t_pay = await execute_agent_tool_step(
                    func_name=func_name,
                    tool_args=tool_args,
                    raw_args=raw_args,
                    tc_id=tc_id,
                    step_num=step_num,
                    step_start=step_start,
                    run_id=run_id,
                    pool=pool,
                    user_id=user_id,
                    goal=goal,
                    abstain_first=abstain_first,
                    search_web_unlocked=search_web_unlocked,
                    tools_used=tools_used,
                )
                step_num += 1
                obs_step.step_number = step_num
                yield obs_step
                accumulated_steps.append(obs_step)
                cast(List[Any], messages).append(a_pay)
                cast(List[Any], messages).append(t_pay)

            # --- Text response branch (agent wants to synthesize) ---
            else:
                reply = choice.message.content or ""

                should_escalate, is_abstained_signal, escalate_step, step_num = evaluate_abstention_and_web_escalation(
                    reply=reply,
                    tools_used=tools_used,
                    abstain_first=abstain_first,
                    web_escalation_used=web_escalation_used,
                    run_id=run_id,
                    step_start=step_start,
                    step_num=step_num,
                    messages=messages,
                )
                if is_abstained_signal:
                    is_abstained = True
                if should_escalate and escalate_step:
                    web_escalation_used = True
                    search_web_unlocked = True
                    forced_tool_choice = {"type": "function", "function": {"name": "search_web"}}
                    yield escalate_step
                    accumulated_steps.append(escalate_step)
                    continue

                if enable_critic and reply:
                    step_num += 1
                    critic_step = await _run_critic_pass(
                        client, settings, reply, messages, step_num, run_id=run_id,
                    )
                    total_run_cost_usd += (critic_step.step_cost_usd or 0.0)
                    yield critic_step
                    accumulated_steps.append(critic_step)

                    critique_rounds += 1
                    if "APPROVED" not in critic_step.content.upper():
                        if critique_rounds < 2:
                            messages.append({"role": "assistant", "content": reply})
                            messages.append({
                                "role": "user",
                                "content": f"A reviewer checked your plan and found issues:\n\n{critic_step.content}\n\nPlease revise your plan to address these concerns.",
                            })
                            continue
                        else:
                            logger.info("Critique-revise cycle cap (2 rounds) reached; proceeding to synthesis.")

                if is_abstained:
                    provenance = "abstained"
                elif any(t in tools_used for t in ("search_web", "ingest_url", "verify_deadline")) or web_escalation_used:
                    provenance = "web"
                else:
                    provenance = "memory"

                step_num += 1
                synth_step = AgentStep(
                    type="synthesize",
                    content=_clean_synthesis_text(reply),
                    step_number=step_num,
                    elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                    run_id=run_id,
                    model_tier="Nemotron-3 Super (120B)",
                    step_cost_usd=0.0,
                    metadata={
                        "abstained": is_abstained,
                        "replan_diff": active_replan_diff,
                        "source": provenance,
                        "sources": [provenance],
                        "web_escalation_used": web_escalation_used,
                    },
                )
                yield synth_step
                accumulated_steps.append(synth_step)
                break

        except Exception as e:
            logger.error(f"Agent loop error at step {step_num}: {e}")
            step_num += 1
            err_step = AgentStep(
                type="error",
                content=f"Agent encountered an error: {e}",
                step_number=step_num,
                elapsed_ms=int((time.perf_counter() - step_start) * 1000),
                run_id=run_id,
                model_tier="Compass System",
                step_cost_usd=0.0,
            )
            yield err_step
            accumulated_steps.append(err_step)
            break

    else:
        step_num += 1
        try:
            forced_synth, forced_cost, is_abstained = await force_final_synthesis(
                client=client,
                settings=settings,
                messages=messages,
                step_num=step_num,
                start_time=start_time,
                run_id=run_id,
                active_replan_diff=active_replan_diff,
            )
            total_run_cost_usd += forced_cost
            yield forced_synth
            accumulated_steps.append(forced_synth)
        except Exception as e:
            err_step = AgentStep(
                type="error",
                content=f"Final synthesis failed: {e}",
                step_number=step_num,
                elapsed_ms=int((time.perf_counter() - start_time) * 1000),
                run_id=run_id,
                model_tier="Compass System",
                step_cost_usd=0.0,
            )
            yield err_step
            accumulated_steps.append(err_step)

    done_step = build_done_step(
        run_id=run_id,
        step_num=step_num,
        start_time=start_time,
        tools_used=tools_used,
        critique_rounds=critique_rounds,
        total_run_cost_usd=total_run_cost_usd,
        is_abstained=is_abstained,
        web_escalation_used=web_escalation_used,
        abstain_first=abstain_first,
        active_replan_diff=active_replan_diff,
        pending_confirmations=pending_confirmations,
        accumulated_steps=accumulated_steps,
    )
    yield done_step
    accumulated_steps.append(done_step)

    if pool:
        await save_agent_run(pool, run_id, goal, "completed", accumulated_steps, messages, pending_confirmations, conversation_id=conversation_id)


__all__ = [
    "AgentStep",
    "run_agent",
    "save_agent_run",
    "get_agent_run",
    "record_audit_log",
    "count_active_agent_runs",
    "get_critique_stats",
    "undo_last_agent_action",
    "execute_confirmed_actions",
    "_run_critic_pass",
    "MUTATING_TOOLS",
    "READ_ONLY_TOOLS",
    "_PENDING_CONFIRMATION_EVENTS",
    "_clean_synthesis_text",
    "_extract_content_from_response",
    "_build_agent_system_prompt",
    "MAX_CONCURRENT_AGENT_RUNS",
]
