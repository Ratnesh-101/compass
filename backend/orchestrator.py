"""
Compass — Skill Orchestrator.

Coordinates routing via Nemotron-3 Nano and execution of structured database operations.
"""

import time
import uuid
import logging
from datetime import datetime, date, timezone
from typing import Optional, Dict, Any

from backend.router import route_message
from backend.memory.db import get_pool
from backend.memory import structured, conversations
from backend.services.task_time import combine_local, extract_clock, request_timezone

logger = logging.getLogger("compass.orchestrator")
_DELETE_CANDIDATE_LIMIT = 3
_FINISHED_STATUSES = ("completed", "done", "cancelled")


def _apply_delete_status_filter(tasks: list, status_filter: Optional[str]) -> list:
    """Narrow delete candidates by a status word ("overdue" / "completed"); no-op without one."""
    if status_filter == "overdue":
        today = datetime.now(timezone.utc).date()
        return [
            t for t in tasks
            if t.get("due_date") is not None
            and t["due_date"] < today
            and t.get("status") not in _FINISHED_STATUSES
        ]
    if status_filter == "completed":
        return [t for t in tasks if t.get("status") in ("completed", "done")]
    return tasks
_ORDINAL_INDEX = {
    "1": 0, "first one": 0, "the first one": 0,
    "2": 1, "second one": 1, "the second one": 1,
    "3": 2, "third one": 2, "the third one": 2,
}


def _select_candidate(message: str, task_ids: list) -> Optional[int]:
    """Pick one candidate from a numbered/ID reply; None when the reply is unclear."""
    reply = (message or "").lower().strip().rstrip(".!?")
    idx = _ORDINAL_INDEX.get(reply)
    if idx is not None:
        if idx < len(task_ids):
            return task_ids[idx]
    if reply.isdigit() and int(reply) in task_ids:
        return int(reply)
    return None


def _disambiguation_prompt(count: int) -> str:
    """Return the clarification prompt tailored to the number of candidates."""
    if count == 1:
        return "Reply with 1, or 'Cancel'."
    if count == 2:
        return "Which one? Reply with 1 or 2, or 'Cancel'."
    return "Which one? Reply with 1, 2 or 3, or 'Cancel'."


from backend.orchestrator_helpers import (
    PRIORITY_MAP,
    STATUS_MAP,
    format_chat_response,
    parse_iso_date,
)

_parse_iso_date = parse_iso_date

# Replies that only make sense for a single-task delete / disambiguation, never for clear_schedule.
_SINGLE_TASK_REPLIES = frozenset({
    "1", "first one", "the first one", "delete the first one", "complete the first one",
})


async def _handle_message_core(
    conversation_id: Optional[str] = None,
    message: str = "",
    user_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    history: Optional[list] = None,
    memory_context: Optional[str] = None,
    persist: bool = True,
    tone: Optional[str] = None,
    include_demo: bool = False,
    conv_mode: Optional[str] = None,
    pre_routed_skill: Optional[str] = None,
    pre_routed_args: Optional[Dict[str, Any]] = None,
    target_message_id: Optional[str] = None,
    target_message_content: Optional[str] = None,
    pool: Optional[Any] = None,
) -> Dict[str, Any]:
    """Process an incoming user message through router and skill handlers."""
    start_time = time.perf_counter()
    conv_id = conversation_id or str(uuid.uuid4())
    active_pool = pool

    # Fetch recent history if conversation exists and not pre-provided
    if history is None:
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

    # Load long-term cross-session memory & active tasks if not pre-provided
    if memory_context is None:
        memory_context = ""
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                prior_messages = await conversations.get_cross_conversation_memory(
                    conn, exclude_conversation_id=conversation_id, limit=6, user_id=user_id, guest_id=guest_id
                )
                if user_id:
                    active_tasks = await conn.fetch(
                        """
                        SELECT title, domain, due_date, status, priority, duration_minutes
                        FROM tasks
                        WHERE status != 'completed' AND deleted_at IS NULL AND user_id = $1
                          AND ($2::boolean OR COALESCE(trusted_event_url,'') NOT LIKE 'compass://demo-persona/%')
                        ORDER BY due_date ASC NULLS LAST, priority DESC
                        LIMIT 8
                        """,
                        user_id,
                        bool(include_demo),
                    )
                else:
                    active_tasks = []
                recent_plans = await conn.fetch(
                    """
                    SELECT goal, status
                    FROM agent_runs
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 3
                    """,
                    user_id,
                ) if user_id else []

                sections = []
                try:
                    from backend.memory.profile import get_profile_facts
                    p_facts = await get_profile_facts(conn, user_id=user_id or "default_user")
                    if p_facts:
                        facts_str = "\n".join([f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in sorted(p_facts.items())])
                        sections.append(f"Personal Profile Facts:\n{facts_str}")
                except Exception as e:
                    logger.warning("Could not load profile facts in orchestrator (continuing gracefully): %s", e)

                try:
                    from backend.memory.parked import list_parked_thoughts
                    p_thoughts = await list_parked_thoughts(conn, user_id=user_id or "default_user", status="parked", limit=5)
                    if p_thoughts:
                        parked_str = "\n".join([f"- {t['text']}" for t in p_thoughts])
                        sections.append(f"Parked Thoughts on Shelf:\n{parked_str}")
                except Exception as e:
                    logger.warning("Could not load parked thoughts in orchestrator (continuing gracefully): %s", e)

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

    # 1. Route via Nemotron-3 Nano (bypass if already resolved upstream)
    if pre_routed_skill is not None:
        from backend.skills.registry import SKILL_REGISTRY
        allowed_tools = frozenset(SKILL_REGISTRY.keys()) | {
            "add_task", "undo", "agent",
            "pending_action_confirm", "pending_action_cancel", "chat_delete_task",
        }
        import inspect
        sig = inspect.signature(route_message)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        route_kwargs: Dict[str, Any] = {}
        if "target_message_id" in sig.parameters or has_var_kw:
            route_kwargs["target_message_id"] = target_message_id
        if "target_message_content" in sig.parameters or has_var_kw:
            route_kwargs["target_message_content"] = target_message_content
        if "pool" in sig.parameters or has_var_kw:
            route_kwargs["pool"] = active_pool
        if "user_id" in sig.parameters or has_var_kw:
            route_kwargs["user_id"] = user_id or guest_id
        if "tone" in sig.parameters or has_var_kw:
            route_kwargs["tone"] = tone

        if pre_routed_skill in allowed_tools:
            skill_name = pre_routed_skill
            args = dict(pre_routed_args) if isinstance(pre_routed_args, dict) else {}
            text_reply = None
        else:
            logger.warning("Orchestrator rejected unauthorized pre_routed_skill '%s'; falling back to route_message", pre_routed_skill)
            skill_name, args, text_reply = await route_message(
                message,
                history=history if history else None,
                memory_context=memory_context if memory_context else None,
                **route_kwargs,
            )
    else:
        import inspect
        sig = inspect.signature(route_message)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        route_kwargs: Dict[str, Any] = {}
        if "target_message_id" in sig.parameters or has_var_kw:
            route_kwargs["target_message_id"] = target_message_id
        if "target_message_content" in sig.parameters or has_var_kw:
            route_kwargs["target_message_content"] = target_message_content
        db_pool = active_pool
        if db_pool is None:
            try:
                db_pool = await get_pool()
            except Exception:
                db_pool = None

        if "pool" in sig.parameters or has_var_kw:
            route_kwargs["pool"] = db_pool
        if "user_id" in sig.parameters or has_var_kw:
            route_kwargs["user_id"] = user_id or guest_id
        if "tone" in sig.parameters or has_var_kw:
            route_kwargs["tone"] = tone

        skill_name, args, text_reply = await route_message(
            message,
            history=history if history else None,
            memory_context=memory_context if memory_context else None,
            **route_kwargs,
        )
    effective_user_id = user_id or guest_id
    if effective_user_id and isinstance(args, dict):
        args["user_id"] = effective_user_id
    if target_message_id and isinstance(args, dict):
        args["target_message_id"] = target_message_id
    if target_message_content and isinstance(args, dict):
        args["target_message_content"] = target_message_content
    if tone and isinstance(args, dict):
        args["tone"] = tone
    if isinstance(args, dict):
        args["include_demo"] = bool(include_demo)
    if conv_mode and isinstance(args, dict):
        args["conv_mode"] = conv_mode
    if memory_context and isinstance(args, dict) and "memory_context" not in args:
        args["memory_context"] = memory_context
    if message and isinstance(args, dict) and "user_message" not in args:
        args["user_message"] = message
    if history and isinstance(args, dict) and "history" not in args:
        args["history"] = history

    owner_identity = effective_user_id or "default_user"

    # 2a. Skill Execution: pending_action_confirm
    if skill_name == "pending_action_confirm":
        from backend.memory.chat_pending import (
            get_active_chat_pending_action,
            resolve_chat_pending_action,
            soft_delete_tasks,
        )
        from backend.router_helpers import ORDINAL_REPLIES
        pool = active_pool or await get_pool()
        active_action = None
        deleted: list = []
        needs_reply = ""
        intake_result = None
        if pool:
            async with pool.acquire() as conn:
                active_action = await get_active_chat_pending_action(conn, owner_identity, conv_id)
                if active_action:
                    act_type = active_action.get("action")
                    if act_type == "add_tasks":
                        from backend.services.task_intake import confirm_add_tasks
                        reply_key = (message or "").lower().strip().rstrip(".!?")
                        if reply_key in ORDINAL_REPLIES or reply_key in _SINGLE_TASK_REPLIES:
                            needs_reply = "That isn't a confirmation. Reply 'Confirm' to add all the tasks or 'Cancel'."
                        else:
                            intake_result = await confirm_add_tasks(conn, active_action, owner_identity, conv_id)
                    elif act_type in ("delete_task", "clear_schedule"):
                        normalized_reply = (message or "").lower().strip().rstrip(".!?")
                        if normalized_reply in ORDINAL_REPLIES or (
                            act_type == "clear_schedule" and normalized_reply in _SINGLE_TASK_REPLIES
                        ):
                            needs_reply = "That isn't a confirmation. Reply 'Confirm' to proceed or 'Cancel'."
                        else:
                            task_ids = active_action.get("task_ids") or []
                            async with conn.transaction():
                                claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
                                if claimed:
                                    deleted = await soft_delete_tasks(conn, task_ids, owner_identity)
                            if not claimed:
                                active_action = None
                    elif act_type == "delete_task_disambiguation":
                        task_ids = active_action.get("task_ids") or []
                        selected_id = _select_candidate(message, task_ids)
                        if selected_id is None:
                            needs_reply = _disambiguation_prompt(len(task_ids))
                        else:
                            async with conn.transaction():
                                claimed = await resolve_chat_pending_action(conn, active_action["id"], "executed")
                                if claimed:
                                    deleted = await soft_delete_tasks(conn, [selected_id], owner_identity)
                            if not claimed:
                                active_action = None

        if intake_result is not None:
            resp_msg, ret_data, success = intake_result
        elif needs_reply:
            resp_msg = needs_reply
            ret_data = None
            success = False
        elif active_action and deleted:
            if len(deleted) == 1:
                resp_msg = f"Deleted task '{deleted[0]['title']}'. You can undo this deletion within 10 minutes."
            else:
                resp_msg = f"Cleared {len(deleted)} tasks from your schedule. You can undo this deletion within 10 minutes."
            ret_data: Optional[Dict[str, Any]] = {"deleted_tasks": deleted, "can_undo": True}
            success = True
        elif active_action:
            resp_msg = "No tasks were modified."
            ret_data = None
            success = False
        else:
            resp_msg = "There are no pending actions to confirm. What would you like me to help you with?"
            ret_data = None
            success = False

        if persist and pool:
            try:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="pending_action_confirm", verifiable=False)
                    conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist pending_action_confirm history: {e}")

        return {
            "conversation_id": conv_id,
            "response": resp_msg,
            "message": resp_msg,
            "skill_used": "pending_action_confirm",
            "success": success,
            "data": ret_data,
            "verifiable": False,
            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
        }

    # 2b. Skill Execution: pending_action_cancel
    if skill_name == "pending_action_cancel":
        from backend.memory.chat_pending import (
            get_active_chat_pending_action,
            resolve_chat_pending_action,
        )
        pool = active_pool or await get_pool()
        was_pending = False
        if pool:
            async with pool.acquire() as conn:
                active_action = await get_active_chat_pending_action(conn, owner_identity, conv_id)
                if active_action:
                    was_pending = True
                    await resolve_chat_pending_action(conn, active_action["id"], "cancelled")

        resp_msg = "Action cancelled. No tasks were modified." if was_pending else "No action was pending."
        if persist and pool:
            try:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="pending_action_cancel", verifiable=False)
                    conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist pending_action_cancel history: {e}")

        return {
            "conversation_id": conv_id,
            "response": resp_msg,
            "message": resp_msg,
            "skill_used": "pending_action_cancel",
            "success": True,
            "data": {"cancelled": was_pending},
            "verifiable": False,
            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
        }

    # 2c. Skill Execution: chat_delete_task
    if skill_name == "chat_delete_task":
        from backend.memory.chat_pending import (
            create_chat_pending_action,
            search_active_tasks_for_delete,
            get_all_active_tasks_for_user,
            list_nearest_active_titles,
        )
        from backend.services.delete_target import parse_delete_target
        pool = active_pool or await get_pool()
        is_clear = bool(args.get("clear_all")) if isinstance(args, dict) else False
        del_query = (args.get("query") if isinstance(args, dict) else "") or message
        resp_msg = "I can't delete tasks right now because the database is unavailable."
        ret_data = None
        success = True

        if is_clear:
            all_active = []
            if pool:
                async with pool.acquire() as conn:
                    all_active = await get_all_active_tasks_for_user(conn, owner_identity, include_demo=include_demo)
                    if not all_active:
                        resp_msg = "You have 0 active tasks in your schedule."
                        ret_data = {"count": 0, "tasks": []}
                    else:
                        pending = await create_chat_pending_action(
                            conn,
                            action="clear_schedule",
                            task_ids=[t["id"] for t in all_active],
                            task_titles=[{"id": t["id"], "title": t["title"]} for t in all_active],
                            count=len(all_active),
                            owner_identity=owner_identity,
                            conversation_id=conv_id,
                            expires_minutes=5,
                        )
                        resp_msg = f"⚠️ Are you sure you want to clear all {len(all_active)} active tasks from your schedule? Please reply 'Confirm' or click Confirm below."
                        ret_data = {"pending_action": pending, "tasks": all_active}
        else:
            parsed_target = parse_delete_target(del_query)
            specific_query, is_generic = parsed_target.text, parsed_target.is_generic
            if pool:
                async with pool.acquire() as conn:
                    if is_generic:
                        matches = await get_all_active_tasks_for_user(conn, owner_identity, include_demo=include_demo)
                    else:
                        matches = await search_active_tasks_for_delete(
                            conn, owner_identity, specific_query, include_demo=include_demo
                        )
                        raw_query = " ".join((del_query or "").lower().split())
                        if not matches and raw_query and raw_query != specific_query:
                            # e.g. a title like "Fix deadline bug" whose generic words were stripped
                            matches = await search_active_tasks_for_delete(
                                conn, owner_identity, raw_query, include_demo=include_demo
                            )
                    matches = _apply_delete_status_filter(matches, parsed_target.status_filter)
                    if not matches:
                        if is_generic:
                            resp_msg = "You have no active tasks to delete."
                            ret_data = {"count": 0}
                        else:
                            nearest = await list_nearest_active_titles(
                                conn, owner_identity, limit=5, include_demo=include_demo
                            )
                            resp_msg = "I couldn't find an active task with that name."
                            if nearest:
                                resp_msg += " Your active tasks:\n" + "\n".join(
                                    f"{i}. '{t['title']}' (ID: {t['id']})" for i, t in enumerate(nearest, 1)
                                )
                            ret_data = {"count": 0, "nearest": nearest}
                    elif len(matches) == 1:
                        target = matches[0]
                        pending = await create_chat_pending_action(
                            conn,
                            action="delete_task",
                            task_ids=[target["id"]],
                            task_titles=[{"id": target["id"], "title": target["title"]}],
                            count=1,
                            owner_identity=owner_identity,
                            conversation_id=conv_id,
                            expires_minutes=5,
                        )
                        resp_msg = f"Are you sure you want to delete task '{target['title']}' (ID: {target['id']})? Please confirm to proceed or click Cancel."
                        ret_data = {"pending_action": pending, "task": target}
                    else:
                        total = len(matches)
                        # The numeric reply handler supports choices 1-3, so only those are offered.
                        matches = matches[:_DELETE_CANDIDATE_LIMIT]
                        pending = await create_chat_pending_action(
                            conn,
                            action="delete_task_disambiguation",
                            task_ids=[t["id"] for t in matches],
                            task_titles=[{"id": t["id"], "title": t["title"]} for t in matches],
                            count=len(matches),
                            owner_identity=owner_identity,
                            conversation_id=conv_id,
                            expires_minutes=5,
                        )
                        if is_generic:
                            lines = [f"You have {total} active tasks. Which one do you want to delete?"]
                        else:
                            lines = [f"Found {total} tasks matching '{specific_query}':"]
                        for i, m in enumerate(matches, 1):
                            lines.append(f"{i}. '{m['title']}' (ID: {m['id']})")
                        if total > len(matches):
                            lines.append(f"Showing the first {len(matches)} of {total}; tell me the task's title to narrow it down.")
                        lines.append("Please reply with the number you want to delete, or click Cancel.")
                        resp_msg = "\n".join(lines)
                        ret_data = {"pending_action": pending, "matches": matches}

        if persist and pool:
            try:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="chat_delete_task", verifiable=False)
                    conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist chat_delete_task history: {e}")

        return {
            "conversation_id": conv_id,
            "response": resp_msg,
            "message": resp_msg,
            "skill_used": "chat_delete_task",
            "success": success,
            "data": ret_data,
            "verifiable": False,
            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
        }

    # 2d. Skill Execution: undo
    if skill_name == "undo":
        from backend.memory.chat_pending import undo_soft_deleted_tasks
        restored: list = []
        found = False
        audit_id_to_undo = None
        try:
            pool = await get_pool()
            if pool:
                async with pool.acquire() as conn:
                    # 1. Prefer whichever action is most recent: a soft-delete or a logged add_task
                    latest_audit = await conn.fetchrow(
                        """
                        SELECT id, created_at
                        FROM agent_audit_log
                        WHERE lower(COALESCE(args->>'user_id', approved_by, '')) = lower($1::text)
                          AND is_reverted = FALSE
                        ORDER BY id DESC LIMIT 1
                        """,
                        owner_identity,
                    )
                    latest_delete = await conn.fetchval(
                        """
                        SELECT max(deleted_at) FROM tasks
                        WHERE (user_id = $1 OR (user_id IS NULL AND $1 IS NULL))
                          AND deleted_at IS NOT NULL
                          AND deleted_at >= now() - interval '10 minutes'
                        """,
                        owner_identity,
                    )
                    audit_is_newer = bool(
                        latest_audit and (latest_delete is None or latest_audit["created_at"] > latest_delete)
                    )
                    if not audit_is_newer:
                        restored = await undo_soft_deleted_tasks(conn, owner_identity, minutes=10)
                    if restored:
                        found = True
                        titles = [f"'{t['title']}'" for t in restored]
                        resp_msg = f"Restored {len(restored)} task(s): {', '.join(titles)}."
                        ret_data = {"restored_tasks": restored}
                    else:
                        # 2. Fall back to the caller's latest agent_audit_log action (owner-scoped)
                        row = await conn.fetchrow(
                            """
                            SELECT id
                            FROM agent_audit_log
                            WHERE lower(COALESCE(args->>'user_id', approved_by, '')) = lower($1::text)
                              AND is_reverted = FALSE
                            ORDER BY id DESC LIMIT 1
                            """,
                            owner_identity,
                        )
                        audit_id_to_undo = row["id"] if row else None
                if not restored and audit_id_to_undo is None:
                    resp_msg = "No recently deleted tasks were found within the 10-minute undo window."
                    ret_data = None
                elif not restored:
                    from backend.agent_persistence import undo_last_agent_action
                    undo_result = await undo_last_agent_action(
                        pool, audit_log_id=audit_id_to_undo, owner_id=owner_identity
                    )
                    if undo_result.get("status") == "ok":
                        found = True
                        what = (undo_result.get("reverted") or {}).get("action") or "the last change"
                        resp_msg = f"Undid: {what}."
                    else:
                        resp_msg = undo_result.get("message") or "Nothing could be undone."
                    ret_data = None
        except Exception as e:
            logger.warning(f"Undo operation failed: {e}")
            resp_msg = "Unable to process undo request right now."
            ret_data = None

        if persist:
            try:
                pool = await get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                        await conversations.add_message(conn, real_cid, role="user", content=message)
                        await conversations.add_message(conn, real_cid, role="assistant", content=resp_msg, skill_called="undo", verifiable=False)
                        conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist undo message history: {e}")

        return {
            "conversation_id": conv_id,
            "response": resp_msg,
            "message": resp_msg,
            "skill_used": "undo",
            "success": found,
            "data": ret_data,
            "verifiable": False,
            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
        }

    # 2b. Skill Execution: add_tasks_preview (a pasted list; stores a pending confirmation, writes nothing)
    if skill_name == "add_tasks_preview":
        from backend.services.task_intake import handle_intake_preview
        return await handle_intake_preview(
            message=message, conv_id=conv_id, owner_identity=owner_identity, user_id=user_id,
            guest_id=guest_id, persist=persist, active_pool=active_pool, start_time=start_time,
            items=args.get("items") if isinstance(args, dict) else None,
        )

    # 2b. Skill Execution: add_task
    if skill_name == "add_task" and args:
        from backend.services.task_intent import blocks_task_creation, has_explicit_task_phrase, title_problem
        title = str(args.get("title") or "").strip()
        if blocks_task_creation(message) or title_problem(title):
            from backend.services.task_intake import clarification_result
            return clarification_result(conv_id, start_time, message)
        if pre_routed_skill == "add_task" and not has_explicit_task_phrase(message):
            from backend.services.intent_gate import classify_task_intent
            from backend.services.task_intake import implicit_task_result
            if await classify_task_intent(message) is False:
                return implicit_task_result(conv_id, start_time, title)
        domain = args.get("domain") or "general"
        project_name = args.get("project")
        due_str = args.get("due_date")
        due_date = _parse_iso_date(due_str)
        user_tz = request_timezone.get() or "UTC"
        due_clock = extract_clock(due_str, args.get("time_str"), message) if due_date else None
        due_at = combine_local(due_date, due_clock, user_tz) if due_date and due_clock else None

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

        task_record: Optional[Dict[str, Any]] = None
        shift_existing = bool(args.get("shift_existing", False))
        allow_different_thing = bool(args.get("allow_different_thing", False))
        allow_duplicate = bool(args.get("allow_duplicate", False))
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                task_owner = user_id or guest_id
                existing_tasks = await structured.list_tasks(conn, user_id=task_owner) if task_owner else []
                exact_matches = [
                    t for t in existing_tasks
                    if t["title"].strip().lower() == title.strip().lower()
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
                        real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
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
                        "verifiable": False,
                        "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
                    }

                same_name_matches = [
                    t for t in existing_tasks
                    if t["title"].strip().lower() == title.strip().lower()
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
                            owner_id=task_owner,
                            due_date=due_date,
                            priority=priority,
                            notes=notes or ex.get("notes"),
                        )
                        resp = f"Shifted existing deadline '{ex['title']}' from {old_d} to {new_d}."
                        try:
                            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
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
                            "verifiable": False,
                            "routing_latency_ms": int((time.perf_counter() - start_time) * 1000),
                        }
                    else:
                        resp = (
                            f"⚠️ A deadline named '{ex['title']}' is already scheduled for {old_d}. "
                            f"Would you like me to shift your existing deadline to {new_d}, or is this for a completely different task? "
                            f"I can also look into your schedules to find an optimal slot without clashes."
                        )
                        try:
                            real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
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
                            "verifiable": False,
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
                    user_id=task_owner,
                    due_at=due_at,
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
                "verifiable": False,
                "routing_latency_ms": latency_ms,
            }

        # Record into agent_audit_log for undo
        try:
            pool = await get_pool()
            if pool:
                async with pool.acquire() as conn:
                    if task_record and "id" in task_record:
                        import json
                        await conn.execute(
                            """
                            INSERT INTO agent_audit_log 
                                (run_id, tool, args, affected_table, affected_id, new_state, approved_by, status, is_reverted)
                            VALUES ($1, 'add_task', $2::jsonb, 'tasks', $3, $4::jsonb, $5, 'executed', FALSE)
                            """,
                            conv_id,
                            json.dumps(args, default=str),
                            int(task_record["id"]),
                            json.dumps(task_record, default=str),
                            user_id or "default_user",
                        )
        except Exception as e:
            logger.debug(f"Audit log recording or timezone lookup failed: {e}")

        # Build skill summary echoing ONLY what user specified (no invented priority or category)
        from backend.persona import format_tool_response
        summary = format_tool_response("add_task", {
            "title": title,
            "due_date": f"{due_date.isoformat()} {due_clock:%H:%M}" if due_date and due_clock else (due_date.isoformat() if due_date else ""),
            "time_str": "",
            "timezone": user_tz,
            "roll_forward_note": args.get("roll_forward_note") or "",
        })

        # Persist conversation & messages
        if persist:
            try:
                pool = await get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                        await conversations.add_message(conn, real_cid, role="user", content=message)
                        await conversations.add_message(conn, real_cid, role="assistant", content=summary, skill_called="add_task", verifiable=False)
                        conv_id = real_cid
            except Exception as e:
                logger.debug(f"Could not persist message history: {e}")

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "conversation_id": conv_id,
            "response": summary,
            "message": summary,
            "skill_used": "add_task",
            "success": True,
            "data": task_record,
            "verifiable": False,
            "routing_latency_ms": latency_ms,
        }

    # 2c. Skill Execution: agent (Multi-step autonomous reasoning & scheduling)
    if skill_name == "agent":
        from backend.agent import run_agent
        pool = await get_pool()
        goal = (args.get("goal") if isinstance(args, dict) else None) or message
        thoughts = []
        synth_text = ""
        agent_succeeded = True
        err_msg = None
        try:
            async for step in run_agent(
                goal=goal,
                pool=pool,
                user_id=user_id,
                conversation_id=conv_id,
                tone=tone,
            ):
                if step.type == "think":
                    if not any("Understanding" in m for m in thoughts):
                        thoughts.append("Thinking: Understanding your request")
                elif step.type == "act":
                    tool = (step.tool_name or "").lower()
                    if any(k in tool for k in ("task", "deadline", "coursework", "hackathon")):
                        m = "Retrieving relevant tasks & deadlines"
                    elif any(k in tool for k in ("schedule", "calendar", "feasibility", "conflict")):
                        m = "Checking upcoming deadlines & schedule"
                    elif "web" in tool:
                        m = "Searching reference documentation"
                    elif any(k in tool for k in ("note", "code", "context", "project")):
                        m = "Reviewing relevant context"
                    else:
                        clean_name = tool.replace("_", " ").title()
                        m = f"Executing {clean_name}" if clean_name else "Executing action"
                    if not thoughts or thoughts[-1] != m:
                        thoughts.append(m)
                elif step.type == "critic":
                    m = "Verifying plan constraints"
                    if not thoughts or thoughts[-1] != m:
                        thoughts.append(m)
                elif step.type == "synthesize":
                    synth_text = step.content
                    m = "Preparing your response"
                    if not thoughts or thoughts[-1] != m:
                        thoughts.append(m)
                elif step.type == "done":
                    m = "Analysis complete"
                    if not thoughts or thoughts[-1] != m:
                        thoughts.append(m)
                elif step.type == "error":
                    agent_succeeded = False
                    err_msg = step.content
        except Exception as e:
            logger.error("Error executing agent: %s", e, exc_info=True)
            agent_succeeded = False
            err_msg = str(e)

        reply_content = synth_text or (f"I encountered an error while processing your request: {err_msg}" if err_msg else "")
        if not reply_content:
            agent_succeeded = False
            reply_content = "Unable to complete request. Please retry."

        if persist and pool:
            try:
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(conn, real_cid, role="assistant", content=reply_content, skill_called="agent", verifiable=False)
                    conv_id = real_cid
            except Exception as e:
                logger.debug("Could not persist agent conversation: %s", e)

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "conversation_id": conv_id,
            "response": reply_content,
            "message": reply_content,
            "skill_used": "agent",
            "success": agent_succeeded,
            "error": err_msg if not agent_succeeded else None,
            "data": {
                "thought": "\n\n".join(thoughts) if thoughts else None,
                "can_retry": not agent_succeeded,
            },
            "verifiable": False,
            "routing_latency_ms": latency_ms,
        }

    # 3. Dynamic Skill Execution via SKILL_REGISTRY
    from backend.skills import SKILL_REGISTRY, MUTATING_TOOLS

    if skill_name in MUTATING_TOOLS and skill_name != "add_task":
        gate_msg = (
            f"The action '{skill_name}' modifies data and requires approval. "
            f"Please run this request through the Agent Planner."
        )
        if persist:
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    real_cid = await conversations.get_or_create_conversation(conn, conv_id, user_id=user_id, guest_id=guest_id)
                    await conversations.add_message(conn, real_cid, role="user", content=message)
                    await conversations.add_message(
                        conn, real_cid, role="assistant",
                        content=gate_msg, skill_called=skill_name, verifiable=False,
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
            "verifiable": False,
            "routing_latency_ms": latency_ms,
        }

    if skill_name and skill_name in SKILL_REGISTRY:
        try:
            pool = active_pool or await get_pool()
            handler = SKILL_REGISTRY[skill_name]
            skill_args = dict(args or {})
            if tone and "tone" not in skill_args:
                skill_args["tone"] = tone
            skill_result = await handler(skill_args, pool)

            # SkillResult contract: {success, data, summary, error}
            # Accept "response" only as a legacy alias so older handlers keep working.
            if not isinstance(skill_result, dict):
                raise TypeError(
                    f"Skill '{skill_name}' returned {type(skill_result).__name__}, expected dict"
                )

            succeeded = bool(skill_result.get("success", True))
            summary = (
                skill_result.get("response")
                or skill_result.get("summary")
                or ("Action completed." if succeeded else "")
            )
            data = skill_result.get("data")

            if not succeeded:
                err = skill_result.get("error") or "unknown error"
                logger.warning("Skill '%s' reported failure: %s", skill_name, err)
                summary = summary or f"I couldn't complete that: {err}"

            is_verifiable = bool(
                skill_name in ("verify_with_tavily", "web_search", "search_web")
                or (isinstance(data, dict) and data.get("verifiable"))
            )

            if persist:
                try:
                    async with pool.acquire() as conn:
                        real_cid = await conversations.get_or_create_conversation(
                            conn, conv_id, user_id=user_id, guest_id=guest_id
                        )
                        await conversations.add_message(conn, real_cid, role="user", content=message)
                        evidence_to_save = data.get("evidence") if isinstance(data, dict) else None
                        await conversations.add_message(
                            conn, real_cid, role="assistant",
                            content=summary, skill_called=skill_name,
                            evidence=evidence_to_save,
                            verifiable=is_verifiable,
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
                "verifiable": is_verifiable,
                "routing_latency_ms": latency_ms,
            }
        except Exception as e:
            logger.error(f"Skill execution failed for {skill_name}: {e}", exc_info=True)
            # Do not leak raw exception text to the user.
            text_reply = (
                "I hit an internal error running that action. It has been logged — "
                "nothing was changed."
            )

    return await format_chat_response(
        conv_id=conv_id,
        message=message,
        text_reply=text_reply,
        user_id=user_id,
        guest_id=guest_id,
        persist=persist,
        start_time=start_time,
        verifiable=False,
        tone=tone,
    )


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


async def handle_message(*args: Any, request_id: Optional[str] = None, tz: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    """Process one chat turn in the user's timezone; a repeated request_id replays instead of re-running."""
    from backend.services.chat_idempotency import run_chat_request
    return await run_chat_request(_handle_message_core, args, kwargs, request_id=request_id, tz=tz)
