"""
Compass — Conversational AI Orchestrator (Nebius / Nemotron).

Runs a single-stage conversational pipeline:
  1. Fetch recent task context from DB (so the AI knows what's scheduled)
  2. Fetch recent conversation history (multi-turn memory)
  3. Send to Nebius (Nemotron model) with a natural assistant persona
  4. Persist the conversation turn to DB
  5. Return the response

The assistant can handle:
  - Normal casual conversation ("hey, how's it going?")
  - Scheduling / task questions ("what do I have due this week?")
  - Adding tasks ("remind me to submit my report by Thursday")
  - Any other question — it just talks normally

No hardcoded demo scripts. No forced domain categorization.
"""

import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from openai import OpenAI

from backend.config import get_settings
from backend.services.usage import record_usage

logger = logging.getLogger("compass.services.orchestrator")
settings = get_settings()


def _get_nebius_client() -> OpenAI:
    return OpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
        timeout=15.0,
    )


def _build_system_prompt(task_context: str) -> str:
    """Build the system prompt with optional task context injected."""
    now_str = datetime.now(timezone.utc).strftime("%A, %B %d %Y, %H:%M UTC")

    base = (
        "You are Compass, a personal AI assistant. You're friendly, helpful, and conversational — "
        "like a smart friend who also happens to keep track of your schedule and tasks. "
        "You can talk about anything: give advice, answer questions, have a normal chat. "
        "You also help with scheduling, deadlines, and task management. "
        f"Current time: {now_str}.\n\n"
    )

    if task_context:
        base += (
            "Here are the user's currently tracked tasks and upcoming deadlines "
            "(use this to answer scheduling questions naturally):\n"
            f"{task_context}\n\n"
        )
    else:
        base += (
            "The user has no tasks tracked yet. If they want to add one, just ask for the details.\n\n"
        )

    base += (
        "Guidelines:\n"
        "- Be conversational and warm. Don't be robotic or overly formal.\n"
        "- If the user asks about tasks/deadlines, use the task context above to answer specifically.\n"
        "- If the user wants to add/schedule something, extract the details and confirm clearly.\n"
        "- If the user is just chatting, just chat — don't force everything into task-management.\n"
        "- Keep responses concise unless the user asks for detail.\n"
        "- Use markdown sparingly — only when it genuinely helps readability."
    )

    return base


async def _fetch_task_context() -> str:
    """Fetch open tasks from DB and format them as a readable context string."""
    try:
        from backend.database import get_pool
        from backend.memory import structured

        pool = await get_pool()
        async with pool.acquire() as conn:
            tasks = await structured.list_tasks(conn, status="open")

        if not tasks:
            return ""

        lines = []
        for t in tasks[:10]:  # Cap at 10 to avoid flooding the prompt
            title = t.get("title", "Untitled")
            domain = t.get("domain", "general").upper()
            due = t.get("due_date")
            due_str = f", due {due}" if due else ""
            proj = t.get("project", {})
            proj_name = f" [{proj.get('name', '')}]" if proj and proj.get("name") else ""
            lines.append(f"• [{domain}]{proj_name} {title}{due_str}")

        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"Could not fetch task context: {e}")
        return ""


async def _fetch_conversation_history(conversation_id: str) -> List[Dict[str, str]]:
    """Fetch recent messages for this conversation from DB."""
    try:
        from backend.database import get_pool
        from backend.memory import conversations

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conversations.get_recent_messages(conn, conversation_id, limit=10)

        history = []
        for row in rows:
            role = row.get("role", "user")
            content = row.get("content", "")
            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content})

        return history
    except Exception as e:
        logger.debug(f"Could not fetch conversation history: {e}")
        return []


async def _persist_turn(conversation_id: str, user_message: str, assistant_reply: str) -> str:
    """Persist the conversation turn to DB. Returns the real conversation_id."""
    try:
        from backend.database import get_pool
        from backend.memory import conversations

        pool = await get_pool()
        async with pool.acquire() as conn:
            real_cid = await conversations.get_or_create_conversation(conn, conversation_id)
            await conversations.add_message(conn, real_cid, role="user", content=user_message)
            await conversations.add_message(conn, real_cid, role="assistant", content=assistant_reply)
            return real_cid
    except Exception as e:
        logger.debug(f"Could not persist conversation turn: {e}")
        return conversation_id


async def process_chat_query(
    message: str,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point for the frontend /api/chat endpoint.

    Runs:
      1. Fetch task context from DB
      2. Fetch conversation history
      3. Call Nebius (Nemotron) with natural system prompt + history
      4. Persist turn to DB
      5. Return response
    """
    conv_id = conversation_id or str(uuid.uuid4())
    start_time = time.perf_counter()

    # -----------------------------------------------------------------------
    # Step 1: Gather context (tasks + conversation history) in parallel
    # -----------------------------------------------------------------------
    task_context = await _fetch_task_context()
    history = await _fetch_conversation_history(conv_id)

    # -----------------------------------------------------------------------
    # Step 2: Build messages for Nebius
    # -----------------------------------------------------------------------
    system_prompt = _build_system_prompt(task_context)
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

    # Inject recent history (last N turns before this message)
    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": message})

    # -----------------------------------------------------------------------
    # Step 3: Call Nebius
    # -----------------------------------------------------------------------
    response_text = ""
    if settings.NEBIUS_API_KEY:
        try:
            client = _get_nebius_client()
            result = client.chat.completions.create(
                model=settings.ROUTER_MODEL,  # Nemotron-3 Nano — fast, good for chat
                messages=messages,
                max_tokens=512,
                temperature=0.7,
            )
            usage = getattr(result, "usage", None)
            p_tok = usage.prompt_tokens if usage else len(message.split()) * 3
            c_tok = usage.completion_tokens if usage else 80
            record_usage(settings.ROUTER_MODEL, p_tok, c_tok)

            response_text = result.choices[0].message.content or ""
        except Exception as e:
            logger.warning(f"Nebius chat call failed: {e}")

    # -----------------------------------------------------------------------
    # Step 4: Fallback if Nebius is unavailable
    # -----------------------------------------------------------------------
    if not response_text:
        msg_lower = message.lower()
        if any(w in msg_lower for w in ["task", "deadline", "due", "schedule", "remind"]):
            if task_context:
                response_text = f"Here's what I have tracked for you:\n\n{task_context}"
            else:
                response_text = "You don't have any tasks tracked yet. Want to add one? Just tell me what it is and when it's due."
        else:
            response_text = (
                "I'm having a bit of trouble connecting right now. "
                "Try again in a moment — I'll be back shortly!"
            )

    # -----------------------------------------------------------------------
    # Step 5: Persist conversation turn
    # -----------------------------------------------------------------------
    latency_ms = int((time.perf_counter() - start_time) * 1000)
    conv_id = await _persist_turn(conv_id, message, response_text)

    return {
        "response": response_text,
        "message": response_text,
        "conversation_id": conv_id,
        "skill_used": "chat",
        "routing_latency_ms": latency_ms,
    }


async def orchestrate_chat(message: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
    """Alias for backwards compatibility with existing callers."""
    return await process_chat_query(message=message, conversation_id=conversation_id)
