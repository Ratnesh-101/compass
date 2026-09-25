"""
Compass — Skill Orchestrator.

Coordinates routing via Nemotron-3 Nano and execution of structured database operations.
"""

import time
import uuid
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any

from backend.router import route_message
from backend.memory.db import get_pool
from backend.memory import structured, conversations

logger = logging.getLogger("compass.orchestrator")

PRIORITY_MAP = {
    "urgent": "urgent", "critical": "urgent", "p0": "urgent", "asap": "urgent",
    "high": "high", "p1": "high", "important": "high",
    "medium": "medium", "normal": "medium", "p2": "medium", "moderate": "medium",
    "low": "low", "p3": "low", "minor": "low",
}

STATUS_MAP = {
    "open": "open", "todo": "open", "to_do": "open", "pending": "open", "not_started": "open",
    "in_progress": "in_progress", "in progress": "in_progress", "doing": "in_progress", "wip": "in_progress",
    "done": "done", "completed": "done", "finished": "done", "closed": "done",
    "overdue": "overdue",
}


def _parse_iso_date(val: Optional[str]) -> Optional[date]:
    if not val:
        return None
    try:
        parsed = datetime.strptime(val.strip(), "%Y-%m-%d").date()
        today = date.today()
        # If the date was parsed with a past year (e.g. LLM defaulted to 2024/2025 instead of current year),
        # roll it forward to the current year or next occurrence.
        if parsed < today and parsed.year < today.year:
            try:
                candidate = date(today.year, parsed.month, parsed.day)
                if candidate >= today:
                    return candidate
                return date(today.year + 1, parsed.month, parsed.day)
            except ValueError:
                pass
        return parsed
    except Exception:
        return None


async def handle_message(
    conversation_id: Optional[str],
    message: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process an incoming user message through router and skill handlers."""
    start_time = time.perf_counter()
    conv_id = conversation_id or str(uuid.uuid4())

    # Fetch recent history if conversation exists
    history = []
    if conversation_id:
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                rows = await conversations.get_recent_messages(conn, conversation_id, limit=6)
                for r in rows:
                    role = r.get("role", "user")
                    content = r.get("content", "")
                    if role in ("user", "assistant") and content:
                        history.append({"role": role, "content": content})
            logger.debug("Loaded history for %s: %s", conversation_id, history)
        except Exception as e:
            logger.debug(f"Could not load conversation history: {e}")

    # Load long-term cross-session memory & active tasks to prevent schedule conflicts
    memory_context = ""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            prior_messages = await conversations.get_cross_conversation_memory(
                conn, exclude_conversation_id=conversation_id, limit=6, user_id=user_id
            )
            if user_id:
                active_tasks = await conn.fetch(
                    """
                    SELECT title, domain, due_date, status, priority, duration_minutes
                    FROM tasks
                    WHERE status != 'completed' AND (user_id IS NULL OR user_id = $1)
                    ORDER BY due_date ASC NULLS LAST, priority DESC
                    LIMIT 8
                    """,
                    user_id
                )
            else:
                active_tasks = await conn.fetch(
                    """
                    SELECT title, domain, due_date, status, priority, duration_minutes
                    FROM tasks
                    WHERE status != 'completed'
                    ORDER BY due_date ASC NULLS LAST, priority DESC
                    LIMIT 8
                    """
                )
            recent_plans = await conn.fetch(
                """
                SELECT goal, status
                FROM agent_runs
                ORDER BY created_at DESC
                LIMIT 3
                """
            )

            sections = []
            if prior_messages:
                prior_str = "\n".join([f"- [{m.get('role', 'user')}]: {m.get('content', '')[:120]}" for m in prior_messages])
                sections.append(f"Past Chats Recall:\n{prior_str}")
            if active_tasks:
                task_str = "\n".join([
                    f"- {t['title']} ({t['domain']}) | Due: {t['due_date'] or 'Unscheduled'} | {t['duration_minutes'] or 60}m | {t['priority']}"
                    for t in active_tasks
                ])
                sections.append(f"Existing Tasks & Deadlines (Avoid schedule conflicts):\n{task_str}")
            if recent_plans:
                plan_str = "\n".join([f"- Plan: {p['goal']} ({p['status']})" for p in recent_plans])
                sections.append(f"Recent Planner Goals:\n{plan_str}")

            if sections:
                memory_context = "\n\n".join(sections)
    except Exception as e:
        logger.debug(f"Could not load cross-conversation memory: {e}")

    # 1. Route via Nemotron-3 Nano
    skill_name, args, text_reply = await route_message(
        message,
        history=history if history else None,
        memory_context=memory_context if memory_context else None,
    )
    if user_id and isinstance(args, dict):
        args["user_id"] = user_id

    # 2. Skill Execution: add_task
    if skill_name == "add_task" and args:
        title = args.get("title") or message
        domain = args.get("domain") or "general"
        project_name = args.get("project")
        due_str = args.get("due_date")
        due_date = _parse_iso_date(due_str)

        # Normalize priority & status
        raw_p = str(args.get("priority") or "medium").lower().strip()
        priority = PRIORITY_MAP.get(raw_p, "medium")
        raw_s = str(args.get("status") or "open").lower().strip()
        status = STATUS_MAP.get(raw_s, "open")

        notes = args.get("notes")

        # Normalize domain to valid enum
        valid_domains = {"hackathon", "coursework", "code", "general"}
        if domain not in valid_domains:
            domain = "general"

        task_record: Dict[str, Any] = {}
        shift_existing = bool(args.get("shift_existing", False))
        allow_different_thing = bool(args.get("allow_different_thing", False))
        allow_duplicate = bool(args.get("allow_duplicate", False))
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                existing_tasks = await structured.list_tasks(conn, user_id=user_id)
                exact_matches = [
                    t for t in existing_tasks
                    if t["title"].strip().lower() == title.lower()
                    and (
                        (t.get("due_date") is None and due_date is None)
                        or (t.get("due_date") == due_date)
                    )
                    and t.get("status") != "done"
                ]
                if exact_matches and not allow_duplicate:
                    ex = exact_matches[0]
                    d_str = ex.get("due_date") or "unscheduled"
                    resp = (
                        f"⚠️ A deadline with the exact same name '{ex['title']}' and due date ({d_str}) "
                        f"already exists in your schedule. You cannot add the exact same deadline multiple times. "
                        f"I can inspect your schedules to see when you have free slots or help you rebalance your tasks."
                    )
                    try:
                        real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id)
                        await conversations.add_message(conn, real_cid, role="user", content=message)
                        await conversations.add_message(conn, real_cid, role="assistant", content=resp, skill_called="add_task")
                        conv_id = real_cid
                    except Exception as e:
                        logger.debug(f"Could not persist message history: {e}")
                    return {
                        "conversation_id": conv_id,
                        "response": resp,
                        "message": resp,
                        "skill_used": "add_task",
                        "success": False,
                        "data": {"error": "duplicate_exact_deadline", "existing_task_id": ex["id"]},
                        "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
                    }

                same_name_matches = [
                    t for t in existing_tasks
                    if t["title"].strip().lower() == title.lower()
                    and t.get("status") != "done"
                ]
                if same_name_matches and not allow_different_thing and not allow_duplicate:
                    ex = same_name_matches[0]
                    old_d = ex.get("due_date") or "unscheduled"
                    new_d = due_date or "unscheduled"
                    if shift_existing:
                        task_record = await structured.update_task(
                            conn,
                            ex["id"],
                            due_date=due_date,
                            priority=priority,
                            notes=notes or ex.get("notes"),
                        )
                        resp = f"Shifted existing deadline '{ex['title']}' from {old_d} to {new_d}."
                        try:
                            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id)
                            await conversations.add_message(conn, real_cid, role="user", content=message)
                            await conversations.add_message(conn, real_cid, role="assistant", content=resp, skill_called="add_task")
                            conv_id = real_cid
                        except Exception as e:
                            logger.debug(f"Could not persist message history: {e}")
                        return {
                            "conversation_id": conv_id,
                            "response": resp,
                            "message": resp,
                            "skill_used": "add_task",
                            "success": True,
                            "data": task_record,
                            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
                        }
                    else:
                        resp = (
                            f"⚠️ A deadline named '{ex['title']}' is already scheduled for {old_d}. "
                            f"Would you like me to shift your existing deadline to {new_d}, or is this for a completely different task? "
                            f"I can also look into your schedules to find an optimal slot without clashes."
                        )
                        try:
                            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id)
                            await conversations.add_message(conn, real_cid, role="user", content=message)
                            await conversations.add_message(conn, real_cid, role="assistant", content=resp, skill_called="add_task")
                            conv_id = real_cid
                        except Exception as e:
                            logger.debug(f"Could not persist message history: {e}")
                        return {
                            "conversation_id": conv_id,
                            "response": resp,
                            "message": resp,
                            "skill_used": "add_task",
                            "success": False,
                            "data": {
                                "warning": "duplicate_name",
                                "existing_task_id": ex["id"],
                                "existing_due_date": str(old_d),
                                "proposed_due_date": str(new_d),
                            },
                            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
                        }

                project_id = None
                if project_name:
                    proj = await structured.get_or_create_project(conn, name=project_name, domain=domain)
                    project_id = proj.get("id")

                task_record = await structured.create_task(
                    conn,
                    domain=domain,
                    title=title,
                    project_id=project_id,
                    due_date=due_date,
                    status=status,
                    priority=priority,
                    notes=notes,
                    user_id=user_id,
                )
        except Exception as e:
            logger.error(f"add_task failed — database unavailable: {e}", exc_info=True)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            failure_msg = (
                f"I could not save the task '{title}' — the database is unreachable "
                f"right now. Nothing was stored. Please try again in a moment."
            )
            return {
                "conversation_id": conv_id,
                "response": failure_msg,
                "message": failure_msg,
                "skill_used": "add_task",
                "success": False,
                "error": "database_unavailable",
                "data": None,
                "routing_latency_ms": latency_ms,
            }

        # Build skill summary
        due_info = f" with due date {due_str}" if due_str else ""
        summary = f"Added task '{title}' under {domain.upper()} domain{due_info}."

        # Persist conversation & messages
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                real_cid = await conversations.get_or_create_conversation(conn, conv_id)
                await conversations.add_message(conn, real_cid, role="user", content=message)
                await conversations.add_message(conn, real_cid, role="assistant", content=summary, skill_called="add_task")
                conv_id = real_cid
        except Exception as e:
            logger.debug(f"Could not persist message history: {e}")

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "conversation_id": conv_id,
            "response": summary,
            "message": summary,
            "skill_used": "add_task",
            "data": task_record,
            "routing_latency_ms": latency_ms,
        }

    # 3. Dynamic Skill Execution via SKILL_REGISTRY
    from backend.skills import SKILL_REGISTRY, MUTATING_TOOLS

    if skill_name in MUTATING_TOOLS and skill_name != "add_task":
        gate_msg = (
            f"The action '{skill_name}' modifies data and requires approval. "
            f"Please run this request through the Agent Planner."
        )
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                real_cid = await conversations.get_or_create_conversation(conn, conv_id)
                await conversations.add_message(conn, real_cid, role="user", content=message)
                await conversations.add_message(
                    conn, real_cid, role="assistant",
                    content=gate_msg, skill_called=skill_name,
                )
                conv_id = real_cid
        except Exception as e:
            logger.debug(f"Could not persist message history: {e}")

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "conversation_id": conv_id,
            "response": gate_msg,
            "message": gate_msg,
            "skill_used": skill_name,
            "success": False,
            "error": "confirmation_required",
            "data": None,
            "routing_latency_ms": latency_ms,
        }

    if skill_name and skill_name in SKILL_REGISTRY:
        try:
            pool = await get_pool()
            handler = SKILL_REGISTRY[skill_name]
            skill_result = await handler(args or {}, pool)

            # SkillResult contract: {success, data, summary, error}
            # Accept "response" only as a legacy alias so older handlers keep working.
            if not isinstance(skill_result, dict):
                raise TypeError(
                    f"Skill '{skill_name}' returned {type(skill_result).__name__}, expected dict"
                )

            succeeded = bool(skill_result.get("success", True))
            summary = (
                skill_result.get("summary")
                or skill_result.get("response")
                or ("Action completed." if succeeded else "")
            )
            data = skill_result.get("data")

            if not succeeded:
                err = skill_result.get("error") or "unknown error"
                logger.warning("Skill '%s' reported failure: %s", skill_name, err)
                summary = summary or f"I couldn't complete that: {err}"

            try:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(
                        conn, real_cid, role="assistant",
                        content=summary, skill_called=skill_name,
                    )
                    conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist message history: {e}")

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return {
                "conversation_id": conv_id,
                "response": summary,
                "message": summary,
                "skill_used": skill_name,
                "success": succeeded,
                "error": skill_result.get("error"),
                "data": data,
                "routing_latency_ms": latency_ms,
            }
        except Exception as e:
            logger.error(f"Skill execution failed for {skill_name}: {e}", exc_info=True)
            # Do not leak raw exception text to the user.
            text_reply = (
                "I hit an internal error running that action. It has been logged — "
                "nothing was changed."
            )

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            real_cid = await conversations.get_or_create_conversation(conn, conv_id)
            await conversations.add_message(conn, real_cid, role="user", content=message)
            await conversations.add_message(conn, real_cid, role="assistant", content=text_reply, skill_called="chat")
            conv_id = real_cid
    except Exception as e:
        logger.debug(f"Could not persist message history: {e}")

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    return {
        "conversation_id": conv_id,
        "response": text_reply,
        "message": text_reply,
        "skill_used": "chat",
        "data": None,
        "routing_latency_ms": latency_ms,
    }


async def process_chat_query(
    message: str,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Canonical entry point compatible with previous service signature."""
    return await handle_message(conversation_id=conversation_id, message=message)


async def orchestrate_chat(
    message: str,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Alias for backwards compatibility with existing callers."""
    return await handle_message(conversation_id=conversation_id, message=message)
