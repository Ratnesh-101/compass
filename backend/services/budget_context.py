"""
Compass - request-scoped budget context.

Carries the caller's identity (for per-identity Tavily budgets) and a per-run Tavily
credit counter through ``contextvars`` so deep service code (``tavily.search`` /
``tavily.extract``) can enforce budgets without every call site threading arguments.

Context is bound by the ASGI middleware in ``backend.main`` and is inherited by tasks
spawned from the request (``asyncio.gather``, ``create_task``) and by streaming
response generators.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BudgetIdentity:
    """Immutable view of the caller used for budget decisions."""

    identity_id: str
    is_guest: bool = False
    is_admin: bool = False


class RunCounter:
    """Mutable Tavily credit counter shared by every task of one run."""

    __slots__ = ("used",)

    def __init__(self) -> None:
        self.used = 0


_identity_var: ContextVar[Optional[BudgetIdentity]] = ContextVar("compass_budget_identity", default=None)
_run_counter_var: ContextVar[Optional[RunCounter]] = ContextVar("compass_run_counter", default=None)


def bind_identity(identity: Optional[BudgetIdentity]) -> Token:
    """Bind (or clear, with None) the caller identity; returns a token for ``reset_identity``."""
    return _identity_var.set(identity)


def reset_identity(token: Token) -> None:
    _identity_var.reset(token)


def get_identity() -> Optional[BudgetIdentity]:
    return _identity_var.get()


def begin_run_counter() -> Token:
    """Start a fresh per-run Tavily credit counter in the current context."""
    return _run_counter_var.set(RunCounter())


def end_run_counter(token: Token) -> None:
    _run_counter_var.reset(token)


def ensure_run_counter() -> Optional[Token]:
    """Start a counter only when none is active; returns its token, or None if one already existed."""
    if _run_counter_var.get() is None:
        return begin_run_counter()
    return None


def get_run_counter() -> Optional[RunCounter]:
    return _run_counter_var.get()


def add_run_credits(credits: int) -> None:
    """Add (or, with a negative value, refund) credits on the active run counter."""
    counter = _run_counter_var.get()
    if counter is not None:
        counter.used = max(0, counter.used + credits)


def run_credits_used() -> Optional[int]:
    """Credits used by the active run, or None when no run counter is active."""
    counter = _run_counter_var.get()
    return None if counter is None else counter.used
