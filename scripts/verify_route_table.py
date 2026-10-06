"""
Compass — Programmatic Route Table Generator & Verification Script.

Ensures:
1. Every endpoint registered on FastAPI app.routes has a known metadata entry.
2. Every route touching user data has a designated test.
3. No routes are untracked.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from backend.main import app

KNOWN_ROUTE_METADATA = {
    ("/", "GET"): ("None", "Public Health / Metadata (Docs redirected in dev)", "test_api_endpoints.py::test_root_endpoint"),
    ("/health", "GET"): ("None", "Public Readiness / Neon DB pool ping", "test_api_endpoints.py::test_health_endpoint"),
    ("/admin/consolidate", "POST"): ("verify_token (AUTH_TOKEN)", "Restricted to callers with AUTH_TOKEN", "test_nightly_job.py::test_consolidate_endpoint"),
    ("/admin/usage", "GET"): ("verify_token (AUTH_TOKEN)", "Restricted to callers with AUTH_TOKEN", "test_telemetry.py::test_admin_usage_telemetry"),
    ("/api/admin/usage", "GET"): ("verify_token (AUTH_TOKEN)", "Restricted to callers with AUTH_TOKEN", "test_telemetry.py::test_admin_usage_telemetry"),
    ("/api/agent/activity", "GET"): ("_get_current_identity", "WHERE approved_by = $1 OR args->>'user_id' = $1", "test_round3_corrections.py::test_agent_activity_auth_isolation"),
    ("/api/agent/capabilities", "GET"): ("None", "Static schema of available agent actions", "test_agent_execution.py::test_agent_capabilities"),
    ("/api/agent/confirm", "POST"): ("_get_current_identity", "Pending action owner verified (tamper & replay proof)", "test_auth_bypass_gates.py::test_agent_admin_override_logged_to_audit"),
    ("/api/agent/critique-stats", "GET"): ("None", "Aggregated execution telemetry", "test_telemetry.py::test_critique_stats"),
    ("/api/agent/feasibility", "POST"): ("verify_token (AUTH_TOKEN)", "Restricted to callers with AUTH_TOKEN (SSE)", "test_agent_execution.py::test_feasibility_endpoint"),
    ("/api/agent/proactive-briefing", "GET"): ("_get_current_identity", "Returns latest proactive briefing run", "test_nightly_job.py::test_proactive_briefing"),
    ("/api/agent/run", "POST"): ("_get_current_identity", "Run bound to caller; throttled by agent_rate_limit", "test_agent_execution.py::test_agent_run_endpoint"),
    ("/api/agent/runs", "GET"): ("_get_current_identity", "WHERE user_id = $1 or caller run isolation", "test_agent_execution.py::test_list_runs"),
    ("/api/agent/runs/{run_id}", "GET"): ("_get_current_identity", "Ownership check against run owner", "test_agent_execution.py::test_get_run_detail"),
    ("/api/agent/trigger-nightly", "POST"): ("verify_token (AUTH_TOKEN)", "Admin AUTH_TOKEN via hmac.compare_digest strictly", "test_nightly_job.py::test_trigger_nightly_admin_auth"),
    ("/api/agent/undo", "POST"): ("_get_current_identity", "Identity ownership verified against agent_audit_log (IDOR safe)", "test_round4_hardening.py::test_cross_identity_agent_undo_isolation_negative"),
    ("/api/auth/logout", "POST"): ("None", "Clears session cookies compass_session, compass_guest_token", "test_api_endpoints.py::test_logout_endpoint"),
    ("/api/auth/me", "GET"): ("_get_current_identity", "Returns caller identity or 401", "test_api_endpoints.py::test_session_endpoint"),
    ("/api/auth/quick-connect", "GET"): ("None", "Developer/demo switch login (gated)", "test_auth_bypass_gates.py::test_quick_connect"),
    ("/api/auth/quick-connect", "POST"): ("None", "Developer/demo switch login (gated)", "test_auth_bypass_gates.py::test_quick_connect"),
    ("/api/calendar/availability", "GET"): ("_get_current_identity", "Resolved for caller calendar / working hours", "test_reactive_scheduling.py::test_calendar_availability"),
    ("/api/calendar/callback", "GET"): ("_get_current_identity", "Strictly validates state bound to caller (anti-CSRF)", "test_round3_corrections.py::test_oauth_state_binding"),
    ("/api/calendar/connect", "GET"): ("_get_current_identity", "Generates HMAC user-bound state parameter", "test_round3_corrections.py::test_oauth_state_binding"),
    ("/api/calendar/disconnect", "POST"): ("_get_current_identity + CSRF", "Clears Google Calendar tokens for user", "test_round3_corrections.py::test_calendar_disconnect"),
    ("/api/calendar/export.ics", "GET"): ("_get_current_identity", "Generates RFC 5545 feed for caller's tasks only", "test_scheduling.py::test_ics_export"),
    ("/api/calendar/preferences", "GET"): ("None / Fallback", "Default preferences or caller scoped", "test_scheduling.py::test_calendar_preferences"),
    ("/api/calendar/preferences", "PUT"): ("_get_current_identity", "Updates scheduling preferences", "test_scheduling.py::test_update_preferences"),
    ("/api/calendar/status", "GET"): ("_get_current_identity", "WHERE user_id = $1 in calendar_connections", "test_user_isolation.py::test_calendar_status_isolation"),
    ("/api/calendar/sync-now", "POST"): ("_get_current_identity + CSRF", "Syncs tasks to Google Calendar", "test_round3_corrections.py::test_calendar_sync_now"),
    ("/api/chat", "POST"): ("_get_current_identity", "Scoped to conversation_id + user_id / guest_id", "test_chat_gate.py::test_chat_message_flow"),
    ("/api/chat/stream", "POST"): ("_get_current_identity", "Scoped to conversation_id + user_id / guest_id (SSE)", "test_round4_hardening.py::test_sse_disconnect_cancels_upstream"),
    ("/api/conversations", "GET"): ("_get_current_identity", "WHERE user_id = $1 (Strict isolation)", "test_conversations_memory.py::test_list_conversations"),
    ("/api/conversations/{conversation_id}", "DELETE"): ("_get_current_identity", "Ownership check: 403 if not owner", "test_round4_hardening.py::test_cross_identity_conversation_isolation_negative"),
    ("/api/conversations/{conversation_id}", "PATCH"): ("_get_current_identity", "Ownership check: 403 if not owner", "test_round4_hardening.py::test_cross_identity_conversation_isolation_negative"),
    ("/api/conversations/{conversation_id}/messages", "GET"): ("_get_current_identity", "Ownership check: 403 if not owner", "test_round4_hardening.py::test_cross_identity_conversation_isolation_negative"),
    ("/api/demo/seed", "POST"): ("None (Rate Limited)", "Gated seed endpoint, throttled by client IP", "test_round4_hardening.py::test_demo_seed_rate_limited"),
    ("/api/guest/data", "DELETE"): ("_get_current_identity", "Deletes all conversations and memories for guest token", "test_guest_migration.py::test_delete_guest_data"),
    ("/api/guest/migrate", "POST"): ("_get_current_identity", "Atomic transaction import of guest data", "test_guest_migration.py::test_migration_import_all"),
    ("/api/guest/session", "GET"): ("verify_guest_token", "Validates signed HMAC token", "test_guest_migration.py::test_guest_session_get"),
    ("/api/guest/session", "POST"): ("mint_rate_limit", "Mints random UUID guest token, enforces global cap", "test_guest_migration.py::test_guest_session_post"),
    ("/api/log", "POST"): ("_get_or_create_user_id", "Generates 768-dim embedding and inserts into Neon", "test_memory_embeddings.py::test_log_memory"),
    ("/api/memory/overview", "GET"): ("_get_current_identity", "WHERE user_id = $1 memory overview summary", "test_conversations_memory.py::test_memory_overview"),
    ("/api/migration/conversations", "GET"): ("_get_current_identity", "List guest conversations for migration", "test_round4_hardening.py::test_cross_identity_migration_isolation_negative"),
    ("/api/migration/import-all", "POST"): ("_get_current_identity", "Atomic transaction import of all guest items", "test_guest_migration.py::test_migration_import_all"),
    ("/api/migration/import-selected", "POST"): ("_get_current_identity", "Atomic transaction import of selected UUIDs", "test_guest_migration.py::test_migration_import_selected"),
    ("/api/migration/skip", "POST"): ("None", "Sets cookie compass_migration_skipped", "test_guest_migration.py::test_migration_skip"),
    ("/api/migration/status", "GET"): ("_get_current_identity", "Eligible guest items for active user", "test_guest_migration.py::test_migration_status"),
    ("/api/schedule/commit", "POST"): ("_get_current_identity", "Commits approved slots to tasks and calendar", "test_scheduling.py::test_commit_schedule"),
    ("/api/schedule/conflicts", "GET"): ("_get_current_identity", "Checks schedule clashes for active user", "test_reactive_scheduling.py::test_conflicts"),
    ("/api/schedule/propose", "POST"): ("None / Stateless", "Deterministic schedule generation over tasks", "test_scheduling.py::test_propose_schedule"),
    ("/api/schedule/reactive-check", "POST"): ("None / Stateless", "Slipped task replanning algorithm", "test_reactive_scheduling.py::test_reactive_check"),
    ("/api/tasks", "GET"): ("_get_current_identity", "WHERE user_id = $1", "test_direct_tasks.py::test_list_tasks"),
    ("/api/tasks", "POST"): ("_get_current_identity", "Bound to caller user_id / guest_id", "test_direct_tasks.py::test_create_task"),
    ("/api/tasks/verify-deadlines", "POST"): ("_get_current_identity", "Batch verification for caller tasks", "test_tavily_abstain.py::test_verify_deadlines_batch"),
    ("/api/tasks/{task_id}", "DELETE"): ("_get_current_identity", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_round4_hardening.py::test_cross_identity_tasks_isolation_negative"),
    ("/api/tasks/{task_id}", "PATCH"): ("_get_current_identity", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_round4_hardening.py::test_cross_identity_tasks_isolation_negative"),
    ("/api/tasks/{task_id}", "PUT"): ("_get_current_identity", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_round4_hardening.py::test_cross_identity_tasks_isolation_negative"),
    ("/api/tasks/{task_id}/dependencies", "GET"): ("_get_current_identity", "Tasks verified to belong to caller", "test_direct_tasks.py::test_task_dependencies"),
    ("/api/tasks/{task_id}/dependencies", "POST"): ("_get_current_identity", "Both tasks verified to belong to caller", "test_direct_tasks.py::test_task_dependencies"),
    ("/api/tasks/{task_id}/dependencies/{depends_on_task_id}", "DELETE"): ("_get_current_identity", "Ownership verified on parent task", "test_direct_tasks.py::test_delete_task_dependency"),
    ("/api/tasks/{task_id}/verify", "POST"): ("_get_current_identity", "Ownership verified on task_id", "test_tavily_abstain.py::test_verify_deadline_endpoint"),
    ("/api/telemetry", "GET"): ("_get_current_identity (Optional)", "Telemetry metrics; cost stripped for non-admin", "test_telemetry.py::test_telemetry_endpoint"),
    ("/api/usage/summary", "GET"): ("_get_current_identity (Optional)", "Token usage breakdown; cost stripped for non-admin", "test_telemetry.py::test_usage_summary_endpoint"),
    ("/chat", "POST"): ("_get_current_identity", "Redirects to /api/chat with caller identity", "test_chat_gate.py::test_chat_message_flow"),
    ("/dashboard", "GET"): ("_get_current_identity", "WHERE user_id = $1 dashboard stats", "test_direct_tasks.py::test_dashboard_endpoint"),
    ("/memory/timeline", "GET"): ("_get_current_identity", "WHERE user_id = $1 memory timeline", "test_direct_tasks.py::test_timeline_endpoint"),
    ("/projects", "GET"): ("_get_current_identity", "WHERE user_id = $1 projects list", "test_direct_tasks.py::test_projects_endpoint"),
    ("/tasks", "GET"): ("_get_current_identity", "WHERE user_id = $1 tasks list", "test_direct_tasks.py::test_list_tasks"),
    ("/api/chat/recap", "POST"): ("_get_current_identity", "Ownership check: 403 if not owner", "test_round9_negative_coverage.py::test_neg_post_chat_recap"),
    ("/api/parked", "GET"): ("_get_current_identity", "WHERE user_id = $1", "test_round9_negative_coverage.py::test_neg_get_parked_thoughts"),
    ("/api/parked", "POST"): ("_get_current_identity", "Bound to caller identity", "test_round9_negative_coverage.py::test_neg_post_parked_thought"),
    ("/api/parked/{thought_id}", "PATCH"): ("_get_current_identity", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_round9_negative_coverage.py::test_neg_patch_parked_thought"),
    ("/api/parked/{thought_id}/resolve", "PATCH"): ("_get_current_identity", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_round9_negative_coverage.py::test_neg_patch_parked_thought_resolve"),
    ("/api/persona/phrases", "GET"): ("None", "Public persona phrase pools", "test_persona_and_profile.py::test_persona_phrases_endpoint"),
    ("/api/profile/facts", "GET"): ("_get_current_identity", "WHERE user_id = $1", "test_round9_negative_coverage.py::test_neg_get_profile_facts"),
    ("/api/profile/facts", "DELETE"): ("_get_current_identity", "WHERE user_id = $1 (forget all)", "test_round9_negative_coverage.py::test_neg_delete_all_profile_facts"),
    ("/api/profile/facts/{key}", "DELETE"): ("_get_current_identity", "WHERE user_id = $1 AND key = $2", "test_round9_negative_coverage.py::test_neg_delete_single_profile_fact"),
}

# ---------------------------------------------------------------------------
# Negative Cross-Identity Test Mapping for All User-Data Routes
# ---------------------------------------------------------------------------
NEGATIVE_CROSS_IDENTITY_TESTS = {
    # Tasks & verification
    ("/api/tasks", "GET"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks", "POST"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}", "DELETE"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}", "PATCH"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}", "PUT"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}/dependencies", "GET"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}/dependencies", "POST"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}/dependencies/{depends_on_task_id}", "DELETE"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/{task_id}/verify", "POST"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/api/tasks/verify-deadlines", "POST"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/tasks", "GET"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/dashboard", "GET"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/projects", "GET"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
    ("/memory/timeline", "GET"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",

    # Conversations & Chat
    ("/api/chat", "POST"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/api/chat/stream", "POST"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/chat", "POST"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/api/conversations", "GET"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/api/conversations/{conversation_id}", "DELETE"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/api/conversations/{conversation_id}", "PATCH"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/api/conversations/{conversation_id}/messages", "GET"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",
    ("/api/chat/recap", "POST"): "tests/test_round9_negative_coverage.py::test_neg_post_chat_recap",

    # Profile facts
    ("/api/profile/facts", "GET"): "tests/test_round9_negative_coverage.py::test_neg_get_profile_facts",
    ("/api/profile/facts", "DELETE"): "tests/test_round9_negative_coverage.py::test_neg_delete_all_profile_facts",
    ("/api/profile/facts/{key}", "DELETE"): "tests/test_round9_negative_coverage.py::test_neg_delete_single_profile_fact",

    # Parked thoughts
    ("/api/parked", "GET"): "tests/test_round9_negative_coverage.py::test_neg_get_parked_thoughts",
    ("/api/parked", "POST"): "tests/test_round9_negative_coverage.py::test_neg_post_parked_thought",
    ("/api/parked/{thought_id}", "PATCH"): "tests/test_round9_negative_coverage.py::test_neg_patch_parked_thought",
    ("/api/parked/{thought_id}/resolve", "PATCH"): "tests/test_round9_negative_coverage.py::test_neg_patch_parked_thought_resolve",

    # Guest & Migration
    ("/api/guest/data", "DELETE"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",
    ("/api/guest/migrate", "POST"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",
    ("/api/migration/conversations", "GET"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",
    ("/api/migration/import-all", "POST"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",
    ("/api/migration/import-selected", "POST"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",
    ("/api/migration/status", "GET"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",

    # Agent user operations
    ("/api/agent/activity", "GET"): "tests/test_round3_corrections.py::test_agent_activity_auth_isolation",
    ("/api/agent/confirm", "POST"): "tests/test_round5_hardening.py::test_cross_identity_agent_undo_isolation_negative",
    ("/api/agent/proactive-briefing", "GET"): "tests/test_round5_hardening.py::test_cross_identity_agent_undo_isolation_negative",
    ("/api/agent/run", "POST"): "tests/test_round5_hardening.py::test_cross_identity_agent_undo_isolation_negative",
    ("/api/agent/runs", "GET"): "tests/test_round5_hardening.py::test_cross_identity_agent_undo_isolation_negative",
    ("/api/agent/runs/{run_id}", "GET"): "tests/test_round5_hardening.py::test_cross_identity_agent_undo_isolation_negative",
    ("/api/agent/undo", "POST"): "tests/test_round5_hardening.py::test_cross_identity_agent_undo_isolation_negative",

    # Calendar & Scheduling user operations
    ("/api/calendar/availability", "GET"): "tests/test_user_isolation.py::test_account_selection_and_task_isolation",
    ("/api/calendar/callback", "GET"): "tests/test_round3_corrections.py::test_oauth_state_binding_isolation_negative",
    ("/api/calendar/connect", "GET"): "tests/test_round3_corrections.py::test_oauth_state_binding_isolation_negative",
    ("/api/calendar/disconnect", "POST"): "tests/test_round3_corrections.py::test_calendar_disconnect_isolation_negative",
    ("/api/calendar/export.ics", "GET"): "tests/test_user_isolation.py::test_calendar_status_isolation",
    ("/api/calendar/preferences", "PUT"): "tests/test_user_isolation.py::test_account_selection_and_task_isolation",
    ("/api/calendar/status", "GET"): "tests/test_user_isolation.py::test_calendar_status_isolation",
    ("/api/calendar/sync-now", "POST"): "tests/test_round3_corrections.py::test_calendar_sync_now_isolation_negative",
    ("/api/schedule/commit", "POST"): "tests/test_user_isolation.py::test_account_selection_and_task_isolation",
    ("/api/schedule/conflicts", "GET"): "tests/test_user_isolation.py::test_account_selection_and_task_isolation",

    # Memory
    ("/api/log", "POST"): "tests/test_user_isolation.py::test_account_selection_and_task_isolation",
    ("/api/memory/overview", "GET"): "tests/test_round5_hardening.py::test_cross_identity_conversation_isolation_negative",

    # Identity & Seeding
    ("/api/auth/me", "GET"): "tests/test_round5_hardening.py::test_cross_identity_migration_isolation_negative",
    ("/api/demo/seed", "POST"): "tests/test_round5_hardening.py::test_cross_identity_tasks_isolation_negative",
}

USER_DATA_ROUTES = set(NEGATIVE_CROSS_IDENTITY_TESTS.keys())


def get_app_routes() -> list[tuple[str, str]]:
    """Enumerate all registered FastAPI routes across root app and included routers."""
    routes = set()
    paths = app.openapi().get("paths", {})
    for path, pdata in paths.items():
        for m in pdata.keys():
            m_upper = m.upper()
            if m_upper in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                routes.add((path, m_upper))
    for r in app.routes:
        p = getattr(r, "path", None)
        if p and p not in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            for m in getattr(r, "methods", set()):
                if m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    routes.add((p, m.upper()))
    return sorted(list(routes))


def verify_all_routes():
    untracked = []
    for key in get_app_routes():
        if key not in KNOWN_ROUTE_METADATA:
            untracked.append(key)
    return untracked


def discover_negative_route_tests() -> dict[tuple[str, str], str]:
    """Dynamically parse all test files in tests/ via AST to find @pytest.mark.route('METHOD /path') decorations."""
    import ast
    tests_dir = _project_root / "tests"
    mapping: dict[tuple[str, str], str] = {}

    for test_file in tests_dir.glob("test_*.py"):
        try:
            tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call):
                        name = ""
                        if isinstance(deco.func, ast.Attribute):
                            name = deco.func.attr
                        if name == "route" and deco.args:
                            arg0 = deco.args[0]
                            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                                val = arg0.value.strip()
                                parts = val.split(" ", 1)
                                if len(parts) == 2:
                                    method, path = parts[0].upper(), parts[1]
                                    mapping[(path, method)] = f"{test_file.name}::{node.name}"
    return mapping


def verify_negative_cross_identity_coverage():
    """Verify that each user-data route has its OWN negative cross-identity test that actually hits that route."""
    discovered = discover_negative_route_tests()
    missing = []
    seen_tests = set()

    for key in get_app_routes():
        path, m = key
        if key in USER_DATA_ROUTES:
            test_ref = discovered.get(key)
            if not test_ref:
                missing.append((path, m, "No negative test with @pytest.mark.route found in test suite"))
            else:
                if test_ref in seen_tests:
                    missing.append((path, m, f"Test '{test_ref}' is reused across multiple routes; each user-data route must have its own test"))
                seen_tests.add(test_ref)

    return missing, len(discovered), len(USER_DATA_ROUTES)


def print_markdown_table():
    discovered = discover_negative_route_tests()
    print("| Route | Method | Identity Dep | Ownership Check / Access Policy | Test Function | Negative Cross-Identity Test |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for key in get_app_routes():
        path, m = key
        meta = KNOWN_ROUTE_METADATA.get(key, ("None", "Public or Default", "tests/test_api_endpoints.py"))
        neg = discovered.get(key, "N/A (Public / Infrastructure)")
        print(f"| `{path}` | `{m}` | `{meta[0]}` | {meta[1]} | `{meta[2]}` | `{neg}` |")



if __name__ == "__main__":
    untracked = verify_all_routes()
    if untracked:
        print(f"ERROR: {len(untracked)} untracked routes found:", file=sys.stderr)
        for path, method in untracked:
            print(f"  - ({path}, {method})", file=sys.stderr)
        sys.exit(1)

    missing_negative, discovered_count, required_count = verify_negative_cross_identity_coverage()
    if missing_negative:
        print(f"ERROR: {len(missing_negative)} user-data routes lack a distinct NEGATIVE cross-identity test:", file=sys.stderr)
        for path, method, reason in missing_negative:
            print(f"  - ({path}, {method}): {reason}", file=sys.stderr)
        sys.exit(1)

    print(f"SUCCESS: All {len(KNOWN_ROUTE_METADATA)} registered FastAPI routes verified. Real count: {discovered_count}/{required_count} user-data routes covered by distinct negative cross-identity tests derived from @pytest.mark.route.")
    if len(sys.argv) > 1 and sys.argv[1] == "--markdown":
        print_markdown_table()

