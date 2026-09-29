"""
Compass — Skill Handlers Subpackage.

Importing this package ensures all skill handlers are registered into SKILL_REGISTRY.
"""

from backend.skills.handlers.web import (
    handle_search_web,
    handle_ingest_url,
    handle_verify_deadline,
)
from backend.skills.handlers.tasks import (
    handle_query_tasks,
    handle_query_coursework_tasks,
    handle_get_hackathon_deadlines,
    handle_add_task,
    handle_update_task_status,
    handle_edit_task,
    handle_delete_task,
    handle_list_projects,
    handle_detect_deadline_conflicts,
)
from backend.skills.handlers.context import (
    handle_query_code_context,
    handle_log_code_context,
    handle_log_code_snippet,
    handle_summarize_day,
    handle_query_coursework_notes,
    handle_summarize_across_domains,
    handle_chat_skill,
)
from backend.skills.handlers.calendar import (
    handle_get_calendar_availability,
    handle_propose_schedule,
    handle_commit_schedule,
    handle_detect_schedule_conflicts,
)
from backend.skills.handlers.specialist import (
    handle_assess_feasibility,
    handle_apply_triage_plan,
    handle_delegate_to_specialist,
)

__all__ = [
    "handle_search_web",
    "handle_ingest_url",
    "handle_verify_deadline",
    "handle_query_tasks",
    "handle_query_coursework_tasks",
    "handle_get_hackathon_deadlines",
    "handle_add_task",
    "handle_update_task_status",
    "handle_edit_task",
    "handle_delete_task",
    "handle_list_projects",
    "handle_detect_deadline_conflicts",
    "handle_query_code_context",
    "handle_log_code_context",
    "handle_log_code_snippet",
    "handle_summarize_day",
    "handle_query_coursework_notes",
    "handle_summarize_across_domains",
    "handle_chat_skill",
    "handle_get_calendar_availability",
    "handle_propose_schedule",
    "handle_commit_schedule",
    "handle_detect_schedule_conflicts",
    "handle_assess_feasibility",
    "handle_apply_triage_plan",
    "handle_delegate_to_specialist",
]
