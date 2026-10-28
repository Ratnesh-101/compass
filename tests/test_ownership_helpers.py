"""Unit tests for backend.services.ownership (scope_owner, owns_task, require_task_access)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.dependencies import Identity
from backend.services import ownership
from backend.services.ownership import owns_task, require_task_access, scope_owner


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", None),
        ("admin", None),
        ("ADMIN", None),
        (" ADMIN ", None),
        ("\tAdmin\n", None),
        ("user-1", "user-1"),
        ("  user-1  ", "user-1"),
        ("Mixed-Case", "Mixed-Case"),
        ("administrator", "administrator"),
        # Whitespace-only is malformed, not unscoped: fail closed with the reserved owner.
        ("   ", ownership.NO_OWNER),
        ("\t\n", ownership.NO_OWNER),
    ],
)
def test_scope_owner(raw, expected):
    assert scope_owner(raw) == expected


@pytest.mark.parametrize(
    "task_owner, ident, expected",
    [
        # Admin always passes, whatever the owner.
        ("someone", Identity(id="x", is_admin=True), True),
        (None, Identity(id="x", is_admin=True), True),
        ("", Identity(id="", is_admin=True), True),
        # Exact, case-insensitive and whitespace-trimmed matches pass.
        ("user-1", Identity(id="user-1"), True),
        ("User-1", Identity(id="user-1"), True),
        ("user-1", Identity(id="USER-1"), True),
        ("  user-1 ", Identity(id="user-1"), True),
        ("user-1", Identity(id="  user-1\t"), True),
        # Mismatches fail.
        ("user-1", Identity(id="user-2"), False),
        ("user-1", Identity(id="user-10"), False),
        # Missing owner or missing ident.id never passes.
        (None, Identity(id="user-1"), False),
        ("", Identity(id="user-1"), False),
        ("user-1", Identity(id=""), False),
        (None, Identity(id=""), False),
    ],
)
def test_owns_task(task_owner, ident, expected):
    assert owns_task(task_owner, ident) is expected


def _patch_get_task(monkeypatch, task):
    calls = []

    async def fake_get_task(conn, task_id):
        calls.append((conn, task_id))
        return task

    monkeypatch.setattr(ownership.structured, "get_task", fake_get_task)
    return calls


def test_require_task_access_returns_task_for_owner(monkeypatch):
    task = {"id": 7, "user_id": "user-1", "title": "t"}
    calls = _patch_get_task(monkeypatch, task)
    conn = object()

    result = asyncio.run(require_task_access(conn, 7, Identity(id="User-1")))

    assert result is task
    assert calls == [(conn, 7)]


def test_require_task_access_returns_task_for_admin(monkeypatch):
    task = {"id": 7, "user_id": "someone-else"}
    _patch_get_task(monkeypatch, task)

    result = asyncio.run(require_task_access(object(), 7, Identity(id="admin", is_admin=True)))

    assert result is task


@pytest.mark.parametrize("missing", [None, {}])
def test_require_task_access_missing_task_404(monkeypatch, missing):
    _patch_get_task(monkeypatch, missing)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_task_access(object(), 99, Identity(id="user-1")))

    assert exc.value.status_code == 404


def test_require_task_access_foreign_task_404_same_as_missing(monkeypatch):
    _patch_get_task(monkeypatch, {"id": 7, "user_id": "someone-else"})
    with pytest.raises(HTTPException) as foreign:
        asyncio.run(require_task_access(object(), 7, Identity(id="user-1")))

    _patch_get_task(monkeypatch, None)
    with pytest.raises(HTTPException) as missing:
        asyncio.run(require_task_access(object(), 7, Identity(id="user-1")))

    assert foreign.value.status_code == 404
    assert (foreign.value.status_code, foreign.value.detail) == (
        missing.value.status_code,
        missing.value.detail,
    )


def test_require_task_access_ownerless_task_404_for_non_admin(monkeypatch):
    _patch_get_task(monkeypatch, {"id": 7, "user_id": None})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_task_access(object(), 7, Identity(id="user-1")))

    assert exc.value.status_code == 404
