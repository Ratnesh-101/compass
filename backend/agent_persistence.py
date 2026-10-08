"""
Compass Agent — Database Persistence and Undo Operations.
Handles agent_runs state persistence, agent_audit_log, concurrency tracking, and action rollback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from backend.agent_types import AgentStep

logger = logging.getLogger("compass.agent_persistence")

MAX_CONCURRENT_AGENT_RUNS = 3


async def save_agent_run(
    pool: Any,
    run_id: str,
    goal: str,
    status: str,
    accumulated_steps: List[AgentStep],
    messages: List[Dict[str, Any]],
    pending_actions: List[Dict[str, Any]],
    conversation_id: Optional[str] = None,
) -> None:
    """Persist agent run state into agent_runs table."""
    try:
        steps_json = json.dumps([asdict(s) for s in accumulated_steps], default=str)
        messages_json = json.dumps(messages, default=str)
        pending_json = json.dumps(pending_actions, default=str)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_runs (id, goal, status, accumulated_steps, messages, pending_actions, conversation_id)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    accumulated_steps = EXCLUDED.accumulated_steps,
                    messages = EXCLUDED.messages,
                    pending_actions = EXCLUDED.pending_actions,
                    conversation_id = COALESCE(EXCLUDED.conversation_id, agent_runs.conversation_id),
                    updated_at = now()
                """,
                run_id,
                goal,
                status,
                steps_json,
                messages_json,
                pending_json,
                conversation_id,
            )
    except Exception as e:
        logger.warning(f"Failed to save agent run {run_id}: {e}")


async def get_agent_run(pool: Any, run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve an agent run by ID from agent_runs table."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM agent_runs WHERE id = $1", run_id)
            if not row:
                return None
            return {
                "id": row["id"],
                "goal": row["goal"],
                "status": row["status"],
                "conversation_id": row["conversation_id"] if "conversation_id" in row else None,
                "accumulated_steps": json.loads(row["accumulated_steps"]) if isinstance(row["accumulated_steps"], str) else row["accumulated_steps"],
                "messages": json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"],
                "pending_actions": json.loads(row["pending_actions"]) if isinstance(row["pending_actions"], str) else row["pending_actions"],
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            }
    except Exception as e:
        logger.warning(f"Failed to get agent run {run_id}: {e}")
        return None


async def record_audit_log(
    pool: Any,
    tool: str,
    args: Dict[str, Any],
    run_id: Optional[str] = None,
    affected_table: str = "tasks",
    affected_id: Optional[int] = None,
    previous_state: Optional[Dict[str, Any]] = None,
    new_state: Optional[Dict[str, Any]] = None,
    approved_by: str = "user",
) -> int:
    """Record an agent-executed mutation into agent_audit_log."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agent_audit_log
                (run_id, tool, args, affected_table, affected_id, previous_state, new_state, approved_by, status)
            VALUES
                ($1, $2, $3::jsonb, $4, $5, $6::jsonb, $7::jsonb, $8, 'executed')
            RETURNING id
            """,
            run_id,
            tool,
            json.dumps(args, default=str),
            affected_table,
            affected_id,
            json.dumps(previous_state, default=str) if previous_state is not None else None,
            json.dumps(new_state, default=str) if new_state is not None else None,
            approved_by,
        )
        return row["id"]


async def count_active_agent_runs(pool: Any, timeout_minutes: int = 5) -> int:
    """Count currently active or paused agent runs updated within the last timeout_minutes."""
    if not pool:
        return 0
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COUNT(*) FROM agent_runs 
            WHERE status IN ('running', 'paused')
              AND updated_at >= now() - ($1 || ' minutes')::interval
            """,
            str(timeout_minutes)
        )
        return int(val or 0)


async def get_critique_stats(pool: Any) -> Dict[str, Any]:
    """Calculate real critique effectiveness statistics from persisted agent runs."""
    if not pool:
        return {
            "total_runs_analyzed": 0,
            "runs_with_critique": 0,
            "critique_issues_flagged": 0,
            "critique_effectiveness_rate": 0.0,
            "recent_critique_evaluations": [],
        }
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, goal, accumulated_steps, status, created_at FROM agent_runs ORDER BY created_at DESC LIMIT 50"
        )
    total_runs = len(rows)
    runs_with_critique = 0
    issues_flagged = 0
    recent_evals: List[Dict[str, Any]] = []

    for r in rows:
        steps_raw = (
            r.get("accumulated_steps")
            if hasattr(r, "get")
            else (r["accumulated_steps"] if "accumulated_steps" in r else "[]")
        ) or "[]"
        try:
            steps_list = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
        except Exception:
            steps_list = []

        for s in steps_list:
            if s.get("type") == "critic":
                runs_with_critique += 1
                content = s.get("content", "")
                is_flagged = not content.strip().startswith("APPROVED") or any(
                    w in content.upper() for w in ["REVISE", "ISSUE", "CONFLICT", "DECLINED", "REJECT"]
                )
                if is_flagged:
                    issues_flagged += 1
                if len(recent_evals) < 10:
                    r_id = r.get("id") if hasattr(r, "get") else r["id"]
                    r_goal = r.get("goal") if hasattr(r, "get") else r["goal"]
                    r_created = r.get("created_at") if hasattr(r, "get") else r["created_at"]
                    recent_evals.append({
                        "run_id": r_id,
                        "goal": r_goal,
                        "critique_summary": content[:150],
                        "flagged_issue": is_flagged,
                        "created_at": r_created.isoformat() if hasattr(r_created, "isoformat") else str(r_created),
                    })
                break

    rate = round((issues_flagged / runs_with_critique * 100), 1) if runs_with_critique > 0 else 0.0
    return {
        "total_runs_analyzed": total_runs,
        "runs_with_critique": runs_with_critique,
        "critique_issues_flagged": issues_flagged,
        "critique_effectiveness_rate": rate,
        "recent_critique_evaluations": recent_evals,
    }


async def undo_last_agent_action(
    pool: Any,
    run_id: Optional[str] = None,
    audit_log_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Revert an agent-executed mutation using agent_audit_log."""
    async with pool.acquire() as conn:
        if audit_log_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM agent_audit_log WHERE id = $1",
                audit_log_id,
            )
            if row and (row.get("is_reverted") if hasattr(row, "get") else row["is_reverted"]):
                return {"status": "error", "message": f"Action #{audit_log_id} has already been reverted."}
        elif run_id:
            row = await conn.fetchrow(
                "SELECT * FROM agent_audit_log WHERE run_id = $1 AND is_reverted = FALSE ORDER BY id DESC LIMIT 1",
                run_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM agent_audit_log WHERE is_reverted = FALSE ORDER BY id DESC LIMIT 1"
            )

        if not row:
            return {"status": "error", "message": "No agent actions found to undo."}

        audit_id = row["id"]
        tool = row["tool"]
        affected_id = row["affected_id"]
        prev_state = json.loads(row["previous_state"]) if row["previous_state"] else None

        reverted_action = {"tool": tool, "affected_id": affected_id, "audit_log_id": audit_id}

        if tool == "add_task" and affected_id:
            await conn.execute("DELETE FROM tasks WHERE id = $1", affected_id)
            reverted_action["action"] = f"Deleted added task #{affected_id}"

        elif tool in ("edit_task", "update_task_status") and affected_id and prev_state:
            due_date = prev_state.get("due_date")
            if due_date and isinstance(due_date, str):
                try:
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                except Exception:
                    pass

            await conn.execute(
                """
                UPDATE tasks
                SET title = $2, due_date = $3, priority = $4, status = $5, notes = $6
                WHERE id = $1
                """,
                affected_id,
                prev_state.get("title"),
                due_date,
                prev_state.get("priority", "medium"),
                prev_state.get("status", "open"),
                prev_state.get("notes"),
            )
            reverted_action["action"] = f"Restored task #{affected_id} to previous state"

        elif tool == "delete_task" and prev_state:
            due_date = prev_state.get("due_date")
            if due_date and isinstance(due_date, str):
                try:
                    due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                except Exception:
                    pass

            inserted = await conn.fetchrow(
                """
                INSERT INTO tasks (id, domain, project_id, title, due_date, status, priority, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    domain = EXCLUDED.domain,
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    notes = EXCLUDED.notes
                RETURNING id
                """,
                affected_id,
                prev_state.get("domain", "general"),
                prev_state.get("project_id"),
                prev_state.get("title"),
                due_date,
                prev_state.get("status", "open"),
                prev_state.get("priority", "medium"),
                prev_state.get("notes"),
            )
            if inserted and not isinstance(inserted, (str, bytes)):
                try:
                    restored_id = cast(Any, inserted)["id"]
                except Exception:
                    restored_id = affected_id
            else:
                restored_id = affected_id
            reverted_action["action"] = f"Restored deleted task #{restored_id}"

        elif tool in ("log_code_snippet", "log_code_context") and affected_id:
            await conn.execute("DELETE FROM memory_chunks WHERE id = $1", affected_id)
            reverted_action["action"] = f"Deleted logged memory chunk #{affected_id}"

        elif tool == "ingest_url":
            args_obj = json.loads(row["args"]) if isinstance(row["args"], str) else (row["args"] or {})
            target_url = args_obj.get("url")
            audit_ts = row.get("created_at")
            if target_url and audit_ts:
                await conn.execute(
                    "DELETE FROM memory_chunks WHERE source = $1 AND created_at >= ($2::timestamptz - interval '2 minutes')",
                    target_url,
                    audit_ts,
                )
                reverted_action["action"] = f"Deleted ingested memory chunks for {target_url}"
            elif target_url:
                await conn.execute("DELETE FROM memory_chunks WHERE source = $1", target_url)
                reverted_action["action"] = f"Deleted ingested memory chunks for {target_url}"
            elif affected_id:
                await conn.execute("DELETE FROM memory_chunks WHERE id = $1", affected_id)
                reverted_action["action"] = f"Deleted ingested memory chunk #{affected_id}"
            else:
                reverted_action["action"] = "Reverted ingested URL memory"

        await conn.execute("UPDATE agent_audit_log SET is_reverted = TRUE WHERE id = $1", audit_id)

        return {
            "status": "ok",
            "message": f"Successfully reverted agent action #{audit_id} ({tool})",
            "reverted": reverted_action,
        }
