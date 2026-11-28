"""Keep the Timeline tasks created for an application in step with the application itself.

- Applied (SUBMITTED): the "Apply:" task is completed and one "Follow up:" task is created, due 14 days after
  the applied date. The follow-up is found again by a stable marker in its notes, so repeated saves never duplicate it.
- Rejected / Withdrawn / Closed: the "Apply:" and "Follow up:" tasks are completed (status "done", the app's
  convention for finished tasks). Nothing is deleted.
- A new personal deadline moves the due date of the still-open "Apply:" task.

Everything is owner-scoped and best effort: a Timeline problem never fails the application update.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from backend.memory import structured

logger = logging.getLogger(__name__)

FOLLOW_UP_DAYS = 14
TASK_DOMAIN = "general"  # same domain the "Apply:" task is created in
_APPLIED = "SUBMITTED"
_CLOSED = {"REJECTED", "WITHDRAWN", "CLOSED"}


def apply_title(role: str, company: str) -> str:
    return f"Apply: {role} at {company}"[:300]


def follow_up_title(role: str, company: str) -> str:
    return f"Follow up: {role} at {company}"[:300]


def follow_up_marker(application_id: int) -> str:
    return f"[compass-application:{application_id}]"


def _status(value: Any) -> str:
    return str(getattr(value, "value", value) or "").upper()


def _same_title(task: dict, title: str) -> bool:
    return (task.get("title") or "").strip().lower() == title.strip().lower()


async def _complete(conn: Any, tasks: List[dict], user_id: str) -> None:
    for task in tasks:
        if task.get("status") != "done":
            await structured.update_task(conn, task["id"], owner_id=user_id, status="done")


async def _sync(conn: Any, user_id: str, app: Any, opp: Any, deadline_changed: bool) -> None:
    status = _status(app.status)
    a_title = apply_title(opp.role_title, opp.company_name)
    f_title = follow_up_title(opp.role_title, opp.company_name)
    marker = follow_up_marker(app.id)
    tasks = await structured.list_tasks(conn, user_id=user_id)
    apply_tasks = [t for t in tasks if _same_title(t, a_title)]
    follow_tasks = [t for t in tasks if _same_title(t, f_title) and marker in (t.get("notes") or "")]

    if status == _APPLIED:
        await _complete(conn, apply_tasks, user_id)
        applied_on = app.submitted_at.date() if isinstance(app.submitted_at, datetime) else date.today()
        due = applied_on + timedelta(days=FOLLOW_UP_DAYS)
        if follow_tasks:
            for task in follow_tasks:
                if task.get("status") != "done" and task.get("due_date") != due:
                    await structured.update_task(conn, task["id"], owner_id=user_id, due_date=due)
        else:
            await structured.create_task(
                conn,
                domain=TASK_DOMAIN,
                title=f_title,
                due_date=due,
                priority="medium",
                notes=f"Check in on your application. {marker}",
                user_id=user_id,
            )
    elif status in _CLOSED:
        await _complete(conn, apply_tasks + follow_tasks, user_id)
    elif deadline_changed and app.target_deadline is not None:
        for task in apply_tasks:
            if task.get("status") != "done" and task.get("due_date") != app.target_deadline:
                await structured.update_task(conn, task["id"], owner_id=user_id, due_date=app.target_deadline)


async def sync_application_tasks(
    user_id: str, app: Any, opp: Optional[Any], *, status_changed: bool, deadline_changed: bool
) -> None:
    """Apply the Timeline side effects of an application update. Never raises."""
    if opp is None or not (status_changed or deadline_changed):
        return
    try:
        from backend.memory.db import get_pool

        pool = await get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            await _sync(conn, user_id, app, opp, deadline_changed)
    except Exception as err:
        logger.info("Application tasks not synced (%s)", type(err).__name__)
