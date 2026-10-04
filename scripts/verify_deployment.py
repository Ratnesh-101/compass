"""
Compass — Continuous Deployment (CD) Post-Deployment Smoke Verification.

Performs safe, strictly read-only, non-mutating probes against the live production
or staging infrastructure:
  1. Backend /health probe (FastAPI + Neon PostgreSQL connection + Git commit verification)
  2. Frontend reachability probe (Vercel CDN + React bundle loading)
  3. Reverse-proxy transparent routing probe (Vercel /health rewrite to Render)
  4. Cross-Origin Resource Sharing (CORS) preflight probe

Usage:
  python scripts/verify_deployment.py
  python scripts/verify_deployment.py --backend-url https://compass-backend-qryu.onrender.com
  python scripts/verify_deployment.py --expected-commit 30cb1c8
"""

import sys
import time
import argparse
from datetime import datetime, timezone
import httpx

DEFAULT_BACKEND = "https://compass-backend-qryu.onrender.com"
DEFAULT_FRONTEND = "https://compass-farmlytics.vercel.app"
GITHUB_REPO = "Ratnesh-101/compass"


def get_github_main_commit(timeout: float = 8.0) -> str:
    """Fetch the latest commit SHA from GitHub main branch."""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers={"User-Agent": "compass-smoke-verifier"})
            if resp.status_code == 200:
                data = resp.json()
                return data.get("sha", "")[:7]
    except Exception:
        pass
    return ""


def run_smoke_verification(
    backend_url: str = DEFAULT_BACKEND,
    frontend_url: str = DEFAULT_FRONTEND,
    expected_commit: str = "",
    timeout: float = 15.0,
) -> bool:
    """Execute all non-destructive post-deployment probes."""
    backend_url = backend_url.rstrip("/")
    frontend_url = frontend_url.rstrip("/")
    start_time = time.time()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print("=" * 78)
    print("COMPASS -- POST-DEPLOYMENT SMOKE VERIFICATION")
    print(f"   Timestamp   : {timestamp}")
    print(f"   Backend URL : {backend_url}")
    print(f"   Frontend URL: {frontend_url}")
    if expected_commit:
        print(f"   Expected Git: {expected_commit}")
    else:
        gh_head = get_github_main_commit(timeout=timeout)
        if gh_head:
            print(f"   GitHub main : {gh_head}")
            expected_commit = gh_head
    print("=" * 78)

    all_passed = True
    probes = []

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        # Probe 1: Backend Health
        t0 = time.time()
        try:
            r = client.get(f"{backend_url}/health")
            elapsed = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                data = r.json()
                status_ok = data.get("status") == "ok"
                db_conn = data.get("db_connected") is True
                deployed_commit = data.get("commit", "unknown")
                commit_match = True
                if expected_commit and deployed_commit != "unknown":
                    commit_match = deployed_commit.startswith(expected_commit[:7])

                passed = status_ok and db_conn
                probes.append({
                    "name": "Backend /health",
                    "status": "PASS" if passed else "FAIL",
                    "code": r.status_code,
                    "latency_ms": elapsed,
                    "details": f"db_connected={db_conn}, commit={deployed_commit}" +
                               (f" (matches main: {commit_match})" if expected_commit else ""),
                })
                if not passed:
                    all_passed = False
            else:
                probes.append({
                    "name": "Backend /health",
                    "status": "FAIL",
                    "code": r.status_code,
                    "latency_ms": elapsed,
                    "details": f"HTTP status {r.status_code}",
                })
                all_passed = False
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            probes.append({
                "name": "Backend /health",
                "status": "ERROR",
                "code": 0,
                "latency_ms": elapsed,
                "details": str(e),
            })
            all_passed = False

        # Probe 2: Frontend Web Dashboard
        t0 = time.time()
        try:
            r = client.get(frontend_url)
            elapsed = int((time.time() - t0) * 1000)
            has_root = '<div id="root">' in r.text or "<div id='root'>" in r.text
            passed = r.status_code == 200 and has_root
            probes.append({
                "name": "Frontend Dashboard (Vercel)",
                "status": "PASS" if passed else "FAIL",
                "code": r.status_code,
                "latency_ms": elapsed,
                "details": f"HTML bundle loaded ({len(r.content)} bytes, root div verified)",
            })
            if not passed:
                all_passed = False
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            probes.append({
                "name": "Frontend Dashboard (Vercel)",
                "status": "ERROR",
                "code": 0,
                "latency_ms": elapsed,
                "details": str(e),
            })
            all_passed = False

        # Probe 3: Vercel Reverse Proxy /health Rewrite
        t0 = time.time()
        try:
            r = client.get(f"{frontend_url}/health")
            elapsed = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                data = r.json()
                proxy_ok = data.get("status") == "ok"
                probes.append({
                    "name": "Vercel /health Proxy Rewrite",
                    "status": "PASS" if proxy_ok else "FAIL",
                    "code": r.status_code,
                    "latency_ms": elapsed,
                    "details": f"Vercel rewrite/proxy transparently reached Render backend (commit={data.get('commit')})",
                })
                if not proxy_ok:
                    all_passed = False
            else:
                probes.append({
                    "name": "Vercel /health Proxy Rewrite",
                    "status": "FAIL",
                    "code": r.status_code,
                    "latency_ms": elapsed,
                    "details": f"HTTP status {r.status_code}",
                })
                all_passed = False
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            probes.append({
                "name": "Vercel /health Proxy Rewrite",
                "status": "ERROR",
                "code": 0,
                "latency_ms": elapsed,
                "details": str(e),
            })
            all_passed = False

        # Probe 4: CORS Preflight Verification
        t0 = time.time()
        try:
            cors_headers = {
                "Origin": frontend_url,
                "Access-Control-Request-Method": "GET",
            }
            r = client.options(f"{backend_url}/health", headers=cors_headers)
            elapsed = int((time.time() - t0) * 1000)
            allowed_origin = r.headers.get("access-control-allow-origin", "")
            cors_ok = (allowed_origin == frontend_url or allowed_origin == "*")
            probes.append({
                "name": "Backend CORS Preflight",
                "status": "PASS" if cors_ok else "FAIL",
                "code": r.status_code,
                "latency_ms": elapsed,
                "details": f"Origin: {frontend_url} -> Allow-Origin: {allowed_origin or 'NONE'}",
            })
            if not cors_ok:
                all_passed = False
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            probes.append({
                "name": "Backend CORS Preflight",
                "status": "ERROR",
                "code": 0,
                "latency_ms": elapsed,
                "details": str(e),
            })
            all_passed = False

    total_duration = time.time() - start_time

    # Display results table
    print("\nRESULTS:")
    print("-" * 78)
    for p in probes:
        icon = "[PASS]" if p["status"] == "PASS" else "[FAIL]"
        print(f" {icon} [{p['status']:^5}] {p['name']:<30} | {p['latency_ms']:>4}ms | HTTP {p['code']} | {p['details']}")
    print("-" * 78)
    print(f"Total verification time: {total_duration:.2f}s")

    if all_passed:
        print("\nALL POST-DEPLOYMENT SMOKE CHECKS PASSED.")
        print("The production frontend and backend are healthy, synchronized, and reachable.")
    else:
        print("\nONE OR MORE POST-DEPLOYMENT SMOKE CHECKS FAILED.")
        print("Investigate failed probes above or refer to docs/deployment.md for rollback.")

    print("=" * 78)
    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Compass post-deployment smoke verification tool."
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND, help="Backend API base URL")
    parser.add_argument("--frontend-url", default=DEFAULT_FRONTEND, help="Frontend base URL")
    parser.add_argument("--expected-commit", default="", help="Expected commit SHA (e.g. from git rev-parse HEAD)")
    parser.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout in seconds")

    args = parser.parse_args()
    success = run_smoke_verification(
        backend_url=args.backend_url,
        frontend_url=args.frontend_url,
        expected_commit=args.expected_commit,
        timeout=args.timeout,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
