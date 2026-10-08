"""
Compass — Structured Memory Operations (Projects & Tasks).

Provides CRUD operations and fuzzy project matching for PostgreSQL.
Used by the router skills and API endpoints.
"""

from datetime import date
from typing import Optional, Union, Any
import asyncpg
from asyncpg.pool import PoolConnectionProxy

DbConn = Union[asyncpg.Connection, PoolConnectionProxy]

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

VALID_DOMAINS = {"hackathon", "coursework", "code", "general", "other"}


def normalize_domain(domain: Optional[str]) -> str:
    """Sanitize and normalize domain name, supporting standard domains, 'other', and custom categories."""
    if not domain:
        return "general"
    clean = str(domain).lower().strip().replace(" ", "-")
    import re
    clean = re.sub(r"[^a-z0-9_-]", "", clean)
    return clean[:32] if clean else "general"


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

async def get_or_create_project(
    conn: DbConn,
    name: str,
    domain: str,
    description: Optional[str] = None,
) -> dict:
    """Find an existing project by exact or fuzzy name, or create a new one.

    Fuzzy resolution:
      1. Exact case-insensitive match (e.g. 'compass' == 'Compass')
      2. Prefix/substring match with length >= 3 safeguard
      3. Word overlap match
    """
    clean_name = name.strip()

    # 1. Exact match (case-insensitive)
    row = await conn.fetchrow(
        "SELECT id, name, domain, description, created_at FROM projects WHERE LOWER(name) = LOWER($1)",
        clean_name
    )
    if row:
        return dict(row)

    # 2. Fuzzy match: project name starts with or contains candidate, or candidate contains project name
    # Guard: Require both names to be at least 3 characters long to prevent short names
    # (like 'AI' or 'Go') from spuriously matching arbitrary task descriptions.
    if len(clean_name) >= 3:
        row = await conn.fetchrow(
            """
            SELECT id, name, domain, description, created_at
            FROM projects
            WHERE LENGTH(name) >= 3
              AND (
                  LOWER(name) LIKE '%' || LOWER($1) || '%'
                  OR LOWER($1) LIKE '%' || LOWER(name) || '%'
              )
            ORDER BY LENGTH(name) ASC
            LIMIT 1
            """,
            clean_name
        )
        if row:
            return dict(row)

    # 3. Create new project if domain is valid
    target_domain = normalize_domain(domain)

    row = await conn.fetchrow(
        """
        INSERT INTO projects (name, domain, description)
        VALUES ($1, $2, $3)
        ON CONFLICT (name) DO UPDATE SET description = COALESCE(EXCLUDED.description, projects.description)
        RETURNING id, name, domain, description, created_at
        """,
        clean_name, target_domain, description
    )
    return dict(row) if row else {}


async def list_projects(
    conn: DbConn,
    domain: Optional[str] = None,
) -> list[dict]:
    """Retrieve all projects, optionally filtered by domain."""
    if domain:
        rows = await conn.fetch(
            "SELECT id, name, domain, description, created_at FROM projects WHERE domain = $1 ORDER BY name ASC",
            domain
        )
    else:
        rows = await conn.fetch(
            "SELECT id, name, domain, description, created_at FROM projects ORDER BY name ASC"
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

async def create_task(
    conn: DbConn,
    domain: str,
    title: str,
    project_id: Optional[int] = None,
    due_date: Optional[date] = None,
    status: str = "open",
    priority: str = "medium",
    notes: Optional[str] = None,
    user_id: Optional[str] = None,
    trusted_event_url: Optional[str] = None,
) -> dict:
    """Insert a new task into the structured tasks table with normalized inputs and user identity."""
    # Normalize domain, status, and priority
    norm_domain = normalize_domain(domain)

    stat_clean = str(status or "open").lower().strip()
    norm_status = STATUS_MAP.get(stat_clean, "open")

    prio_clean = str(priority or "medium").lower().strip()
    norm_priority = PRIORITY_MAP.get(prio_clean, "medium")

    row = await conn.fetchrow(
        """
        INSERT INTO tasks (domain, project_id, title, due_date, status, priority, notes, user_id, trusted_event_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id, domain, project_id, title, due_date, status, priority, notes, user_id, trusted_event_url, created_at, updated_at
        """,
        norm_domain, project_id, title.strip(), due_date, norm_status, norm_priority, notes, user_id, trusted_event_url
    )
    return dict(row) if row else {}


async def get_task(conn: DbConn, task_id: int) -> Optional[dict]:
    """Retrieve a task by ID including project details."""
    row = await conn.fetchrow(
        """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority, t.notes, t.trusted_event_url,
               t.duration_minutes, t.scheduled_start, t.scheduled_end, t.is_fixed, t.recurrence_rule,
               t.created_at, t.updated_at, t.user_id,
               p.id AS project_id, p.name AS project_name
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE t.id = $1
        """,
        task_id
    )
    if not row:
        return None

    data = dict(row)
    if data["project_id"]:
        data["project"] = {"id": data["project_id"], "name": data["project_name"]}
    else:
        data["project"] = None
    return data


async def list_tasks(
    conn: DbConn,
    domain: Optional[str] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    due_before: Optional[date] = None,
    scheduled_only: bool = False,
    unscheduled_only: bool = False,
    user_id: Optional[str] = None,
) -> list[dict]:
    """Query tasks with optional filters and per-account isolation."""
    query = """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority, t.notes, t.trusted_event_url,
               t.duration_minutes, t.scheduled_start, t.scheduled_end, t.is_fixed, t.recurrence_rule,
               t.created_at, t.updated_at, t.user_id,
               p.id AS project_id, p.name AS project_name
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE ($1::text IS NULL OR (t.user_id = $1 OR (t.user_id IS NULL AND NOT EXISTS (SELECT 1 FROM tasks WHERE user_id = $1))))
          AND ($2::text IS NULL OR t.domain = $2)
          AND ($3::integer IS NULL OR t.project_id = $3)
          AND ($4::text IS NULL OR t.status = $4)
          AND ($5::date IS NULL OR t.due_date <= $5)
          AND (NOT $6::boolean OR t.scheduled_start IS NOT NULL)
          AND (NOT $7::boolean OR t.scheduled_start IS NULL)
        ORDER BY t.scheduled_start ASC NULLS LAST, t.due_date ASC NULLS LAST, t.id ASC
    """
    rows = await conn.fetch(
        query,
        user_id,
        domain,
        project_id,
        status,
        due_before,
        bool(scheduled_only),
        bool(unscheduled_only),
    )
    results = []
    for r in rows:
        item = dict(r)
        if item["project_id"]:
            item["project"] = {"id": item["project_id"], "name": item["project_name"]}
        else:
            item["project"] = None
        results.append(item)
    return results


async def update_task(
    conn: DbConn,
    task_id: int,
    **kwargs: Any
) -> Optional[dict]:
    """Update task fields dynamically (e.g. status, priority, due_date, notes, scheduling) with normalization."""
    allowed_fields = {"domain", "project_id", "title", "due_date", "status", "priority", "notes",
                      "duration_minutes", "scheduled_start", "scheduled_end", "is_fixed", "recurrence_rule", "trusted_event_url"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return await get_task(conn, task_id)

    # Normalize fields if provided
    if "domain" in updates and updates["domain"]:
        updates["domain"] = normalize_domain(updates["domain"])
    if "status" in updates and updates["status"]:
        s_val = str(updates["status"]).lower().strip()
        updates["status"] = STATUS_MAP.get(s_val, "open")
    if "priority" in updates and updates["priority"]:
        p_val = str(updates["priority"]).lower().strip()
        updates["priority"] = PRIORITY_MAP.get(p_val, "medium")
    if "duration_minutes" in updates and updates["duration_minutes"] is not None:
        try:
            updates["duration_minutes"] = int(updates["duration_minutes"])
        except (ValueError, TypeError):
            updates["duration_minutes"] = 60

    query = """
        UPDATE tasks
        SET domain = CASE WHEN $2::boolean THEN $3::text ELSE domain END,
            project_id = CASE WHEN $4::boolean THEN $5::integer ELSE project_id END,
            title = CASE WHEN $6::boolean THEN $7::text ELSE title END,
            due_date = CASE WHEN $8::boolean THEN $9::date ELSE due_date END,
            status = CASE WHEN $10::boolean THEN $11::text ELSE status END,
            priority = CASE WHEN $12::boolean THEN $13::text ELSE priority END,
            notes = CASE WHEN $14::boolean THEN $15::text ELSE notes END,
            duration_minutes = CASE WHEN $16::boolean THEN $17::integer ELSE duration_minutes END,
            scheduled_start = CASE WHEN $18::boolean THEN $19::timestamptz ELSE scheduled_start END,
            scheduled_end = CASE WHEN $20::boolean THEN $21::timestamptz ELSE scheduled_end END,
            is_fixed = CASE WHEN $22::boolean THEN $23::boolean ELSE is_fixed END,
            recurrence_rule = CASE WHEN $24::boolean THEN $25::text ELSE recurrence_rule END,
            trusted_event_url = CASE WHEN $26::boolean THEN $27::text ELSE trusted_event_url END,
            updated_at = now()
        WHERE id = $1
        RETURNING id
    """
    row = await conn.fetchrow(
        query,
        task_id,
        "domain" in updates,
        updates.get("domain"),
        "project_id" in updates,
        updates.get("project_id"),
        "title" in updates,
        updates.get("title"),
        "due_date" in updates,
        updates.get("due_date"),
        "status" in updates,
        updates.get("status"),
        "priority" in updates,
        updates.get("priority"),
        "notes" in updates,
        updates.get("notes"),
        "duration_minutes" in updates,
        updates.get("duration_minutes"),
        "scheduled_start" in updates,
        updates.get("scheduled_start"),
        "scheduled_end" in updates,
        updates.get("scheduled_end"),
        "is_fixed" in updates,
        updates.get("is_fixed"),
        "recurrence_rule" in updates,
        updates.get("recurrence_rule"),
        "trusted_event_url" in updates,
        updates.get("trusted_event_url"),
    )
    if not row:
        return None
    return await get_task(conn, task_id)


async def update_task_status(conn: DbConn, task_id: int, status: str) -> Optional[dict]:
    """Convenience helper to update task status."""
    return await update_task(conn, task_id, status=status)


async def delete_task(conn: DbConn, task_id: int) -> bool:
    """Delete a task by ID."""
    result = await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)
    return result == "DELETE 1"


# ---------------------------------------------------------------------------
# Scheduling Preferences & Calendar Connections
# ---------------------------------------------------------------------------

async def get_scheduling_preferences(conn: DbConn, user_id: str = "default_user") -> dict:
    """Get scheduling preferences for a user, or defaults if not configured."""
    row = await conn.fetchrow(
        """
        SELECT user_id, work_start_time, work_end_time, work_days, buffer_minutes, preferred_focus
        FROM scheduling_preferences
        WHERE user_id = $1
        """,
        user_id
    )
    if row:
        res = dict(row)
        if hasattr(res["work_start_time"], "strftime"):
            res["work_start_time"] = res["work_start_time"].strftime("%H:%M:%S")
        if hasattr(res["work_end_time"], "strftime"):
            res["work_end_time"] = res["work_end_time"].strftime("%H:%M:%S")
        return res

    return {
        "user_id": user_id,
        "work_start_time": "09:00:00",
        "work_end_time": "18:00:00",
        "work_days": [1, 2, 3, 4, 5],
        "buffer_minutes": 15,
        "preferred_focus": "morning"
    }


async def update_scheduling_preferences(
    conn: DbConn,
    user_id: str = "default_user",
    **kwargs: Any
) -> dict:
    """Update or insert scheduling preferences for a user."""
    allowed = {"work_start_time", "work_end_time", "work_days", "buffer_minutes", "preferred_focus"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    # Ensure row exists
    await conn.execute(
        """
        INSERT INTO scheduling_preferences (user_id, work_start_time, work_end_time, work_days, buffer_minutes, preferred_focus)
        VALUES ($1, '09:00:00', '18:00:00', '{1,2,3,4,5}', 15, 'morning')
        ON CONFLICT (user_id) DO NOTHING
        """,
        user_id
    )

    if not updates:
        return await get_scheduling_preferences(conn, user_id)

    query = """
        UPDATE scheduling_preferences
        SET work_start_time = CASE WHEN $2::boolean THEN $3::time ELSE work_start_time END,
            work_end_time = CASE WHEN $4::boolean THEN $5::time ELSE work_end_time END,
            work_days = CASE WHEN $6::boolean THEN $7::integer[] ELSE work_days END,
            buffer_minutes = CASE WHEN $8::boolean THEN $9::integer ELSE buffer_minutes END,
            preferred_focus = CASE WHEN $10::boolean THEN $11::text ELSE preferred_focus END
        WHERE user_id = $1
    """
    await conn.execute(
        query,
        user_id,
        "work_start_time" in updates,
        updates.get("work_start_time"),
        "work_end_time" in updates,
        updates.get("work_end_time"),
        "work_days" in updates,
        updates.get("work_days"),
        "buffer_minutes" in updates,
        updates.get("buffer_minutes"),
        "preferred_focus" in updates,
        updates.get("preferred_focus"),
    )
    return await get_scheduling_preferences(conn, user_id)


# ---------------------------------------------------------------------------
# Task Dependencies Graph
# ---------------------------------------------------------------------------

async def add_task_dependency(conn: DbConn, task_id: int, depends_on_task_id: int) -> dict:
    """Add a dependency relationship: task_id depends on depends_on_task_id.
    Validates:
      1. Both tasks exist.
      2. task_id != depends_on_task_id (no self-loops).
      3. No cycle is created (reachability check from depends_on_task_id to task_id).
    """
    if task_id == depends_on_task_id:
        raise ValueError("A task cannot depend on itself")

    t1 = await conn.fetchrow("SELECT id FROM tasks WHERE id = $1", task_id)
    if not t1:
        raise ValueError(f"Task {task_id} does not exist")
    t2 = await conn.fetchrow("SELECT id FROM tasks WHERE id = $1", depends_on_task_id)
    if not t2:
        raise ValueError(f"Prerequisite task {depends_on_task_id} does not exist")

    # Check for cycle: if depends_on_task_id already depends (directly or transitively) on task_id
    cycle_check = await conn.fetchrow(
        """
        WITH RECURSIVE dep_chain AS (
            SELECT depends_on_task_id FROM task_dependencies WHERE task_id = $1
            UNION
            SELECT td.depends_on_task_id
            FROM task_dependencies td
            JOIN dep_chain dc ON td.task_id = dc.depends_on_task_id
        )
        SELECT 1 FROM dep_chain WHERE depends_on_task_id = $2
        """,
        depends_on_task_id, task_id
    )
    if cycle_check:
        raise ValueError(f"Adding dependency ({task_id} depends on {depends_on_task_id}) would create a circular dependency cycle")

    row = await conn.fetchrow(
        """
        INSERT INTO task_dependencies (task_id, depends_on_task_id)
        VALUES ($1, $2)
        ON CONFLICT (task_id, depends_on_task_id) DO UPDATE SET task_id = EXCLUDED.task_id
        RETURNING id, task_id, depends_on_task_id, created_at
        """,
        task_id, depends_on_task_id
    )
    return dict(row) if row else {}


async def remove_task_dependency(conn: DbConn, task_id: int, depends_on_task_id: int) -> bool:
    """Remove a dependency edge between task_id and depends_on_task_id."""
    res = await conn.execute(
        "DELETE FROM task_dependencies WHERE task_id = $1 AND depends_on_task_id = $2",
        task_id, depends_on_task_id
    )
    return res == "DELETE 1"


async def get_task_dependencies(conn: DbConn, task_id: int) -> list[dict]:
    """Get all tasks that task_id depends on (prerequisites), with task details."""
    rows = await conn.fetch(
        """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority,
               t.duration_minutes, t.scheduled_start, t.scheduled_end, t.is_fixed,
               td.created_at AS dependency_created_at
        FROM task_dependencies td
        JOIN tasks t ON td.depends_on_task_id = t.id
        WHERE td.task_id = $1
        ORDER BY t.scheduled_start ASC NULLS LAST, t.id ASC
        """,
        task_id
    )
    return [dict(r) for r in rows]


async def get_downstream_tasks(conn: DbConn, task_id: int) -> list[dict]:
    """Get all downstream tasks that directly or transitively depend on task_id.
    Returns in topological order (earliest dependents first).
    """
    rows = await conn.fetch(
        """
        WITH RECURSIVE downstream AS (
            SELECT td.task_id, 1 as depth
            FROM task_dependencies td
            WHERE td.depends_on_task_id = $1
            UNION
            SELECT td.task_id, d.depth + 1
            FROM task_dependencies td
            JOIN downstream d ON td.depends_on_task_id = d.task_id
        )
        SELECT DISTINCT ON (t.id) t.id, t.domain, t.title, t.due_date, t.status, t.priority,
               t.duration_minutes, t.scheduled_start, t.scheduled_end, t.is_fixed,
               d.depth
        FROM downstream d
        JOIN tasks t ON d.task_id = t.id
        ORDER BY t.id, d.depth ASC
        """,
        task_id
    )
    res = [dict(r) for r in rows]
    # Sort by depth asc, then scheduled_start asc
    res.sort(key=lambda x: (x.get("depth", 1), str(x.get("scheduled_start") or "")))
    return res


async def get_all_dependencies_map(conn: DbConn) -> dict[int, list[int]]:
    """Return a mapping of task_id -> list of prerequisite task_ids."""
    rows = await conn.fetch("SELECT task_id, depends_on_task_id FROM task_dependencies")
    dep_map: dict[int, list[int]] = {}
    for r in rows:
        dep_map.setdefault(r["task_id"], []).append(r["depends_on_task_id"])
    return dep_map


async def set_user_trusted_url(conn: DbConn, user_id: str, url: str, title: Optional[str] = None) -> dict:
    """Pin a trusted official event/docs URL for a user in the database."""
    row = await conn.fetchrow(
        """
        INSERT INTO user_trusted_urls (user_id, url, title, created_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (user_id, url) DO UPDATE
        SET title = COALESCE(EXCLUDED.title, user_trusted_urls.title)
        RETURNING id, user_id, url, title, created_at
        """,
        user_id, url.strip(), title
    )
    return dict(row) if row else {}


async def get_user_trusted_urls(conn: DbConn, user_id: str) -> list[str]:
    """Retrieve all pinned trusted event URLs for a user from the database."""
    rows = await conn.fetch(
        "SELECT url FROM user_trusted_urls WHERE user_id = $1 ORDER BY created_at DESC",
        user_id
    )
    return [r["url"] for r in rows]

