# Coordination Ledger

One row per task. The orchestrator updates it; workers report in the shape defined in `AGENTS.md`.
Statuses: planned -> dispatched -> reported -> accepted | rejected -> merged. Never mark `accepted` without the
orchestrator's own verification run. `merged` records the squash commit on `main`.

## Batch 1 (pilots)
| Task | Title | Agent | Branch | Base | Status | Commit | Merge | Verified by orchestrator |
|---|---|---|---|---|---|---|---|---|
| P-001 | Unit tests for task-ownership helpers | sonnet | `agent/sonnet/ownership-helper-tests` | `49e68cd` | merged | `c036214` | via #139 (`32bf36f`) | diff = allowed file only; 31 passed; 3 tests fail when the helper is deliberately broken |
| P-002 | Node tests for deadline classifier | gemini | `agent/gemini/deadline-classifier-tests` | `49e68cd` | accepted | `27b670f` | PR pending | diff = allowed file only; 18 passed in 4 timezones; 2 of 3 deliberate breakages caught (3rd is an equivalent mutant) |

## Batch 2 (hardening)
| Task | Title | Agent | Branch | Base | Status | Commit | Merge | Verified by orchestrator |
|---|---|---|---|---|---|---|---|---|
| S4 | scope_owner fail-closed + stale guest token handling | sonnet | `agent/sonnet/guest-and-owner-hardening` | `d0a4c31` | merged | `b4929e5` | #139 (`32bf36f`) | allowed files only; red check: 5 of 8 (+2 of 2 follow-up) fail on old code; reviewed that identity never comes from the raw x-guest-id |
| S2 | Verifier DNS pinning | sonnet | `agent/sonnet/verifier-dns-pinning` | `d0a4c31` | merged | `d683503` | #140 (`518759d`) | 132 targeted tests pass; red check 16 failed + 6 errors on old code; reviewed pinned-IP fetch; follow-up fixed event-loop blocking and first-address-only |
| S3 | CLI hardening | sonnet | `agent/sonnet/cli-hardening` | `d0a4c31` | merged | `9108b95` | #141 (`239a1f0`) | allowed files only; 61 related tests pass; 22 of 29 new tests fail on old code |
| S1 | Tavily budget enforcement (guest cap 25, configurable) | sonnet | `agent/sonnet/tavily-budgets` | `d0a4c31` | merged | `a331933` | #142 (`9ccd49f`) | 69 related tests pass; 14 of 20 new tests fail on old code; reviewed enforcement, middleware and reserve/refund logic |
| G1 | Remove dead streamAssistantResponse / onSendMessage in ChatPanel | gemini | `agent/gemini/frontend-cleanup` | `d0a4c31` | merged | `bfb90c1` | #143 (`18ad956`) | allowed files only; test fails on old file, passes on new; frontend 97/97 then 99/99 combined; build ok |
| HF | Invalid `(?i)` regex stopped the Application Workspace modal loading | opus (orchestrator) | `fix/workspace-modal-invalid-regex` | `d0a4c31` | merged | `7298e7a` | #138 (`d7b15a1`) | new scan test fails on old code; frontend 98/98; build ok |

Combined check before the batch-2 merges: 1220 backend passed / 1 skipped (one dev-server test deselected), frontend 99/99,
build ok, ruff + bandit + file sizes + route table clean; `main` after the merges matched that tree and its CI was green.

## Lessons recorded
- `git stash` is shared across all worktrees: workers must not use it (a `stash pop` once applied an older stash of the
  user's into a scratch worktree).
- A static test plus `vite build` does not validate regex syntax; an invalid `(?i)` literal broke a lazy chunk (HF).
- Headless `agy` cannot approve shell commands: give Gemini the source inline and restrict it to file edits, or use an
  explicit permission rule / user-authorized `--dangerously-skip-permissions` for a merge run.
