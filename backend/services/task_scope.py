"""Shared task visibility rules so chat and the dashboard agree on what a user "has".

Judge Persona demo rows are tagged with a ``compass://demo-persona/`` URL. They are
hidden unless a caller explicitly asks for them. Owner scoping is mandatory here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

DEMO_URL_PREFIX = "compass://demo-persona/"


def demo_sql_predicate(alias: str = "") -> str:
    """SQL fragment that is true for non-demo rows (the ``include_demo=False`` case)."""
    prefix = f"{alias}." if alias else ""
    return f"(COALESCE({prefix}trusted_event_url,'') NOT LIKE '{DEMO_URL_PREFIX}%')"


async def visible_tasks(
    conn: Any,
    owner: Optional[str],
    *,
    include_demo: bool = False,
    domain: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the owner's non-deleted tasks, excluding demo rows unless requested."""
    if not owner or not str(owner).strip():
        raise ValueError("visible_tasks requires a non-empty owner")
    rows = await conn.fetch(
        """
        SELECT id, title, domain, due_date, status, priority, user_id, trusted_event_url
        FROM tasks
        WHERE user_id = $1
          AND deleted_at IS NULL
          AND ($2::boolean OR COALESCE(trusted_event_url,'') NOT LIKE 'compass://demo-persona/%')
          AND ($3::text IS NULL OR domain = $3)
          AND ($4::text IS NULL OR status = $4)
        ORDER BY due_date ASC NULLS LAST, id ASC
        """,
        owner,
        bool(include_demo),
        domain,
        status,
    )
    return [dict(r) for r in rows]


async def list_chat_tasks(conn: Any, args: Dict[str, Any], **filters: Any) -> List[Dict[str, Any]]:
    """``structured.list_tasks`` for chat skill handlers: owner required, demo rows hidden by default.

    Without a ``user_id`` in ``args`` nothing is listed (never another tenant's tasks).
    """
    user_id = args.get("user_id")
    if not user_id:
        return []
    from backend.memory import structured

    return await structured.list_tasks(
        conn, user_id=user_id, include_demo=bool(args.get("include_demo", False)), **filters
    )
