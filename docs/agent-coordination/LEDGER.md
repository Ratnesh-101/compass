# Coordination Ledger

One row per task. The orchestrator updates it; workers report in the shape defined in `AGENTS.md`.
Statuses: planned → dispatched → reported → accepted | rejected. Never mark `accepted` without the
orchestrator's own verification run.

| Task | Title | Agent | Branch | Base | Allowed files | Status | Commit | Verified by orchestrator |
|---|---|---|---|---|---|---|---|---|
| P-001 | Unit tests for task-ownership helpers | sonnet | `agent/sonnet/ownership-helper-tests` | `49e68cd` | `tests/test_ownership_helpers.py` | accepted | `c036214` | yes: diff = allowed file only; 31 passed; ruff clean; 3 tests fail when the helper is deliberately broken |
| P-002 | Node tests for deadline classifier | gemini | `agent/gemini/deadline-classifier-tests` | `49e68cd` | `frontend/tests/deadlineClassifier.test.mjs` | accepted | `27b670f` | yes: diff = allowed file only; 18 passed in 4 timezones; frontend suite 105 passed; 2 of 3 deliberate breakages caught (3rd is an equivalent mutant) |

## Active worktrees (scratch, safe to delete when the task is accepted or rejected)
Recorded in the task file when created. Never reuse a worktree for a second task.
