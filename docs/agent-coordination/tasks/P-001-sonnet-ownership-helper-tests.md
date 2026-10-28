# Task: P-001 — Unit tests for the task-ownership helpers

- **Owner (agent):** sonnet
- **Branch / worktree:** `agent/sonnet/ownership-helper-tests`
- **Base commit:** `49e68cd`
- **Status:** accepted

## Objective
`backend/services/ownership.py` (`scope_owner`, `owns_task`, `require_task_access`) guards every route and
skill that touches a task by id, but has no direct unit tests (it is only covered indirectly by route tests).
Add focused unit tests that pin its contract.

## Allowed files (write)
- `tests/test_ownership_helpers.py` (new file only)

## Forbidden files
- Everything else, including `backend/services/ownership.py` itself, `tests/conftest.py`, manifests, `.env*`.

## Dependencies / contracts
- `scope_owner(None | "" | "admin" | " ADMIN ")` -> `None`; any other id is returned stripped.
- `owns_task(task_owner, ident)`: admin identities always pass; otherwise a case-insensitive, whitespace-
  trimmed match of `ident.id` against `task_owner`; a missing owner or missing `ident.id` never passes.
- `require_task_access(conn, task_id, ident)`: loads via `backend.memory.structured.get_task`; missing task and
  foreign task both raise `HTTPException(404)`; the owner and an admin get the task dict back.
- `Identity` is `backend.dependencies.Identity` (frozen dataclass: `id`, `is_admin`, `is_guest`, `user_id`, `guest_id`).

## Acceptance criteria
1. Table-driven tests for `scope_owner` and `owns_task` covering the contract above, including case/whitespace.
2. `require_task_access` tests use a fake `get_task` (monkeypatch `backend.services.ownership.structured.get_task`);
   no database and no network.
3. Tests do not modify any source file and pass.

## Verification (the orchestrator re-runs these)
```
bash <runtests script> <worktree> tests/test_ownership_helpers.py -q
python -m ruff check tests/test_ownership_helpers.py
```

## Result
- Commit: `c036214` on `agent/sonnet/ownership-helper-tests` (base `49e68cd`)
- Orchestrator verification: diff vs base is `tests/test_ownership_helpers.py` only; `31 passed`; `ruff` clean;
  mutation check (made `owns_task` case-sensitive) -> `3 failed, 28 passed`, source restored.
- Deviations: none against the contract. Worker noted `scope_owner("   ")` returns `""` (not `None`); pinned as-is.
  Follow-up worth considering: a whitespace-only owner is falsy-but-not-None, so treat it explicitly in `scope_owner`.
- Verdict: accepted.
