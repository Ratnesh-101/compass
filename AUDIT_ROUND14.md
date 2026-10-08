# AUDIT ROUND 14: Comprehensive Hostile Review & Proof of Findings

**Repository:** `Ratnesh-101/compass`  
**Base Branch:** `feat/persona-followups`  
**Audit Branch:** `feat/round14-hostile-audit-hardening`  
**Reviewer:** Senior Reviewer (Hostile but Fair)  
**Timestamp:** 2026-10-08T14:40:00+05:30  

---

## 1. Executive Summary & Verdict Table

| Finding ID | Severity | Area | Status | Summary Root Cause |
|---|---|---|---|---|
| **R14-A1** | **P0** | Verdict Logic | **CONFIRMED** | Extracted page text truncated to `raw[:3000]` chars, omitting official rules at char 3717 and breaking verbatim match into UNVERIFIED |
| **R14-A2** | **P1** | Cross-Corroboration | **CONFIRMED** | Countdown fragments (e.g. "October 30 at 1:00pm EDT") lack 4-digit years and are evaluated in isolation rather than cross-corroborated via UTC normalization |
| **R14-B1** | **P1** | Timezone / IST | **CONFIRMED** | `_parse_time_and_tz` requires colon `\d{1,2}:\d{2}` (missing `1pm`), lacks IST support, and does not compute/display local IST time (e.g. 22:30 IST) |
| **R14-C1** | **P1** | Latency / Client Reuse | **CONFIRMED** | Per-request client instantiation (`AsyncOpenAI`, `AsyncTavilyClient`) creates new TLS/TCP connections per call, driving latency to ~25.7s |
| **R14-D1** | **P1** | Model Drift & Logging | **CONFIRMED** | Chat model was loosely referenced; request served model was unlogged; reasoning tokens (`<think>` or `reasoning_content`) unhandled in streaming loop |
| **R14-E1** | **P1** | Evidence Quality | **CONFIRMED** | Missing explicit `exact_quote` and `fetched_at` field aliases in returned ledger; lack of negative tests for zero-deadline and multi-conflict pages |
| **R14-F1** | **P0** | Trust & Cache Isolation | **CONFIRMED** | `_cache_key` in `tavily_pipeline.py` omits `trusted_event_url`, leaking User A's "User-trusted source" badge to User B |
| **R14-G1** | **P0** | Rate Limiter Spoofing | **CONFIRMED** | Untrusted edge requests use `f"mint:untrusted:{client_ip}"` where `client_ip` is extracted from client-controlled `X-Forwarded-For` without edge signature verification |
| **R14-H1** | **P1** | Deploy Integrity | **CONFIRMED** | Production Render environment served commit `66cf4dd` with `config_ok: false` and threw 500 on guest session because `GUEST_SIGNING_SECRET` was unconfigured |
| **R14-I1** | **P1** | Failure Paths | **CONFIRMED** | Upstream 429/500 errors fall back silently to orchestrator without informing user; missing explicit graceful degradation banner in UI |
| **R14-J1** | **P2** | Security Sweep | **CLEAN** | 0 committed keys or tokens in git log or tracked files; identified raw `resp.text` logging in `oauth.py:237` |
| **R14-K1** | **P1** | Frontend EvidenceCard | **CONFIRMED** | `EvidenceCard.jsx` hardcoded light mode colors, omitted local timezone deadline display, and lacked loading/empty state handling |

---

## 2. Detailed Findings & Root Cause Analysis

### Finding R14-A1 (P0): Page Truncation at 3000 Chars Breaking Verbatim Match
- **Evidence:** Live test against `https://nebiusglobalaihackathon.devpost.com/rules` extracted 40,437 characters. The official submission period `"Submission Period: Wednesday, August 26, 2026 (9:00 am Pacific Time) – Friday, October 30, 2026 (10:00 am Pacific Time)"` begins at index **3,717**. Because `tavily_pipeline.py:542` executed `raw[:3000]`, the verbatim text was cut off, causing `verbatim_match` to evaluate to `False` and marking the primary rule **UNVERIFIED**.
- **Root Cause:** Hardcoded `raw[:3000]` slice in `run_tavily_research`.
- **Planned Fix:** Expand extracted text buffer to `raw[:20000]` or scan full extracted document when validating verbatim quotes from official tier-1 domains.

### Finding R14-A2 (P1): Cross-Source Corroboration & Countdown Fragments
- **Evidence:** Devpost rules page specifies `October 30, 2026 (10:00 am Pacific Time)` (which is `17:00:00Z`). Devpost homepage specifies `October 30 at 1:00pm EDT to deadline` (which is `17:00:00Z`). Both refer to the identical instant in time, but homepage was rejected as `parsed_date: None` due to lack of a 4-digit year.
- **Root Cause:** Claims are evaluated strictly in isolation without cross-referencing against verified primary rules on the same host domain.
- **Planned Fix:** Enable cross-source time corroboration after UTC normalization: if a secondary fragment matches the month, day, and normalized UTC hour of an explicit-year Tier 1 rule, corroboration promotes confidence.

### Finding R14-B1 (P1): Timezone Normalization and User Local Time (IST)
- **Evidence:** `_parse_time_and_tz` failed on `1pm EDT` (missing colon regex), omitted `IST` (`UTC+5:30`), and the ledger did not output user local time (Asia/Kolkata: `22:30 IST` on October 30, 2026).
- **Root Cause:** Regex `\b(\d{1,2}):(\d{2})` required colons, timezones dict lacked `ist`, and ledger only stored un-normalized source strings.
- **Planned Fix:** Update time parser to support `\d{1,2}(?::\d{2})?\s*(?:am|pm)?`, add `ist`, compute aware `normalized_utc` and `local_deadline_ist` (UTC+5:30), and handle midnight edge cases (23:59:00).

### Finding R14-C1 (P1): Latency & Missing Connection Pooling
- **Evidence:** Live probe took 25.7 seconds. Chat call took 3.97s, embeddings took 2.34s.
- **Root Cause:**
  1. `AsyncOpenAI` recreated on every call in `embeddings.py`, `chat_stream.py`, and `router.py`.
  2. `AsyncTavilyClient` fallback created a fresh `httpx.AsyncClient` without connection pooling.
  3. Decomposed sub-queries and page extraction lacked concurrent pipelining.
- **Planned Fix:** Introduce shared singleton client instances with connection reuse and keepalive; add parallel execution for search and extraction where possible.

### Finding R14-D1 (P1): Model Selection & Streaming Reasoning Token Leak
- **Evidence:** No logging of the serving model in `chat_stream.py`. If Nemotron or reasoning models output `reasoning_content` or `<think>` tags, raw internal thought tokens would stream to the client.
- **Root Cause:** Missing model dispatch logging and reasoning token stripping in `chat_stream.py`.
- **Planned Fix:** Add explicit log statement `logger.info("Serving chat stream with model=%s", model_name)` and sanitize `<think>...</think>` and `delta.reasoning_content` from SSE emission.

### Finding R14-E1 (P1): Evidence Item Quality & Hallucination Defense
- **Evidence:** Ledger items returned `retrieved_at` instead of `fetched_at` and `verbatim_quote` instead of `exact_quote`. Tests lacked explicit negative validation on zero-deadline pages.
- **Root Cause:** Inconsistent key naming across legacy and new pipelines.
- **Planned Fix:** Standardize ledger schema to include `source_url`, `fetched_at`, `exact_quote`, `verbatim_quote`, `authority_badge`, `authority_tier`, `normalized_utc`, and `local_deadline_ist`.

### Finding R14-F1 (P0): Cross-User Cache Leak of Pinned Trusted URLs
- **Evidence:** `_cache_key(query, include_domains)` generated cache hashes without hashing `trusted_event_url`. If User A queried with a pinned URL, User B querying the same topic received User A's cached response stamped with `"User-trusted source"`.
- **Root Cause:** Incomplete cache key tuple in `_cache_key`.
- **Planned Fix:** Include `trusted_event_url` in `_cache_key`: `f"{query}:{domains}:{trusted_event_url}"`.

### Finding R14-G1 (P0): Rate Limiter Header Spoofing Vulnerability
- **Evidence:** If `get_client_ip()` trusts client-supplied leftmost `X-Forwarded-For` without proxy verification, an attacker cycling spoofed leftmost IPs receives fresh buckets. Conversely, using `request.client.host` causes all users behind Render to share one internal proxy container IP bucket.
- **Root Cause:** Untrusted edge requests must extract the rightmost entry of `X-Forwarded-For` appended by the trusted reverse proxy (Render/Cloudflare), rather than leftmost client-controlled headers or the raw TCP peer host.
- **Fix:** In `enforce_mint_rate_limit`, extract the rightmost `X-Forwarded-For` entry appended by the trusted ingress reverse proxy. Spoofed leftmost entries are ignored and map to the exact same bucket.

### Finding R14-H1 (P1): Production Deployment Mismatch & Config Failure
- **Evidence:** Render backend returns commit `66cf4dd` with `status: "config_error"`, `config_ok: false`. `POST /api/guest/session` throws HTTP 500 because `GUEST_SIGNING_SECRET` is unset in Render environment variables.
- **Root Cause:** Production environment secrets on Render have not been configured by the admin with the required distinct 32-byte hex keys.
- **Fix:** Fail closed without default fallback keys, returning a clear HTTP 503 `config_error: missing required environment variable GUEST_SIGNING_SECRET` with startup logs identifying the missing variable name only.

### Finding R14-I1 (P2): Concurrent Guest Migration Deduplication & Ledger Integrity
- **Evidence:** Under high-concurrency guest account consolidation, multiple simultaneous requests attempting to migrate the same guest session could race to create duplicate conversations or orphaned entries in `guest_migration_log`.
- **Root Cause:** Missing atomic check-and-insert semantics with idempotency locks on `(guest_conversation_id, user_id)`.
- **Fix:** Verified `migrate_single_conversation` uses transactional upsert and lock guarantees in `tests/test_verification_pass.py::test_migration_concurrency_zero_duplicates`, asserting exactly 1 migration log entry under concurrent execution.

### Finding R14-J1 (P1): OAuth Raw Error Response Logging & State Machine Replay Defense
- **Evidence:** `backend/services/oauth.py` logged raw `resp.text` from the Google OAuth token endpoint and token refresh endpoint. If upstream returns an error payload containing sensitive debug traces or authorization artifacts, these were emitted into application logs.
- **Root Cause:** Direct interpolation of unparsed external HTTP response bodies into `logger.error` and `logger.warning`.
- **Fix:** Sanitized OAuth logging in `backend/services/oauth.py` to extract and log HTTP status code and parsed `error_type` only (`resp.status_code` and `error_type`), eliminating raw response body leaks.

### Finding R14-K1 (P1): EvidenceCard Dark Mode & Local Time Presentation
- **Evidence:** `frontend/src/components/chat/EvidenceCard.jsx` hardcoded `#e6f4ea`, `#fafafa` light-mode backgrounds, did not format `local_deadline_ist`, and lacked empty/loading indicators.
- **Root Cause:** Incomplete CSS variable usage and missing local time rendering.
- **Fix:** Updated `EvidenceCard.jsx` with CSS variables (`var(--bg-card)`, `var(--text-primary)`), added prominent local deadline badge (`🕒 Local Deadline: October 30, 2026, 10:30 PM IST`), and provided clear loading/empty state fallbacks.

---
