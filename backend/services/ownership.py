"""
Compass — Task ownership helpers.

Every route or skill that touches a task by id must prove the caller owns it.
Admin identities (the AUTH_TOKEN holder) bypass the check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from fastapi import HTTPException

from backend.memory import structured

if TYPE_CHECKING:
    from backend.dependencies import Identity

ADMIN_OWNER = "admin"

# Reserved owner that matches no real user. A non-empty but blank owner id (e.g. "   ") is
# malformed, not "unscoped", so it must fail closed: truthy in Python guards (`if scoped_owner`)
# and never equal to any stored user_id in SQL comparisons.
NO_OWNER = "\x00no-owner"


def scope_owner(user_id: Optional[str]) -> Optional[str]:
    """Return the owner to scope SQL by, or None when the caller is unscoped (admin / internal).

    None / "" / "admin" mean unscoped. A whitespace-only id returns NO_OWNER (fail closed).
    """
    if not user_id or user_id.strip().lower() == ADMIN_OWNER:
        return None
    stripped = user_id.strip()
    return stripped or NO_OWNER


def owns_task(task_owner: Optional[str], ident: "Identity") -> bool:
    """True when the identity may act on a task owned by `task_owner`."""
    if ident.is_admin:
        return True
    if not task_owner or not ident.id:
        return False
    return task_owner.strip().lower() == ident.id.strip().lower()


async def require_task_access(conn: Any, task_id: int, ident: "Identity") -> dict:
    """Load a task and verify ownership. Missing and foreign tasks both 404 to avoid id enumeration."""
    task = await structured.get_task(conn, task_id)
    if not task or not owns_task(task.get("user_id"), ident):
        raise HTTPException(status_code=404, detail="Task not found")
    return task
