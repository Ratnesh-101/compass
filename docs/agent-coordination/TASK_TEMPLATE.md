# Task: <ID> — <short title>

- **Owner (agent):** <sonnet | gemini | opus>
- **Branch / worktree:** `<agent/...>` in `<path>`
- **Base commit:** `<sha>` (verified with `git rev-parse`)
- **Status:** planned | dispatched | reported | accepted | rejected

## Objective
<one paragraph; what and why>

## Allowed files (write)
- <exact paths or a new file path>

## Forbidden files
- Everything else, especially: `backend/main.py`, `tests/conftest.py`, manifests/lockfiles, `.env*`, `.github/`

## Dependencies / contracts
<API shapes, schema, component props this task relies on; or "none">

## Acceptance criteria
1. <observable, testable>
2. <...>

## Verification (the orchestrator re-runs these)
```
<exact commands>
```

## Notes / known risks
<anything the worker should avoid>

## Result (filled in from the worker report)
- Commit: `<sha>`
- Tests run: <literal output lines>
- Deviations: <none | list>
- Orchestrator verdict: <accepted | rejected — reason>
