"""
Compass — Specialist Agent Registry.

Authoritative source of truth for all specialist agent definitions, metadata,
and validation logic across backend routing and frontend slash selection.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class SpecialistDefinition(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    capabilities: List[str] = Field(default_factory=list)


SPECIALIST_REGISTRY: Dict[str, SpecialistDefinition] = {
    "auto-dispatcher": SpecialistDefinition(
        id="auto-dispatcher",
        name="Auto Dispatcher",
        description="Automatically selects the best specialist agent based on your prompt intent.",
        icon="🧭",
        capabilities=["intent-routing", "domain-dispatch"],
    ),
    "coursework": SpecialistDefinition(
        id="coursework",
        name="Coursework Agent",
        description="Academic assignments, lab notes, exams & CS 61C coursework context.",
        icon="📚",
        capabilities=["coursework_tasks", "coursework_notes", "academic_tracking"],
    ),
    "research": SpecialistDefinition(
        id="research",
        name="Research Agent",
        description="Real-time web search, hackathon rules & deadline verification.",
        icon="🔎",
        capabilities=["web_search", "deadline_verification", "devpost_rules"],
    ),
    "calendar": SpecialistDefinition(
        id="calendar",
        name="Calendar Agent",
        description="Google Calendar availability, free time slots, conflict detection & workload triage.",
        icon="📅",
        capabilities=["calendar_availability", "conflict_detection", "feasibility_triage"],
    ),
    "memory": SpecialistDefinition(
        id="memory",
        name="Memory Agent",
        description="Vector memory search (768-dim Matryoshka), code context & task backlog.",
        icon="🧠",
        capabilities=["vector_search", "code_context", "task_backlog"],
    ),
}

# Alias map for normalized lookup across command prefixes and legacy identifiers
SPECIALIST_ALIAS_MAP: Dict[str, str] = {
    "auto": "auto-dispatcher",
    "auto-dispatcher": "auto-dispatcher",
    "autodispatcher": "auto-dispatcher",
    "dispatcher": "auto-dispatcher",
    "coursework": "coursework",
    "academic": "coursework",
    "research": "research",
    "search": "research",
    "web": "research",
    "calendar": "calendar",
    "schedule": "calendar",
    "memory": "memory",
    "vector": "memory",
    "context": "memory",
}


def get_specialist(specialist_id: str) -> Optional[SpecialistDefinition]:
    """Retrieve SpecialistDefinition by normalized ID or alias."""
    if not specialist_id:
        return None
    clean = specialist_id.strip().lower().lstrip("/")
    resolved_id = SPECIALIST_ALIAS_MAP.get(clean, clean)
    return SPECIALIST_REGISTRY.get(resolved_id)


def validate_specialist_id(specialist_id: str) -> Optional[str]:
    """Validate and return canonical specialist ID, or None if invalid."""
    spec = get_specialist(specialist_id)
    return spec.id if spec else None


def list_specialists() -> List[Dict[str, Any]]:
    """Return serialized list of all registered specialist definitions."""
    return [spec.model_dump() for spec in SPECIALIST_REGISTRY.values()]
