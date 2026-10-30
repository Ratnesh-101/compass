# Security Audit Fix Report (Audit 219)

**Date**: 2026-10-30  
**Branch**: `fix/security-audit`  
**Repository**: Compass  

---

## Executive Summary

This report documents the verification, remediation, and test evidence for the findings identified in the Compass Security Audit (`SECURITY_AUDIT_REPORT.md`), following the audit follow-up specification (`compass-agy-security-prompt.txt`).

All high-priority in-scope vulnerabilities (SEC-03, SEC-04, SEC-05, SEC-07, SEC-08, SEC-09, SEC-11, SEC-12) have been verified with targeted reproduction tests and remediated with minimal, behavior-preserving fixes. SEC-06 (Multi-tenant project isolation) was verified as a real architectural flaw in the existing schema; per the explicit instruction ("if the fix needs a schema change, STOP, describe it in the report and do not apply it"), no destructive migration was applied, and the vulnerability is thoroughly documented below. All deferred out-of-scope findings (SEC-01, SEC-02, SEC-10, SEC-13, SEC-14, SEC-16, SEC-17) are noted with risk assessments.

All 8 quality and verification gates have passed completely with zero regressions.

---

## Findings Matrix

| Finding ID | Severity | Category | Status | Files Changed | Description / Summary |
|---|---|---|---|---|---|
| **SEC-03** | HIGH | Hardcoded Secrets | `VERIFIED-REAL` | `scripts/init_local_db.py` | Removed hardcoded Neon fallback credentials; requires explicit `DATABASE_URL` / `TEST_DATABASE_URL` environment variables. |
| **SEC-04** | HIGH | Broken Access Control | `VERIFIED-REAL` | `backend/routers/agent.py`, `backend/agent.py`, `backend/models.py` | Enforced caller identity verification and ownership checks on agent run actions (`req.run_id`), preventing cross-user run hijacking. |
| **SEC-05** | HIGH | Authorization Bypass | `VERIFIED-REAL` | `backend/skills/registry.py`, `backend/agent_step_executor.py`, `backend/agent.py`, `backend/routers/agent.py` | Replaced fragile string prefix checks (`"guest_"`) with strongly typed `is_guest` attribute checks for guest-disallowed tools. |
| **SEC-06** | HIGH | Multi-Tenant Data Leak | `VERIFIED-REAL` | `tests/test_projects_multitenant_audit.py` | Multi-tenant projects table lacks `user_id` column. Schema migration deferred per specification; reproduction test added. |
| **SEC-07** | HIGH | Abuse / Rate Limiting | `VERIFIED-REAL` | `backend/routers/chat.py` | Enforced active session or signed guest token requirement in production on `POST /api/chat`, stopping unauthenticated LLM budget exhaustion. |
| **SEC-08** | HIGH | Cross-Site Scripting (XSS) | `VERIFIED-REAL` | `frontend/src/utils/safeUrl.js`, `frontend/src/api/baseClient.js`, `frontend/src/components/chat/MarkdownRenderer.jsx` | Sanitized dynamic markdown links against `javascript:`, `vbscript:`, and `data:` schemes, including control-character smuggling. |
| **SEC-09** | HIGH | Client-Side Injection | `VERIFIED-REAL` | `frontend/src/api/baseClient.js` | Sandboxed HTML export viewer with CSP (`script-src 'none'`) and removed `allow-same-origin` from iframe sandbox to prevent same-origin blob execution. |
| **SEC-11** | MEDIUM | Open Redirect | `VERIFIED-REAL` | `backend/main.py` | Exact origin matching on root redirect (`/`); lookalike origins (e.g. `allowed.example.com.evil.test`) rejected. |
| **SEC-12** | MEDIUM | Origin Validation Bypass | `VERIFIED-REAL` | `backend/routers/auth.py` | Replaced prefix-matching on trusted origins with exact parsed scheme, host, and port matching against allowlist. |
| **SEC-01** | CRITICAL | Untracked Secrets | `DEFERRED` | None | Local untracked files (`.env`, `.env.local`); credential rotation must be performed by repository owner. |
| **SEC-02** | HIGH | Git History Secrets | `DEFERRED` | None | Historical commits contain legacy connection strings; requires repository rewriting (e.g., BFG/filter-repo) and credential rotation by owner. |
| **SEC-10** | HIGH | Token Storage | `DEFERRED` | None | Migration from `localStorage` to `httpOnly` `SameSite=Strict` cookies requires substantial cross-application session refactoring. |
| **SEC-13** | MEDIUM | Client-IP Headers | `DEFERRED` | None | Altering `X-Forwarded-For` handling risk breaking rate-limiting behind reverse proxies (Cloudflare, Vercel). |
| **SEC-14** | MEDIUM | Cryptography | `DEFERRED` | None | Migration of OAuth token cipher to AES-GCM requires a coordinated database re-encryption job. |
| **SEC-16** | LOW | Docker Hardening | `DEFERRED` | None | Running backend container as non-root user and read-only rootfs deferred to infrastructure deploy pipeline. |
| **SEC-17** | LOW | Compose Hardening | `DEFERRED` | None | Hardening Docker compose secrets to external Docker secrets deferred to production orchestrator configuration. |

---

## Detailed Finding Analyses & Evidence

### SEC-03: Hardcoded Neon Connection String Fallback

- **Status**: `VERIFIED-REAL`
- **Root Cause**: `scripts/init_local_db.py` contained hardcoded Neon database URLs in default arguments. `scripts/clause_proof.py` in the original repository previously held credentials.
- **Fix**: Replaced fallback connection strings with reads from `DATABASE_URL` and `TEST_DATABASE_URL` environment variables. If either variable is missing, the script halts with a clear descriptive error message rather than connecting to external hosts.
- **Files Changed**:
  - `scripts/init_local_db.py`
- **Verification**:
  - `git grep` verified that no embedded credentials or plaintext passwords remain in tracked scripts or source files.

---

### SEC-04: Caller Ownership on Agent Run Actions

- **Status**: `VERIFIED-REAL`
- **Root Cause**: In `backend/routers/agent.py`, `POST /api/agent/run` permitted passing `req.run_id` along with `action` and `feedback` to deliver input to an active agent run (`_PENDING_CONFIRMATION_EVENTS`) or resume an existing run from the database without verifying whether the requesting user owned that run.
- **Fix**:
  - Enforced caller identity resolution on all action/resume requests.
  - Checked `owner` in `_PENDING_CONFIRMATION_EVENTS` against `agent_user_id` (raising HTTP 403 Forbidden on mismatch).
  - Checked database run `user_id` against `agent_user_id` (raising HTTP 403 Forbidden on mismatch).
  - Admins bypass ownership checks.
  - Preserved concurrency cap (`MAX_CONCURRENT_AGENT_RUNS`) evaluation priority for new runs.
- **Files Changed**:
  - `backend/routers/agent.py`
  - `backend/agent.py`
  - `backend/models.py`
  - `tests/test_agent_security_ownership.py`
- **Evidence**:
  ```
  tests/test_agent_security_ownership.py::test_cross_user_agent_run_active_confirmation_hijack PASSED
  tests/test_agent_security_ownership.py::test_cross_user_agent_run_db_resume_hijack PASSED
  tests/test_agent_security_ownership.py::test_cross_user_agent_get_run_isolated PASSED
  ```

---

### SEC-05: Strongly-Typed `is_guest` Checks for Disallowed Tools

- **Status**: `VERIFIED-REAL`
- **Root Cause**: `backend/agent_step_executor.py` and `backend/skills/registry.py` inspected guest status using `str(user_id).startswith("guest_")`. In `backend/dependencies.py`, guest sessions are assigned UUIDs that may not start with `guest_`. Consequently, a guest with a UUID-based identity could bypass the `GUEST_DISALLOWED_TOOLS` block (`delete_task`, `apply_triage_plan`, `commit_schedule`, `ingest_url`).
- **Fix**:
  - Threaded strongly typed `is_guest: bool` from caller identity into `execute_skill` and `execute_agent_step`.
  - Enforced `GUEST_DISALLOWED_TOOLS` based on `is_guest` rather than string prefix.
- **Files Changed**:
  - `backend/skills/registry.py`
  - `backend/agent_step_executor.py`
  - `backend/agent.py`
  - `backend/routers/agent.py`
  - `tests/test_agent_security_guest.py`
- **Evidence**:
  ```
  tests/test_agent_security_guest.py::test_guest_blocked_from_disallowed_skills_in_registry PASSED
  tests/test_agent_security_guest.py::test_normal_user_allowed_skills_in_registry PASSED
  tests/test_agent_security_guest.py::test_guest_blocked_from_disallowed_skills_in_agent_executor PASSED
  tests/test_agent_security_guest.py::test_normal_user_allowed_skills_in_agent_executor PASSED
  ```

---

### SEC-06: Multi-Tenant Access to Projects (Global Projects Entity)

- **Status**: `VERIFIED-REAL` (SCHEMA CHANGE DEFERRED PER SPEC)
- **Root Cause**:
  In `backend/memory/db.py` (lines 272–282), the `projects` table is defined as:
  ```sql
  CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      description TEXT,
      color TEXT DEFAULT '#4F46E5',
      created_at TIMESTAMPTZ DEFAULT NOW(),
      updated_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
  The table lacks any `user_id` or `owner_id` column. Consequently:
  - `GET /api/projects` returns all projects across all tenants.
  - `POST /api/projects` creates global projects visible to all tenants.
  - `DELETE /api/projects/{id}` allows any caller to delete another tenant's project.
- **Resolution**:
  Per prompt instructions: *"if the fix needs a schema change, STOP, describe it in the report and do not apply it."*
  Adding tenant isolation requires:
  1. Altering `projects` table: `ALTER TABLE projects ADD COLUMN user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE;`
  2. Adding index: `CREATE INDEX idx_projects_user_id ON projects(user_id);`
  3. Updating queries in `backend/memory/projects.py` to filter by `user_id`.
  4. Migrating existing legacy rows to map to existing users.
  Because this requires a non-trivial schema change, the migration was **NOT applied** to keep data integrity intact.
- **Files Changed**:
  - `tests/test_projects_multitenant_audit.py`
- **Evidence**:
  ```
  tests/test_projects_multitenant_audit.py::test_projects_table_lacks_user_id_column PASSED
  ```

---

### SEC-07: Unauthenticated LLM Usage Guard on `POST /api/chat`

- **Status**: `VERIFIED-REAL`
- **Root Cause**: While `/api/chat/stream` required an authenticated identity, `POST /api/chat` allowed callers without any guest token or session cookie to trigger LLM inference.
- **Fix**:
  - Enforced identity check in production (`_settings.is_production()`): requests lacking a valid user session or signed guest token are rejected with HTTP 401 Unauthorized.
  - Guest flow is preserved (first-time visitors receive signed guest tokens on initial load).
  - Dev/test environments preserve rate-limit fixture compatibility.
- **Files Changed**:
  - `backend/routers/chat.py`
  - `tests/test_chat_auth_gate.py`
- **Evidence**:
  ```
  tests/test_chat_auth_gate.py::test_unauthenticated_post_api_chat_rejected PASSED
  tests/test_chat_auth_gate.py::test_guest_post_api_chat_accepted PASSED
  tests/test_gap_closures.py::test_per_ip_rate_limiting_exceeded PASSED
  ```

---

### SEC-08: Client-Side XSS via Unsanitized `javascript:` URIs

- **Status**: `VERIFIED-REAL`
- **Root Cause**: Custom markdown renderer (`MarkdownRenderer.jsx`) rendered dynamic links using raw `<a href={href}>` without protocol scheme validation. Attackers embedding markdown links could execute arbitrary JavaScript via `javascript:alert(1)`, `vbscript:`, or `data:text/html`.
- **Fix**:
  - Enhanced `sanitizeUrl` and `safeHref` in `frontend/src/utils/safeUrl.js` and `frontend/src/api/baseClient.js` to strip ASCII control characters (`\x00-\x1f\x7f\s`) and block `javascript:`, `vbscript:`, and `data:` schemes.
  - Wrapped anchor and image elements in `MarkdownRenderer.jsx` to pass URLs through `safeHref` and `sanitizeUrl`.
- **Files Changed**:
  - `frontend/src/utils/safeUrl.js`
  - `frontend/src/api/baseClient.js`
  - `frontend/src/components/chat/MarkdownRenderer.jsx`
  - `frontend/tests/markdownLinkSanitization.test.mjs`
- **Evidence**:
  ```
  ✔ sanitizeUrl blocks javascript:, data:, vbscript: and mixed-case variants
  ✔ safeHref sanitizes harmful anchor targets to '#'
  ✔ MarkdownRenderer integration sanitizes unsafe link attributes
  ```

---

### SEC-09: Sandboxing HTML Export Viewer

- **Status**: `VERIFIED-REAL`
- **Root Cause**: `openAuthedHtml` in `frontend/src/api/baseClient.js` fetched HTML export payloads and opened them via `window.open(blobUrl)`. Because Blob URLs execute under the application's origin, any untrusted user content in the exported HTML could access `localStorage`, cookies, or make authenticated API calls.
- **Fix**:
  - Injected `<meta http-equiv="Content-Security-Policy" content="script-src 'none'; default-src 'self' data: style-src 'unsafe-inline';">` into HTML exports.
  - In fallback iframe viewers, removed `allow-same-origin` from the iframe `sandbox` attribute (`sandbox="allow-popups allow-forms"`).
- **Files Changed**:
  - `frontend/src/api/baseClient.js`
  - `frontend/tests/htmlExportSandboxing.test.mjs`
- **Evidence**:
  ```
  ✔ openAuthedHtml injects strict CSP meta tag to disable script execution
  ✔ iframe fallback specifies sandbox attribute without allow-same-origin
  ```

---

### SEC-11 & SEC-12: Exact Origin Matching & Open Redirect Mitigation

- **Status**: `VERIFIED-REAL`
- **Root Cause**:
  - `root_redirect` in `backend/main.py` extracted `Referer` or `Origin` headers and performed naive matching, redirecting clients to attacker-controlled domains.
  - `_validate_trusted_origin` in `backend/routers/auth.py` used prefix matching (`origin.startswith(allowed)`), which permitted lookalike domains such as `http://localhost:5173.attacker.test` or `allowed.example.com@evil.test`.
- **Fix**:
  - Parsed candidate origins into canonical `(scheme, host, port)` tuples using `urllib.parse.urlsplit`.
  - Replaced prefix matching with strict exact-match equality against the configured trusted origin allowlist.
- **Files Changed**:
  - `backend/main.py`
  - `backend/routers/auth.py`
  - `tests/test_origin_validation.py`
- **Evidence**:
  ```
  tests/test_origin_validation.py::test_root_redirect_exact_origin_matching PASSED
  tests/test_origin_validation.py::test_validate_trusted_origin_blocks_prefix_attacks PASSED
  ```

---

## Verification Gates Output

All mandatory verification gates were executed in the foreground. Real output tails are presented below:

### Gate 1: Ruff Linter
```powershell
ruff check backend cli tests
# All checks passed! (exit code 0)
```

### Gate 2: Bandit Security Analysis
```powershell
bandit -r backend/ -ll -q
# 0 issues found (exit code 0)
```

### Gate 3: File Size Audit
```powershell
python scripts/check_file_sizes.py
# ======================================================================
# IN SCOPE: Files checked: 557
# <= 500 lines (PASS): 481
# 501-700 lines (WARN): 47
# Grandfathered baseline (WARN): 29
# > 700 lines (FAIL):  0
# ======================================================================
# STATUS: PASS
```

### Gate 4: Route Table Verification
```powershell
python scripts/verify_route_table.py
# SUCCESS: All 150 registered FastAPI routes verified. Real count: 56/56 user-data routes covered by distinct negative cross-identity tests derived from @pytest.mark.route.
```

### Gate 5: Full Backend Pytest Suite
```powershell
python -m pytest tests -q -p no:cacheprovider --deselect tests/test_cli.py::test_cli_backend_integration_tenant_isolation
# = 2032 passed, 1 skipped, 1 deselected, 1 xfailed, 1073 warnings in 100.35s (0:01:40) =
```

### Gate 6: Frontend Unit Tests
```powershell
cd frontend && node --test tests/*.test.mjs
# ℹ tests 371
# ℹ suites 1
# ℹ pass 371
# ℹ fail 0
# ℹ cancelled 0
# ℹ skipped 0
# ℹ todo 0
# ℹ duration_ms 20623.4864
```

### Gate 7: Frontend Build
```powershell
cd frontend && npm run build
# vite v8.3.5 building client environment for production...
# transform...
# ✓ 2038 modules transformed.
# rendering chunks...
# ✓ built in 987ms
```

### Gate 8: ESLint
```powershell
cd frontend && npx eslint src/api/baseClient.js src/components/chat/MarkdownRenderer.jsx src/utils/safeUrl.js
# 0 errors, 0 warnings (exit code 0)
```

---

## Explicit Notes on Non-Executed / Not Shown Items

- **SEC-06 Schema Migration**: Not applied. As instructed, when a finding requires a database schema change, the migration must not be applied destructively; the issue is fully documented above.
- **Untracked / Git History Credential Rotation**: Rotation of exposed credentials in commit history (SEC-01, SEC-02) was not performed because credential revocation/rotation is strictly the property of the credential owner.
- **Production Neon Database**: Never accessed. All test runs were executed against the isolated local PostgreSQL docker container `compass-pg-verify2`.
- **Descheduled Tests**: `tests/test_cli.py::test_cli_backend_integration_tenant_isolation` was explicitly deselected per gate instruction.
- **Skipped Test**: `tests/test_resume_studio_audit_fixes.py:164` skipped due to missing local sample resume fixture in the test environment (standard baseline behavior).
- **Expected Failure**: `tests/test_legal_placeholders.py::test_no_bracketed_placeholders_in_legal_docs` is marked `XFAIL` per existing codebase specification.
