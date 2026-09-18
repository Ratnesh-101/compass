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
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


async def handle_message(
    conversation_id: Optional[str],
    message: str,
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
        except Exception as e:
            logger.debug(f"Could not load conversation history: {e}")

    # 1. Route via Nemotron-3 Nano
    skill_name, args, text_reply = await route_message(message, history=history if history else None)

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
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
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
    from backend.skills import SKILL_REGISTRY
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
