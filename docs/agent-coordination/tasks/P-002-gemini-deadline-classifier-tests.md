# Task: P-002 — Node tests for the deadline classifier

- **Owner (agent):** gemini (Antigravity)
- **Branch / worktree:** `agent/gemini/deadline-classifier-tests`
- **Base commit:** `49e68cd`
- **Status:** accepted

## Objective
`frontend/src/utils/deadlineClassifier.js` implements a deterministic deadline classification engine
(documented in its header comment) but has no dedicated test file. Add Node tests that pin its documented behavior.

## Allowed files (write)
- `frontend/tests/deadlineClassifier.test.mjs` (new file only)

## Forbidden files
- Everything else, including `frontend/src/**`, `frontend/package.json`, lockfiles, `.env*`.

## Dependencies / contracts
- Test with Node's built-in runner (`node:test`, `node:assert/strict`), importing the module by relative path,
  in the same style as the other files in `frontend/tests/`.
- Read the module's header comment and exported functions first; test only exported behavior.
- Do NOT assert anything about "demo" task detection (that logic is changing elsewhere).
- Use fixed reference dates passed in explicitly where the API allows it; do not depend on today's real date or
  on the machine's timezone beyond what the module documents.

## Acceptance criteria
1. Covers the documented precedence rules: completed/cancelled excluded, no-deadline, overdue, due_today
   (date-only deadline stays due_today through its local day), urgent (within 24h), due_soon (within 7 days), upcoming.
2. Covers `parseDeadlineDate` for date-only, timestamp, empty and malformed input.
3. The file runs standalone with `node --test frontend/tests/deadlineClassifier.test.mjs` and passes.

## Verification (the orchestrator re-runs these)
```
cd frontend && node --test tests/deadlineClassifier.test.mjs
cd frontend && node --test tests/*.test.mjs
```

## Result
- Commit: `27b670f` on `agent/gemini/deadline-classifier-tests` (base `49e68cd`), committed by the orchestrator
  because headless `agy` has no shell permission by design.
- Dispatch notes: attempt 1 produced nothing (headless mode auto-denied a shell command). Attempt 2 supplied the module
  source and a sample test inline and told the worker to use only its file-writing tool; that succeeded without
  `--dangerously-skip-permissions`.
- Orchestrator verification: diff vs base is `frontend/tests/deadlineClassifier.test.mjs` only; `18 passed` (also under
  TZ=UTC, Asia/Kolkata, America/Los_Angeles, Pacific/Auckland); `node --test tests/*.test.mjs` -> `105 pass, 0 fail`.
  Mutation checks: 24h window 24->12 -> 2 failures; 7-day window 7->3 -> 3 failures; date-only overdue rule change ->
  0 failures (behaviorally equivalent, not a test gap).
- Deviations reported by the worker (all verified against the code): completed/cancelled return timing
  'completed'/'cancelled'; date-only parsing ends at 23:59:59.999; the 'urgent' filters also match 'due_today'.
  The module header comment is slightly out of date on those three points.
- Verdict: accepted.
