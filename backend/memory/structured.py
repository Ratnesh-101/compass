"""
Compass — Structured Memory Operations (Projects & Tasks).

Provides CRUD operations and fuzzy project matching for PostgreSQL.
Used by the router skills and API endpoints.
"""

from datetime import date, datetime
from typing import Optional, Any
import asyncpg


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

async def get_or_create_project(
    conn: asyncpg.Connection,
    name: str,
    domain: str,
    description: Optional[str] = None,
) -> dict:
    """Find an existing project by exact or fuzzy name, or create a new one.

    Fuzzy resolution:
      1. Exact case-insensitive match (e.g. 'compass' == 'Compass')
      2. Prefix/substring match (e.g. 'Compass' matches 'Compass AI Assistant')
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
    row = await conn.fetchrow(
        """
        SELECT id, name, domain, description, created_at
        FROM projects
        WHERE LOWER(name) LIKE '%' || LOWER($1) || '%'
           OR LOWER($1) LIKE '%' || LOWER(name) || '%'
        ORDER BY LENGTH(name) ASC
        LIMIT 1
        """,
        clean_name
    )
    if row:
        return dict(row)

    # 3. Create new project if domain is valid
    valid_domains = {"hackathon", "coursework", "code", "general"}
    target_domain = domain if domain in valid_domains else "general"

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
    conn: asyncpg.Connection,
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
    conn: asyncpg.Connection,
    domain: str,
    title: str,
    project_id: Optional[int] = None,
    due_date: Optional[date] = None,
    status: str = "open",
    priority: str = "medium",
    notes: Optional[str] = None,
) -> dict:
    """Insert a new task into the structured tasks table."""
    row = await conn.fetchrow(
        """
        INSERT INTO tasks (domain, project_id, title, due_date, status, priority, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, domain, project_id, title, due_date, status, priority, notes, created_at, updated_at
        """,
        domain, project_id, title.strip(), due_date, status, priority, notes
    )
    return dict(row) if row else {}


async def get_task(conn: asyncpg.Connection, task_id: int) -> Optional[dict]:
    """Retrieve a task by ID including project details."""
    row = await conn.fetchrow(
        """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority, t.notes,
               t.created_at, t.updated_at,
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
    conn: asyncpg.Connection,
    domain: Optional[str] = None,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    due_before: Optional[date] = None,
) -> list[dict]:
    """Query tasks with optional filters."""
    query = """
        SELECT t.id, t.domain, t.title, t.due_date, t.status, t.priority, t.notes,
               t.created_at, t.updated_at,
               p.id AS project_id, p.name AS project_name
        FROM tasks t
        LEFT JOIN projects p ON t.project_id = p.id
        WHERE 1=1
    """
    params: list[Any] = []

    if domain:
        params.append(domain)
        query += f" AND t.domain = ${len(params)}"
    if project_id:
        params.append(project_id)
        query += f" AND t.project_id = ${len(params)}"
    if status:
        params.append(status)
        query += f" AND t.status = ${len(params)}"
    if due_before:
        params.append(due_before)
        query += f" AND t.due_date <= ${len(params)}"

    query += " ORDER BY t.due_date ASC NULLS LAST, t.id ASC"

    rows = await conn.fetch(query, *params)
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
    conn: asyncpg.Connection,
    task_id: int,
    **kwargs: Any
) -> Optional[dict]:
    """Update task fields dynamically (e.g. status, priority, due_date, notes)."""
    allowed_fields = {"domain", "project_id", "title", "due_date", "status", "priority", "notes"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return await get_task(conn, task_id)

    set_clauses = []
    params: list[Any] = [task_id]
    for k, v in updates.items():
        params.append(v)
        set_clauses.append(f"{k} = ${len(params)}")

    set_clause_str = ", ".join(set_clauses)
    query = f"""
        UPDATE tasks
        SET {set_clause_str}, updated_at = now()
        WHERE id = $1
        RETURNING id
    """
    row = await conn.fetchrow(query, *params)
    if not row:
        return None
    return await get_task(conn, task_id)


async def delete_task(conn: asyncpg.Connection, task_id: int) -> bool:
    """Delete a task by ID."""
    result = await conn.execute("DELETE FROM tasks WHERE id = $1", task_id)
    return result == "DELETE 1"
