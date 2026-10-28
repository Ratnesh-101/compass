# Coordination Ledger

One row per task. The orchestrator updates it; workers report in the shape defined in `AGENTS.md`.
Statuses: planned → dispatched → reported → accepted | rejected. Never mark `accepted` without the
orchestrator's own verification run.

| Task | Title | Agent | Branch | Base | Allowed files | Status | Commit | Verified by orchestrator |
|---|---|---|---|---|---|---|---|---|
| P-001 | Unit tests for task-ownership helpers | sonnet | `agent/sonnet/ownership-helper-tests` | `49e68cd` | `tests/test_ownership_helpers.py` | dispatched | — | — |
| P-002 | Node tests for deadline classifier | gemini | `agent/gemini/deadline-classifier-tests` | `49e68cd` | `frontend/tests/deadlineClassifier.test.mjs` | dispatched | — | — |

## Active worktrees (scratch, safe to delete when the task is accepted or rejected)
Recorded in the task file when created. Never reuse a worktree for a second task.
