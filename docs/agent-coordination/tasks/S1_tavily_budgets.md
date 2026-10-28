# Task S1 - Enforce Tavily budgets (per-run, per-identity daily, global)

- Worktree: <local path>   Branch: agent/sonnet/tavily-budgets   Base: d0a4c31
- Test script: bash "<local path>" "<worktree with forward slashes>" [pytest args]
- May edit: backend/services/budgets.py, backend/services/usage.py, backend/services/tavily.py, backend/services/tavily_pipeline.py,
  NEW backend/services/budget_context.py, backend/main.py (ONLY to add one middleware), backend/memory/db.py, backend/memory/schema.sql,
  NEW tests/test_tavily_budget_enforcement.py (and minimal edits to existing tests that now need an identity/context to pass).
- Must NOT edit: backend/dependencies.py (another worker owns it), backend/services/winning_features.py (the separate in-process intel sub-budget of 30 stays as is),
  tests/conftest.py, anything else.

## Problem (verified by the orchestrator)
`backend/services/budgets.py` defines caps (MAX_RUN_TAVILY_CREDITS=6, MAX_DAILY_USER_TAVILY_CREDITS=30, MAX_DAILY_GUEST_TAVILY_CREDITS=8) and
functions `check_run_limits`, `check_daily_identity_budget`, `check_global_spend_cap`, but NOTHING in production code calls them
(`tavily_pipeline.py` imports check_run_limits and never uses it). `check_daily_identity_budget` also sums credits for ALL identities because
`tavily_usage_log` (created in backend/memory/db.py ~line 113; schema in backend/memory/schema.sql if present) has only (operation, credits, created_at).
All real Tavily spending flows through `backend/services/tavily.py` `search()` (records via `record_tavily_credits("search", ...)` ~line 130) and `extract()` (~line 149).
Result: the stated per-run / per-user / per-guest limits are not enforced anywhere.

## Design (follow it; deviations go in your report)
1. NEW `backend/services/budget_context.py`: `contextvars`-based request context holding `identity_id: Optional[str]`, `is_guest: bool`, `is_admin: bool`
   and a per-run Tavily credit counter. Provide small helpers: bind/get identity, `begin_run_counter()` / `add_run_credits(n)` / `run_credits_used()`.
2. `backend/main.py`: add ONE HTTP middleware that resolves the caller with `backend.dependencies._get_current_identity(request)` inside try/except
   (it may raise HTTPException for bad headers - then bind no identity, and never turn that into a middleware failure) and binds the context for the
   request. IMPORTANT: confirm by a test that the bound identity is visible inside the SSE chat stream generator (`POST /api/chat/stream`) and inside
   background-style code that awaits tavily from a route; context must survive Starlette's streaming responses. If BaseHTTPMiddleware loses the context for
   streaming, use a pure ASGI middleware instead.
3. `backend/memory/db.py`: add `ALTER TABLE tavily_usage_log ADD COLUMN IF NOT EXISTS identity TEXT;` plus an index on (identity, created_at), next to the
   existing table creation (same idempotent style as other ALTERs there); mirror in schema.sql if the table is defined there. Nullable: old rows stay NULL.
4. `usage.py` `_persist_tavily_to_db`: also store the bound identity (NULL when none).
5. `budgets.py`: add `async def enforce_tavily_budget(cost: int) -> None`, called by `tavily.search`/`tavily.extract` BEFORE spending:
   - per-run: if a run counter is active and used+cost > MAX_RUN_TAVILY_CREDITS -> raise `BudgetExceededError` (existing class).
   - global: `await check_global_spend_cap()` (existing; keep its kill switch and the production fail-closed behavior added in #136).
   - per-identity daily: if an identity is bound and not admin -> sum today's credits for that identity (new column, UTC day) + cost vs
     MAX_DAILY_GUEST_TAVILY_CREDITS (guest) / MAX_DAILY_USER_TAVILY_CREDITS (user); over -> HTTPException(429) with detail code `tavily_budget_exceeded`
     and Retry-After. If this DB query errors: log a warning and ALLOW (fail open; the global cap is the hard backstop).
   - jobs with no bound identity (nightly consolidation, radar sync) are subject only to the global cap.
   Fix `check_daily_identity_budget` so it actually filters by identity (or replace its use by the new function) and keep its tests passing.
6. Callers must degrade gracefully: read how `tavily_pipeline.py` (search ~line 187, extract ~line 833), `radar_verifier.py`, `radar_sync.py`, and the chat
   tool path call tavily and make sure BudgetExceededError / the 429 yields a normal "search capped" result or a clean 429 where a route is the direct caller,
   NEVER a 500 or a crashed SSE stream. Call `begin_run_counter()` where an agent run / tavily pipeline run starts.
7. The existing intel sub-budget (30/day, in winning_features.py) is a different in-process limiter: leave it untouched.

## Tests (NEW tests/test_tavily_budget_enforcement.py; real Postgres, stub the Tavily HTTP client so no network)
Per-run cap stops the 7th credit; guest stops at 8 and user at 30 (and admin is unlimited); one identity's usage does not block another; no-identity
jobs are only subject to the global cap; global cap and kill switch still work; identity is recorded in `tavily_usage_log`; DB error in the per-identity
query fails open with a warning; SSE stream path sees the identity; callers return a graceful result on budget errors. Existing tests must still pass.

Acceptance: all of the above, full suite green, red-check shown, gates clean.
