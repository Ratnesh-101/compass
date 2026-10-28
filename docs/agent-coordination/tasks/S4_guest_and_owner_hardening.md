# Task S4 - scope_owner and guest-token hardening

- Worktree: <local path>   Branch: agent/sonnet/guest-and-owner-hardening   Base: d0a4c31
- Test script: bash "<local path>" "<worktree with forward slashes>" [pytest args]
- May edit: backend/services/ownership.py, backend/dependencies.py, tests/test_ownership_helpers.py (created by step 0), NEW tests/test_guest_token_hardening.py,
  and existing tests only where a deliberate behavior change requires it (say which in the report).
- Must NOT edit: anything else. Another worker (S1) adds a middleware in main.py that CALLS `_get_current_identity`; do not change that function's signature or return type.

## Step 0
Run `git merge --no-edit agent/sonnet/ownership-helper-tests` in your worktree (a local test-only branch adding tests/test_ownership_helpers.py, 31 tests).
Confirm the merge added only that file and the suite still passes before you change anything.

## A. `scope_owner` whitespace-only owner
`backend/services/ownership.py::scope_owner` returns None for None/""/"admin" (meaning "unscoped": admin or internal call) and the stripped id otherwise. A whitespace-only
string like "   " is truthy and not "admin", so it currently returns "" (empty string). Callers (calendar handlers, agent_critic, etc.) use `if scoped_owner` / SQL
`($n IS NULL OR lower(user_id) = lower($n))`, so "" is falsy in Python (skips the ownership check) and matches nothing in SQL: inconsistent and unsafe by accident.
Required: a non-empty-but-blank owner must FAIL CLOSED everywhere. Return a reserved never-matching owner constant (document it, e.g. `NO_OWNER = "\x00no-owner"`), keep
None/""/"admin" -> None exactly as today, and update the pinned test in tests/test_ownership_helpers.py (it currently asserts scope_owner("   ") == ""). Grep every caller of
scope_owner and confirm none relies on a falsy result for blank input; add a test through one real route/skill path showing a blank owner can read/write nothing.

## B. `x-guest-id` with an expired or invalid guest token returns 403 in production
In `backend/dependencies.py::_get_current_identity` (around lines 268-314), a request carrying `x-guest-id: <uuid>` plus an expired/invalid `x-guest-token` raises 403
("Raw x-guest-id impersonation ...") in production instead of being treated as anonymous, so a stale browser session gets a confusing 403 and the frontend cannot re-mint.
Required: expired or invalid token -> treat the caller as unauthenticated (protected routes return 401, which the frontend already handles by re-minting). KEEP the 403 for the
real impersonation case: a VALID token for guest A together with an `x-guest-id` naming a different guest B. Read the code and the existing tests (tests/test_auth_bypass_gates.py,
tests/test_security_hardening.py, tests/test_cross_identity_coverage.py) first; do not weaken any of their assertions.

## C. Legacy two-part guest tokens (`<uuid>.<hmac>`, no timestamp)
DECISION from the user: leave them working. Only add one `logger.warning` per process the first time a legacy-format token is accepted (module-level flag), so the
operator can see if they are still in use. No behavior change; add a test for the one-time log.

## Tests
New tests/test_guest_token_hardening.py for B and C (use the existing helpers `generate_guest_token`, `create_session` as the other tests do; for an expired token build one with an old
timestamp using the same signing helper). Each new test must fail on the old code (except the C log test, which can only be shown to fail by import/absence - say so).

Acceptance: full suite green, red-check shown, gates clean.
