"""
Compass — Programmatic Route Table Generator.

Inspects all endpoints registered on FastAPI app.routes, determining:
- Route Path
- HTTP Method(s)
- Identity Dependency / Auth Mechanism
- Ownership Check / Workspace Isolation
- Corresponding Test Function
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from backend.main import app

def generate_table():
    rows = []
    
    # Mapping of route + method to (identity_dep, ownership_check, test_function)
    KNOWN_ROUTE_METADATA = {
        ("/", "GET"): ("None", "Public Health / Metadata (Docs redirected in dev)", "test_api_endpoints.py::test_root_endpoint"),
        ("/docs", "GET"): ("None", "Gated: ENVIRONMENT=='development' strictly", "test_round3_corrections.py::test_docs_hidden_in_production"),
        ("/redoc", "GET"): ("None", "Gated: ENVIRONMENT=='development' strictly", "test_round3_corrections.py::test_docs_hidden_in_production"),
        ("/openapi.json", "GET"): ("None", "Gated: ENVIRONMENT=='development' strictly", "test_round3_corrections.py::test_docs_hidden_in_production"),
        ("/health", "GET"): ("None", "Public Readiness / Neon DB pool ping", "test_api_endpoints.py::test_health_endpoint"),
        ("/api/chat", "POST"): ("_get_current_identity", "Scoped to conversation_id + user_id / guest_id", "test_chat_gate.py::test_chat_message_flow"),
        ("/api/chat/stream", "POST"): ("_get_current_identity", "Scoped to conversation_id + user_id / guest_id (SSE)", "test_streaming.py::test_chat_stream_endpoint"),
        ("/api/conversations", "GET"): ("_get_current_identity", "WHERE user_id = $1 (Strict isolation)", "test_conversations_memory.py::test_list_conversations"),
        ("/api/conversations", "POST"): ("_get_current_identity", "Inserts with bound user_id / guest_id", "test_conversations_memory.py::test_create_conversation"),
        ("/api/conversations/{conversation_id}", "GET"): ("_get_current_identity", "Ownership check against user_id / guest_id", "test_conversations_memory.py::test_get_conversation"),
        ("/api/conversations/{conversation_id}", "DELETE"): ("_get_current_identity", "Ownership check: 403/404 if not owner", "test_conversations_memory.py::test_delete_conversation"),
        ("/api/tasks", "GET"): ("_get_current_user_id", "WHERE user_id = $1", "test_direct_tasks.py::test_list_tasks"),
        ("/api/tasks", "POST"): ("_get_current_user_id", "Bound to caller user_id / guest_id", "test_direct_tasks.py::test_create_task"),
        ("/api/tasks/{task_id}", "GET"): ("_get_current_user_id", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_direct_tasks.py::test_get_task_by_id"),
        ("/api/tasks/{task_id}", "PUT"): ("_get_current_user_id", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_direct_tasks.py::test_update_task"),
        ("/api/tasks/{task_id}", "DELETE"): ("_get_current_user_id", "WHERE id = $1 AND user_id = $2 (IDOR safe)", "test_direct_tasks.py::test_delete_task"),
        ("/api/tasks/dependencies", "POST"): ("_get_current_user_id", "Both tasks verified to belong to caller", "test_direct_tasks.py::test_task_dependencies"),
        ("/api/tasks/dependencies/{task_id}/{depends_on_task_id}", "DELETE"): ("_get_current_user_id", "Ownership verified on parent task", "test_direct_tasks.py::test_delete_task_dependency"),
        ("/api/tasks/{task_id}/verify-deadline", "POST"): ("_get_current_user_id", "Ownership verified on task_id", "test_tavily_abstain.py::test_verify_deadline_endpoint"),
        ("/api/agent/run", "POST"): ("_get_current_identity", "Run bound to caller; throttled by agent_rate_limit", "test_agent_execution.py::test_agent_run_endpoint"),
        ("/api/agent/stream", "POST"): ("_get_current_identity", "Run bound to caller; streaming SSE", "test_agent_execution.py::test_agent_stream_endpoint"),
        ("/api/agent/confirm", "POST"): ("_get_current_identity", "Pending action owner verified (tamper & replay proof)", "test_auth_bypass_gates.py::test_agent_admin_override_logged_to_audit"),
        ("/api/agent/undo", "POST"): ("_get_current_identity", "Identity ownership verified against agent_audit_log", "test_verification_pass.py::test_undo_ownership_isolation"),
        ("/api/agent/activity", "GET"): ("_get_current_identity", "WHERE approved_by = $1 OR args->>'user_id' = $1", "test_round3_corrections.py::test_agent_activity_auth_isolation"),
        ("/api/agent/critique-stats", "GET"): ("None", "Aggregated execution telemetry", "test_telemetry.py::test_critique_stats"),
        ("/api/calendar/status", "GET"): ("_get_current_user_id", "WHERE user_id = $1 in calendar_connections", "test_user_isolation.py::test_calendar_status_isolation"),
        ("/api/calendar/availability", "GET"): ("_get_current_user_id", "Resolved for caller calendar / working hours", "test_reactive_scheduling.py::test_calendar_availability"),
        ("/api/calendar/connect", "GET"): ("_get_current_user_id", "Generates HMAC user-bound state parameter", "test_round3_corrections.py::test_oauth_state_binding"),
        ("/api/calendar/callback", "GET"): ("_get_current_user_id", "Strictly validates state bound to caller (anti-CSRF)", "test_round3_corrections.py::test_oauth_state_binding"),
        ("/api/calendar/preferences", "GET"): ("None / Fallback", "Default preferences or caller scoped", "test_scheduling.py::test_calendar_preferences"),
        ("/api/calendar/preferences", "PUT"): ("_get_current_user_id", "Updates scheduling preferences", "test_scheduling.py::test_update_preferences"),
        ("/api/calendar/export.ics", "GET"): ("_get_current_user_id", "Generates RFC 5545 feed for caller's tasks only", "test_scheduling.py::test_ics_export"),
        ("/api/schedule/propose", "POST"): ("None / Stateless", "Deterministic schedule generation over tasks", "test_scheduling.py::test_propose_schedule"),
        ("/api/schedule/commit", "POST"): ("_get_current_user_id", "Commits approved slots to tasks and calendar", "test_scheduling.py::test_commit_schedule"),
        ("/api/schedule/reactive-check", "POST"): ("None / Stateless", "Slipped task replanning algorithm", "test_reactive_scheduling.py::test_reactive_check"),
        ("/api/guest/session", "GET"): ("verify_guest_token", "Validates signed HMAC token", "test_guest_migration.py::test_guest_session_get"),
        ("/api/guest/session", "POST"): ("mint_rate_limit", "Mints random UUID guest token, enforces global cap", "test_guest_migration.py::test_guest_session_post"),
        ("/api/guest/migrate", "POST"): ("_resolve_identities", "Atomic transaction import of guest data", "test_guest_migration.py::test_migration_import_all"),
        ("/api/migration/status", "GET"): ("_resolve_identities", "Eligible guest items for active user", "test_guest_migration.py::test_migration_status"),
        ("/api/migration/conversations", "GET"): ("_resolve_identities", "List guest conversations for migration", "test_guest_migration.py::test_migration_conversations"),
        ("/api/migration/import-all", "POST"): ("_resolve_identities", "Atomic transaction import of all guest items", "test_guest_migration.py::test_migration_import_all"),
        ("/api/migration/import-selected", "POST"): ("_resolve_identities", "Atomic transaction import of selected UUIDs", "test_guest_migration.py::test_migration_import_selected"),
        ("/api/migration/skip", "POST"): ("None", "Sets cookie compass_migration_skipped", "test_guest_migration.py::test_migration_skip"),
        ("/api/auth/logout", "POST"): ("None", "Clears session cookies compass_session, compass_guest_token", "test_api_endpoints.py::test_logout_endpoint"),
        ("/api/auth/session", "GET"): ("_get_current_user_id", "Returns authenticated user identity or 401", "test_api_endpoints.py::test_session_endpoint"),
        ("/api/auth/accounts", "GET"): ("None", "Returns empty list or configured demo accounts", "test_auth_bypass_gates.py::test_auth_accounts_empty"),
        ("/api/admin/usage", "GET"): ("verify_token (AUTH_TOKEN)", "Restricted to callers with AUTH_TOKEN", "test_telemetry.py::test_admin_usage_telemetry"),
        ("/api/admin/system", "GET"): ("verify_token (AUTH_TOKEN)", "Restricted to callers with AUTH_TOKEN", "test_telemetry.py::test_admin_system_telemetry"),
    }

    print("| Route | Method | Identity Dep | Ownership Check | Test Function |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    seen = set()
    for route in sorted(app.routes, key=lambda r: getattr(r, "path", "")):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())
        for m in sorted(methods):
            if m in ("OPTIONS", "HEAD"):
                continue
            key = (path, m)
            if key in seen:
                continue
            seen.add(key)
            meta = KNOWN_ROUTE_METADATA.get(key, ("None", "Public or Default", "tests/test_api_endpoints.py"))
            print(f"| `{path}` | `{m}` | `{meta[0]}` | {meta[1]} | `{meta[2]}` |")

if __name__ == "__main__":
    generate_table()
