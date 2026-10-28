# Task S2 - Pin the resolved IP in the opportunity verifier (DNS rebinding)

- Worktree: <local path>   Branch: agent/sonnet/verifier-dns-pinning   Base: d0a4c31
- Test script: bash "<local path>" "<worktree with forward slashes>" [pytest args]
- May edit: backend/services/radar_verifier.py, backend/services/security.py (ONLY add a new function / small refactor of safe_http_get; keep its existing signature and behavior),
  tests/test_audit_release_readiness_p1_p2.py, tests/test_career_e2e_workflow.py, tests/test_career_profile_intelligence.py, tests/test_radar_broad_discovery.py,
  tests/test_radar_verification_hardening.py, tests/conftest.py (ONLY the autouse fixture `_offline_tolerant_ssrf_dns`), NEW tests/test_verifier_dns_pinning.py.
- Must NOT edit: anything else.

## Problem (verified)
`verify_opportunity_status` in backend/services/radar_verifier.py fetches discovered URLs with `httpx.AsyncClient`, manually following redirects and checking
each hop with `is_safe_url` / `is_safe_redirect`. Those checks resolve DNS once, then httpx resolves again at connect time, so a hostname that resolves to a public
address at check time and to a private/loopback/metadata address at connect time (DNS rebinding) is still reachable. The repo already has
`backend/services/security.py::safe_http_get(url, max_redirects, timeout, headers) -> (status, text, headers)` which resolves once, rejects non-global IPs,
and connects to the pinned IP with SNI (verify=True), but it does not return the FINAL url after redirects, which the verifier needs (it judges the landing page).

## Required behavior
1. Add to security.py a sibling `safe_http_get_with_url(...)` returning `(status, text, headers, final_url)` (implement `safe_http_get` as a thin wrapper
   over it so its existing callers/tests are unchanged).
2. Use it in `radar_verifier.py` in place of the manual httpx loop. Preserve ALL existing decisions: 404/410 -> CLOSED_CONFIRMED; >=400 -> retain status;
   content analysis; judging official_source/specific_ats/generic on the FINAL url; internal/blocked URLs never fetched -> retain status with an evidence message
   containing "not fetched"; too many redirects / SSRF-blocked redirect / connection failure -> retain status with a "failed"/"stopped" style message
   (look at tests/test_radar_verification_hardening.py and the other radar tests for the exact wording they assert).
3. A ValueError from safe_http_get (SSRF blocked, unresolved host, too many redirects) must be turned into the same "retain current status" result, never an exception.
4. Update the four test files that mock `httpx.AsyncClient.get` for the verifier so they mock the new fetch function instead (patch the name where it is used:
   `backend.services.radar_verifier.safe_http_get_with_url`). Keep every assertion's intent. Update the `_offline_tolerant_ssrf_dns` fixture in tests/conftest.py
   so verifier tests stay hermetic (no real DNS/network).
5. New tests/test_verifier_dns_pinning.py: (a) a host that resolves to a public IP on the first lookup and a private IP on the second is never contacted at the
   private address (prove the connection goes to the pinned first IP - stub `loop.getaddrinfo` and the httpx send); (b) a host resolving to loopback/RFC1918/
   169.254.169.254 is rejected; (c) redirect to an internal host is blocked; (d) the final URL is returned and used for judging.
6. Manual smoke (report the literal output, do not put it in tests): one real `await safe_http_get_with_url("https://example.com/")` call from a python one-liner
   to prove HTTPS with the pinned IP still validates the certificate. If the network is unavailable, say so.

Acceptance: full suite green, new tests fail on old code, gates clean.
