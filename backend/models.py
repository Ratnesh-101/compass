"""
Compass — Pydantic API Models.

Shared request and response schemas matching docs/api_contract.md.
"""

from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    skill_used: Optional[str] = None
    data: Optional[Any] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    skill_called: Optional[str] = None
    created_at: str


class MessagesResponse(BaseModel):
    conversation_id: str
    messages: List[MessageOut]


class ProjectOut(BaseModel):
    id: int
    name: str
    domain: str
    description: Optional[str] = None
    created_at: str


class ProjectsResponse(BaseModel):
    projects: List[ProjectOut]


class TaskProjectRef(BaseModel):
    id: int
    name: str


class TaskOut(BaseModel):
    id: int
    domain: str
    project: Optional[TaskProjectRef] = None
    title: str
    due_date: Optional[str] = None
    status: str
    priority: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class TasksResponse(BaseModel):
    tasks: List[TaskOut]


class NearestDeadline(BaseModel):
    task_id: int
    title: str
    due_date: str


class DomainStats(BaseModel):
    project_count: int
    open_task_count: int
    nearest_deadline: Optional[NearestDeadline] = None
    last_activity: Optional[str] = None


class DashboardResponse(BaseModel):
    domains: Dict[str, DomainStats]
    total_open_tasks: int
    total_projects: int


class TimelineEntry(BaseModel):
    type: str
    domain: str
    project: Optional[str] = None
    summary: str
    created_at: str


class TimelineResponse(BaseModel):
    entries: List[TimelineEntry]
    total: int
    has_more: bool


class ModelUsage(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class UsageResponse(BaseModel):
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float
    by_model: Dict[str, ModelUsage]


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"
    database: str
    db_connected: bool = False
    commit: str = "unknown"


class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None


class ConsolidateRequest(BaseModel):
    dry_run: bool = False
    similarity_threshold: float = 0.95
    stale_thread_days: int = 7


class ConsolidateResponse(BaseModel):
    status: str
    dry_run: bool
    overdue_tasks_flagged: int
    duplicate_chunks_merged: int
    stale_conversations_rolled_up: int


class FrontendTaskOut(BaseModel):
    id: str
    title: str
    domain: str
    project: str
    countdown: str
    tags: List[str] = []
    vector_dim: int = 768
    timestamp: str = "Recently"
    priority: str = "medium"
    status: str = "open"
    duration_minutes: int = 60
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    is_fixed: bool = False
    description: Optional[str] = None
    due_date: Optional[str] = None


class CreateTaskRequest(BaseModel):
    title: str
    domain: Optional[str] = "general"
    project: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = "medium"
    status: Optional[str] = "open"
    description: Optional[str] = None
    notes: Optional[str] = None
    duration_minutes: Optional[int] = 60
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    is_fixed: Optional[bool] = False
    shift_existing: Optional[bool] = False
    allow_different_thing: Optional[bool] = False
    allow_duplicate: Optional[bool] = False


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    domain: Optional[str] = None
    project: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    duration_minutes: Optional[int] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    is_fixed: Optional[bool] = None


class PublicChatRequest(BaseModel):
    message: str
    domain: Optional[str] = None
    project: Optional[str] = None
    conversation_id: Optional[str] = None


class PublicChatResponse(BaseModel):
    response: str
    skill_used: Optional[str] = None
    agent_reasoning: Optional[str] = None
    data: Optional[Any] = None
    conversation_id: Optional[str] = None


class LogMemoryRequest(BaseModel):
    content: str
    domain: Optional[str] = "general"
    project: Optional[str] = None
    tags: Optional[List[str]] = []


class StreamChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    domain: Optional[str] = None


class AgentRequest(BaseModel):
    goal: str
    domain: Optional[str] = None
    max_steps: Optional[int] = 8
    enable_critic: Optional[bool] = True
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None


class AgentConfirmRequest(BaseModel):
    run_id: str
    confirmed: bool = True
    response_text: Optional[str] = None
    actions: Optional[List[Dict[str, Any]]] = None


class AgentUndoRequest(BaseModel):
    run_id: Optional[str] = None
    audit_log_id: Optional[int] = None


class FeasibilityRequest(BaseModel):
    days: Optional[int] = 5
    hours_per_day: Optional[float] = 4.0
    domain: Optional[str] = None


class ProposeScheduleBody(BaseModel):
    target_date: Optional[str] = None
    domain: Optional[str] = None
    task_ids: Optional[List[int]] = None


class CommitScheduleBody(BaseModel):
    assignments: List[Dict[str, Any]]
    rationale: Optional[str] = "Committed via Compass Schedule API"


class UpdatePreferencesBody(BaseModel):
    work_start_time: Optional[str] = None
    work_end_time: Optional[str] = None
    work_days: Optional[List[int]] = None
    buffer_minutes: Optional[int] = None


class SelectAccountBody(BaseModel):
    email: Optional[str] = None
    user_id: Optional[str] = None
    display_name: Optional[str] = None


class QuickConnectBody(BaseModel):
    email: Optional[str] = None
    auth_code: Optional[str] = None


class AddDependencyBody(BaseModel):
    prerequisite_task_id: int


class ReactiveCheckBody(BaseModel):
    event_type: str = "task_rescheduled"
    task_id: Optional[int] = None
    current_time: Optional[str] = None

