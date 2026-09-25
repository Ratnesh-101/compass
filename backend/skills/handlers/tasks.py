"""
Compass — Task and Project Management Skill Handlers.
"""

from typing import Any, Dict, List
import logging
from datetime import datetime, date, timedelta

from backend.skills.registry import register_skill

logger = logging.getLogger("compass.skills.tasks")


@register_skill("query_tasks")
async def handle_query_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query tasks table via structured.list_tasks and format summary."""
    from backend.memory import structured
    domain = args.get("domain")
    status = args.get("status")
    user_id = args.get("user_id")

    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain=domain, status=status, user_id=user_id)

    count = len(tasks)
    d_str = f" in {domain.upper()}" if domain else ""
    s_str = f" with status '{status}'" if status else ""
    if tasks:
        task_details = [
            f"'{t['title']}' (due: {t.get('due_date') or 'no due date'}, status: {t.get('status', 'open')})"
            for t in tasks[:5]
        ]
        summary = f"Found {count} task(s){d_str}{s_str}: {'; '.join(task_details)}."
    else:
        summary = f"Found {count} task(s){d_str}{s_str}."
    return {
        "response": summary,
        "data": tasks,
    }


@register_skill("query_coursework_tasks")
async def handle_query_coursework_tasks(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Query coursework tasks such as CS 61C labs, reports, and homework."""
    from backend.memory import structured
    status = args.get("status")
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain="coursework", status=status)
    count = len(tasks)
    summary = f"📚 Coursework: Found {count} task(s) including RISC-V reports and Logisim labs."
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


@register_skill("get_hackathon_deadlines")
async def handle_get_hackathon_deadlines(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Retrieve urgent hackathon deliverables and demo benchmark deadlines."""
    from backend.memory import structured
    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, domain="hackathon")
    count = len(tasks)
    summary = f"🚀 Hackathon: {count} active deliverables for Nebius Token Factory benchmark."
    return {"response": summary, "data": {"tasks": tasks, "count": count}}


@register_skill("add_task")
async def handle_add_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Add a new task via structured.create_task."""
    from backend.memory import structured

    title = args.get("title", "Untitled Task")
    domain = args.get("domain", "general")
    if domain not in {"hackathon", "coursework", "code", "general"}:
        domain = "general"

    project_name = args.get("project")
    due_str = args.get("due_date")
    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(str(due_str)[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    priority = args.get("priority", "medium")
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"

    status = args.get("status", "open")
    if status not in {"open", "in_progress", "done", "overdue"}:
        status = "open"

    notes = args.get("notes")
    shift_existing = bool(args.get("shift_existing", False))
    allow_different_thing = bool(args.get("allow_different_thing", False))
    allow_duplicate = bool(args.get("allow_duplicate", False))

    try:
        user_id = args.get("user_id")
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
                return {
                    "response": (
                        f"⚠️ A deadline with the exact same name '{ex['title']}' and due date ({d_str}) "
                        f"already exists in your schedule. You cannot add the exact same deadline multiple times. "
                        f"I can inspect your schedules to see when you have free slots or help you rebalance your tasks."
                    ),
                    "data": {
                        "error": "duplicate_exact_deadline",
                        "existing_task_id": ex["id"],
                        "title": ex["title"],
                        "due_date": str(d_str),
                    },
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
                    updated = await structured.update_task(
                        conn,
                        ex["id"],
                        due_date=due_date,
                        priority=priority,
                        notes=notes or ex.get("notes"),
                    )
                    return {
                        "response": f"Shifted existing deadline '{ex['title']}' from {old_d} to {new_d}.",
                        "data": updated,
                    }
                else:
                    return {
                        "response": (
                            f"⚠️ A deadline with the name '{ex['title']}' already exists, scheduled for {old_d}. "
                            f"Would you like me to shift your existing deadline to {new_d}, or is this for a completely different thing? "
                            f"I can also look into your schedules to find an optimal slot without clashes."
                        ),
                        "data": {
                            "warning": "duplicate_name",
                            "existing_task_id": ex["id"],
                            "existing_due_date": str(old_d),
                            "proposed_due_date": str(new_d),
                            "action_required": "confirm_shift_or_different",
                        },
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
        return {
            "response": f"Added task #{task_record.get('id')}: '{title}' in {domain}.",
            "data": task_record,
        }
    except Exception as e:
        logger.warning(f"Failed to add task: {e}")
        return {"response": f"Failed to add task: {e}", "data": {"error": str(e)}}


@register_skill("update_task_status")
async def handle_update_task_status(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Update the status of an existing task."""
    from backend.memory import structured
    task_id = args.get("task_id")
    status = args.get("status", "open")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    try:
        async with pool.acquire() as conn:
            updated = await structured.update_task(conn, int(task_id), status=status)
        if updated:
            return {
                "response": f"Updated task #{task_id} status to '{status}'.",
                "data": updated,
            }
        return {"response": f"Task #{task_id} not found.", "data": {}}
    except Exception as e:
        return {"response": f"Failed to update task status: {e}", "data": {"error": str(e)}}


@register_skill("edit_task")
async def handle_edit_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Edit an existing task's title, due date, priority, or notes."""
    from backend.memory import structured
    task_id = args.get("task_id")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    update_fields: Dict[str, Any] = {}
    if "title" in args:
        update_fields["title"] = args["title"]
    if "due_date" in args:
        try:
            update_fields["due_date"] = datetime.strptime(args["due_date"], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return {"response": f"Invalid date format: {args['due_date']}. Use YYYY-MM-DD.", "data": {}}
    if "priority" in args:
        update_fields["priority"] = args["priority"]
    if "notes" in args:
        update_fields["notes"] = args["notes"]

    if not update_fields:
        return {"response": "No fields to update. Provide title, due_date, priority, or notes.", "data": {}}

    try:
        async with pool.acquire() as conn:
            updated = await structured.update_task(conn, int(task_id), **update_fields)
        if updated:
            fields_str = ", ".join(f"{k}={v}" for k, v in update_fields.items())
            return {
                "response": f"Updated task #{task_id}: {fields_str}.",
                "data": updated,
            }
        return {"response": f"Task #{task_id} not found.", "data": {}}
    except Exception as e:
        return {"response": f"Failed to edit task: {e}", "data": {"error": str(e)}}


@register_skill("delete_task")
async def handle_delete_task(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Delete a task by ID."""
    from backend.memory import structured
    task_id = args.get("task_id")

    if not task_id:
        return {"response": "Missing task_id.", "data": {}}

    try:
        async with pool.acquire() as conn:
            deleted = await structured.delete_task(conn, int(task_id))
        if deleted:
            return {"response": f"Deleted task #{task_id}.", "data": {"deleted": True}}
        return {"response": f"Task #{task_id} not found.", "data": {"deleted": False}}
    except Exception as e:
        return {"response": f"Failed to delete task: {e}", "data": {"error": str(e)}}


@register_skill("list_projects")
async def handle_list_projects(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """List all tracked projects via structured.list_projects."""
    from backend.memory import structured
    domain = args.get("domain")
    async with pool.acquire() as conn:
        projects = await structured.list_projects(conn)
    if domain:
        projects = [p for p in projects if p.get("domain") == domain]
    p_names = [f"'{p['name']}' ({p.get('domain', 'general')})" for p in projects]
    summary = f"Found {len(projects)} tracked project(s): {', '.join(p_names)}." if projects else "No tracked projects found."
    return {
        "response": summary,
        "data": {"projects": projects, "count": len(projects)},
    }


@register_skill("detect_deadline_conflicts")
async def handle_detect_deadline_conflicts(args: Dict[str, Any], pool: Any) -> Dict[str, Any]:
    """Scan active tasks for conflicting deadlines across domains within the next N days."""
    from backend.memory import structured

    days = int(args.get("days_ahead") or 7)
    today = date.today()
    cutoff = today + timedelta(days=days)

    async with pool.acquire() as conn:
        tasks = await structured.list_tasks(conn, status="open")

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        d = t.get("due_date")
        if d:
            d_str = str(d)[:10]
            try:
                task_date = date.fromisoformat(d_str)
                if today <= task_date <= cutoff:
                    by_date.setdefault(d_str, []).append(t)
            except Exception:
                pass

    conflicts: List[Dict[str, Any]] = []
    for d_str, day_tasks in sorted(by_date.items()):
        domains = {t.get("domain", "general") for t in day_tasks}
        priorities = {t.get("priority", "medium") for t in day_tasks}
        if len(day_tasks) > 1 or ("urgent" in priorities and "hackathon" in domains and "coursework" in domains):
            is_critical = ("hackathon" in domains and "coursework" in domains) or ("urgent" in priorities)
            conflicts.append({
                "date": d_str,
                "task_count": len(day_tasks),
                "severity": "critical" if is_critical else "moderate",
                "domains": list(domains),
                "tasks": [
                    {"id": t["id"], "title": t["title"], "domain": t.get("domain"), "priority": t.get("priority")}
                    for t in day_tasks
                ],
                "recommendation": (
                    f"Reschedule non-urgent tasks on {d_str} to avoid clash between {', '.join(domains)}."
                    if is_critical
                    else f"Review task pacing on {d_str} to prevent bottleneck."
                )
            })

    if conflicts:
        top_domains = [str(d) for d in (conflicts[0].get("domains") or [])]
        summary = (
            f"⚠️ Detected {len(conflicts)} deadline conflict cluster(s) within the next {days} days. "
            f"Most critical: {conflicts[0]['date']} with {conflicts[0]['task_count']} tasks across {', '.join(top_domains)}."
        )
    else:
        summary = f"✅ No critical deadline conflicts detected across domains in the next {days} days."

    return {
        "response": summary,
        "data": {
            "conflicts_count": len(conflicts),
            "conflicts": conflicts,
            "scanned_tasks_count": len(tasks),
            "days_ahead": days,
        },
    }
