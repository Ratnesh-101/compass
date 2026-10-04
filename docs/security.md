# Compass — Security Architecture & Threat Model

## 1. Overview & Threat Model

Compass is an agentic AI assistant designed to maintain persistent memory across tasks, hackathon deadlines, coursework, code contexts, and conversations. Because it interacts with the live web, external LLM APIs, and a persistent PostgreSQL database, robust defensive boundaries are required against malicious inputs, SSRF, IDOR, and unauthorized mutations.

### Assets to Protect
1. **Persistent Task Store (`tasks`)**: User deadlines, hackathon deliverables, and schedules.
2. **Long-Term Vector Memory (`memory_chunks`)**: 768-dimensional embeddings and contextual text.
3. **Calendar OAuth Credentials (`calendar_connections`)**: Google Calendar refresh tokens stored encrypted at rest.
4. **Agent State & Audit Logs (`agent_runs`, `agent_audit_log`)**: Traces of autonomous decisions, proposed mutations, and reversibility logs.
5. **External Quotas & Costs**: Nebius LLM token quotas and Tavily search API quotas.

### Threat Actors
- **Anonymous Internet User**: Can send HTTP requests to public endpoints without credentials.
- **Malicious Workspace User**: May attempt to query, mutate, or delete another user's tasks or calendar events (IDOR).
- **Adversarial Web Content (Prompt Injection / Indirect Injection)**: External web pages or search results containing prompt-injection payloads intended to coerce the LLM into executing unintended actions.
- **SSRF Exploitation**: Attempts to force server-side web ingestion tools to scan internal IP addresses or cloud metadata endpoints.

### Trust Boundaries

```text
Untrusted Internet (Browser / Client / Web Pages)
                     │
                     ▼ [CORS & Rate Limiting: 30 req/min]
       FastAPI Router & Dependency Layer
                     │
                     ▼ [verify_token / Constant-time HMAC]
       Protected Services & Specialist Agent
                     │
                     ▼ [SSRF Validator & Input Sanitizer]
      External Services (Tavily / Google OAuth)
                     │
                     ▼ [Confirm Gate: Zero DB write prior to approval]
       PostgreSQL / Neon pgvector Database
```

---

## 2. Attack Surface: Endpoint Security Matrix

| Endpoint | Method | Public / Auth | Mutates State | External Calls | Sensitive Data | Rate Limited | Risk Level |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `/api/chat` | POST | Public | No (Gated) | Nebius LLM | Conversation context | Yes (30/min) | Medium |
| `/api/chat/stream` | POST | Public | No (Gated) | Nebius LLM | Conversation context | Yes (30/min) | Medium |
| `/api/agent/run` | POST | Public | No (Gated) | Nebius / Tavily | Agent execution trace | Yes (10/min) | Medium |
| `/api/agent/confirm` | POST | Bearer (`AUTH_TOKEN`) | Yes | PostgreSQL | Task/Memory state | Yes (30/min) | High |
| `/api/agent/undo` | POST | Bearer (`AUTH_TOKEN`) | Yes | PostgreSQL | Restores state | Yes (30/min) | High |
| `/api/agent/trigger-nightly` | POST | Bearer (`AUTH_TOKEN`) | Yes | Nebius / DB | Full task state | Yes | High |
| `/api/tasks` | GET | Public (Scoped) | No | PostgreSQL | Tasks by account | Yes (30/min) | Low |
| `/api/tasks` | POST | Public (Scoped) | Yes | PostgreSQL | Task creation | Yes (30/min) | Medium |
| `/api/tasks/{task_id}` | PATCH / PUT | Owner / Admin | Yes | PostgreSQL | Task modifications | Yes (30/min) | High |
| `/api/tasks/{task_id}` | DELETE | Owner / Admin | Yes | PostgreSQL | Task deletions | Yes (30/min) | High |
| `/api/agent/runs` | GET | Public | No | PostgreSQL | Execution history | Yes (30/min) | Low |
| `/api/calendar/auth-url` | GET | Public | No | Google OAuth | Auth URL | Yes | Low |
| `/api/calendar/callback` | GET | Public | Yes (encrypted) | Google API | Refresh token (AES/HMAC) | Yes | High |
| `/api/usage/summary` | GET | Public | No | PostgreSQL | Token costs | Yes (30/min) | Informational |
| `/health` | GET | Public | No | PostgreSQL ping | Uptime status | No | Informational |

---

## 3. Security Controls Implemented

### 1. Direct Task Creation & Guest Workspace Isolation (Option B)
- **Supported Architecture**: Compass intentionally supports public and guest demo workspaces so prospective users and evaluators can experience the product without mandatory login friction.
- **Server-Side Identity Binding**: When an anonymous or guest caller creates a task via `POST /api/tasks`, the server never leaves ownership unassigned (`NULL`). Instead, `_get_or_create_user_id(request)` binds the task to:
  1. The explicit `x-user-id` header (if provided, e.g. `anon_abc123`).
  2. The `compass_session` or `compass_user_id` cookie.
  3. A deterministic, collision-resistant guest identity derived from client IP: `guest_{sha256(ip)[:12]}`.
- **Cross-Guest Isolation**:
  - `GET /api/tasks` queries are scoped to the requesting guest identity; Guest B cannot view Guest A's tasks.
  - `PATCH /api/tasks/{task_id}` and `DELETE /api/tasks/{task_id}` enforce strict ownership checks; Guest B cannot modify or delete Guest A's tasks (`HTTP 403 Forbidden`).
  - Unowned or legacy system tasks (`user_id = NULL`) cannot be modified or deleted by non-admin users (`HTTP 403 Forbidden`).
- **Abuse Prevention**: `POST /api/tasks` is protected by a 30 req/min sliding-window rate limiter, and task titles are validated to a maximum of 500 characters.

### 2. Confirmation Gate Integrity & Replay Protection (`/api/agent/confirm`)
- **Bearer Authentication Required**: `/api/agent/confirm` is not public; it requires `Authorization: Bearer <AUTH_TOKEN>`.
- **Server-Side Proposal Retrieval**: The server retrieves the original agent proposal directly from `agent_runs` using `req.run_id`.
- **Tampering Defense**: If the client supplies an action list, the server verifies that every submitted action strictly matches a proposed tool call recorded on that run. Unproposed actions are rejected with `HTTP 400 Bad Request`.
- **Replay Protection**: Upon execution, pending actions are cleared on the persisted agent run. Any subsequent attempt to re-confirm that run is rejected with `HTTP 400 Bad Request` ("replay rejected").

### 3. Undo Integrity & Replay Protection (`/api/agent/undo`)
- **Bearer Authentication Required**: `/api/agent/undo` requires valid Bearer authentication.
- **Audit Log Verification**: Reversions are executed against `agent_audit_log` records containing exact pre-mutation state snapshots.
- **Replay Protection**: The database marks `is_reverted = TRUE` atomically upon reversion. Subsequent undo requests for the same action return an error (`Action #X has already been reverted`).

### 4. Fail-Closed Authentication & Constant-Time Verification
- **Constant-Time Verification**: `backend.dependencies.verify_token` uses `hmac.compare_digest` to prevent side-channel timing attacks when validating Bearer tokens.
- **Production Fail-Closed**: In production (`ENVIRONMENT="production"`), the application strictly refuses to start or validate requests if `AUTH_TOKEN` is blank or set to default development tokens (`dev-token`).

### 5. Cryptographic Secret Management & Token Encryption
- **Key Derivation**: Google OAuth tokens stored in `calendar_connections` are encrypted using authenticated symmetric stream encryption (HMAC-SHA256 keystream + integrity tag).
- **Production Key Enforcement**: In production, `TOKEN_ENCRYPTION_KEY` must be explicitly configured with a secret key; the development fallback key (`compass_secure_local_dev_token_encryption_key_32bytes!`) is rejected with a configuration error.

### 6. Server-Side Request Forgery (SSRF) Protection
- **URL Ingestion Filter**: `backend.services.security.is_safe_url` strictly validates URLs before fetching:
  - Disallows loopback addresses (`127.0.0.0/8`, `::1`).
  - Disallows AWS/GCP/Azure cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
  - Disallows RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
  - Disallows private/reserved IPv6 networks (`::1`, `fc00::/7`, `fe80::/10`) and unwraps IPv4-mapped IPv6 addresses (`::ffff:127.0.0.1`).
  - Restricts schemes strictly to `http` and `https`, and ports to standard web ports (80, 443, 8080, 8443).
- **Safe Redirect Validation**: `is_safe_redirect(source_url, location)` resolves relative and absolute redirects and validates that the destination does not point to internal or private addresses.

### 7. Strict CORS Policy
- Wildcard CORS (`allow_origins=["*"]`) combined with credentials has been removed.
- Cross-origin requests are strictly restricted to configured origins in `settings.CORS_ORIGINS` (Vercel deployment domains, local development ports 5173/3000, and Nebius app domains).

### 8. Rate Limiting & Spoofing Resistance
- **Sanitized Client IP**: Rate limiters in `backend.dependencies` extract client IP through `get_client_ip()`, preventing bypasses via forged, prepended `X-Forwarded-For` headers.
- **Dual-Tier Limits**:
  - Chat, memory, and task endpoints: 30 requests/minute per IP.
  - Agent runs: 10 runs/minute per IP.

---

## 4. Security Changelog

### Phase 2 Security Hardening
- Added `backend/services/security.py` providing SSRF validation (`is_safe_url`), IPv4-mapped IPv6 handling, safe redirect checking (`is_safe_redirect`), and safe client IP extraction (`get_client_ip`).
- Updated `backend/config.py` with `ENVIRONMENT` setting and `validate_production_secrets()` enforcing fail-closed behavior for `AUTH_TOKEN` and `TOKEN_ENCRYPTION_KEY`.
- Updated `backend/dependencies.py` to use `hmac.compare_digest` and fail-closed checks on `verify_token`, and added `_get_or_create_user_id` for deterministic guest workspace binding.
- Hardened `backend/main.py` CORS middleware to use `settings.CORS_ORIGINS`.
- Added SSRF defense to `handle_ingest_url` in `backend/skills/handlers/web.py`.
- Enforced IDOR ownership checks on `PATCH` and `DELETE` in `backend/routers/tasks.py` and protected unowned tasks against unauthorized modification.
- Hardened `backend/routers/agent.py` `/confirm` endpoint with proposal verification and replay protection.
- Added 28 regression tests in `tests/test_security_hardening.py`.

---

## 5. Known Limitations & Architecture Notes

1. **In-Memory Rate Limiting**: The current rate limiter uses an in-memory sliding window deque. In multi-worker or multi-container horizontal deployments, rate limits apply per worker process rather than globally across the cluster. A distributed Redis/Valkey store can be plugged into `dependencies.py` if scaling horizontally.
2. **Public Interactive Endpoints by Design**: `/api/chat`, `/api/chat/stream`, `/api/agent/run`, and `POST /api/tasks` remain public by design without mandatory Bearer authentication to support guest demo workspaces. State mutations are protected by deterministic workspace isolation, the confirmation gate, and per-account ownership boundaries.
3. **Client-Scoped Workspace Identifier (`x-user-id`)**: `x-user-id` is an unsigned client-scoped workspace identifier rather than a cryptographic JWT; this is an intentional design trade-off for zero-friction guest evaluation. It provides guest workspace partitioning, not user identity authentication.
4. **DNS Rebinding & TOCTOU**: Pre-fetch validation in `is_safe_url` resolves DNS hostnames to verify that IP addresses do not point to internal subnets. However, because external web extraction is performed via the Tavily SaaS API, Tavily independently re-resolves the domain name. This external SaaS architecture inherently isolates Compass's internal network from direct network connections during web extraction.
5. **Indirect Prompt Injection**: While web content is fenced with `[UNTRUSTED WEB CONTENT]` tags and screened with regex heuristics, complex adversarial LLM jailbreaks in ingested content remain an active industry-wide research problem. The primary defensive barrier is the hard confirm-gate preventing autonomous execution without human review.
