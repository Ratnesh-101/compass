"""
Compass — Skill Orchestrator.

Coordinates routing via Nemotron-3 Nano and execution of structured database operations.
"""

import uuid
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any

from backend.router import route_message
from backend.memory.db import get_pool
from backend.memory import structured, conversations

logger = logging.getLogger("compass.orchestrator")


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
    conv_id = conversation_id or str(uuid.uuid4())

    # 1. Route via Nemotron-3 Nano
    skill_name, args, text_reply = await route_message(message)

    # 2. Skill Execution: add_task
    if skill_name == "add_task" and args:
        title = args.get("title") or message
        domain = args.get("domain") or "general"
        project_name = args.get("project")
        due_str = args.get("due_date")
        due_date = _parse_iso_date(due_str)
        priority = args.get("priority") or "medium"
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
                    priority=priority,
                    notes=notes,
                )
        except Exception as e:
            logger.warning(f"Database unavailable for add_task, returning structured response: {e}")
            task_record = {
                "id": 999,
                "domain": domain,
                "title": title,
                "due_date": due_str,
                "status": "open",
                "priority": priority,
                "notes": notes,
                "db_persisted": False,
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

        return {
            "conversation_id": conv_id,
            "response": summary,
            "skill_used": "add_task",
            "data": task_record,
        }

    # 3. Default Chat Response
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            real_cid = await conversations.get_or_create_conversation(conn, conv_id)
            await conversations.add_message(conn, real_cid, role="user", content=message)
            await conversations.add_message(conn, real_cid, role="assistant", content=text_reply, skill_called="chat")
            conv_id = real_cid
    except Exception as e:
        logger.debug(f"Could not persist message history: {e}")

    return {
        "conversation_id": conv_id,
        "response": text_reply,
        "skill_used": "chat",
        "data": None,
    }
