"""
Compass — Tool Schemas and Definitions.

Defines OpenAI-compatible function calling schemas for Nemotron-3 Nano/Super.
"""

from typing import Any, Dict, List

ADD_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "add_task",
        "description": "Add a new task or action item to the user's structured task list.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title or action item description of the task",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Domain category",
                },
                "project": {
                    "type": "string",
                    "description": "Optional name of the project this task belongs to",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format (if specified or inferred)",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Priority level of the task",
                },
                "notes": {
                    "type": "string",
                    "description": "Additional context or details for the task",
                },
                "shift_existing": {
                    "type": "boolean",
                    "description": "If a task with the same name already exists, shift its deadline to due_date instead of asking",
                },
                "allow_different_thing": {
                    "type": "boolean",
                    "description": "If a task with the same name already exists, confirm this is for a completely different item and allow creating",
                },
                "allow_duplicate": {
                    "type": "boolean",
                    "description": "Bypass exact duplicate check",
                },
            },
            "required": ["title"],
        },
    },
}

QUERY_TASKS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_tasks",
        "description": "Query or list existing tasks and deadlines by domain, project, or status.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Filter by domain",
                },
                "project": {
                    "type": "string",
                    "description": "Filter by project name",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done", "overdue"],
                    "description": "Filter by status",
                },
            },
        },
    },
}

QUERY_CODE_CONTEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_code_context",
        "description": "Semantic search over code snippets, architecture notes, and technical memory chunks.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query or technical question",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter (typically 'code' or 'hackathon')",
                },
            },
            "required": ["query"],
        },
    },
}

SUMMARIZE_DAY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "summarize_day",
        "description": "Generate a daily summary or standup report across all projects and open tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to summarize in YYYY-MM-DD format, defaults to today",
                },
            },
        },
    },
}

QUERY_COURSEWORK_TASKS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_coursework_tasks",
        "description": "Query academic coursework tasks, lab submissions, and reports (e.g. CS 61C RISC-V).",
        "parameters": {
            "type": "object",
            "properties": {
                "course": {"type": "string", "description": "Optional course name or code (e.g. CS 61C)"},
                "status": {"type": "string", "enum": ["open", "overdue", "done"], "description": "Filter by status"}
            }
        }
    }
}

GET_HACKATHON_DEADLINES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_hackathon_deadlines",
        "description": "Retrieve active hackathon project deliverables, deadlines, and benchmark submissions.",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Hackathon project name"}
            }
        }
    }
}

LOG_CODE_SNIPPET_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "log_code_snippet",
        "description": "Store technical architecture notes, code snippets, or configuration in vector memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The code snippet or technical summary"},
                "project": {"type": "string", "description": "Target project"},
                "tags": {"type": "string", "description": "Comma-separated tags"}
            },
            "required": ["content"]
        }
    }
}

LOG_CODE_CONTEXT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "log_code_context",
        "description": "Store technical architecture notes, code snippets, or configuration in vector memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The code snippet or technical summary"},
                "project": {"type": "string", "description": "Target project"},
                "tags": {"type": "string", "description": "Comma-separated tags"}
            },
            "required": ["content"]
        }
    }
}

SEARCH_WEB_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the live web for current information that is NOT in Compass's "
            "stored memory. Use only after checking memory first. Good for: current "
            "deadlines, library/API changes since a note was written, facts that "
            "post-date stored context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query, under 390 chars"},
                "depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": "Use 'advanced' (2 credits) only when basic is insufficient",
                },
            },
            "required": ["query"],
        },
    },
}

INGEST_URL_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ingest_url",
        "description": (
            "Permanently add the contents of a web page to Compass's long-term "
            "memory so it becomes semantically searchable later. Use when the user "
            "says to remember, save, or read a link."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to extract and ingest"},
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Domain to store memory under",
                },
                "project": {"type": "string", "description": "Optional project name to associate with"},
            },
            "required": ["url", "domain"],
        },
    },
}

VERIFY_DEADLINE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "verify_deadline",
        "description": (
            "Compare a stored task's due_date against what the live web currently says. "
            "Searches for deadline announcements or updates and flags drift."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "The ID of the task to verify"},
            },
            "required": ["task_id"],
        },
    },
}

UPDATE_TASK_STATUS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_task_status",
        "description": "Update the status of an existing task (open, in_progress, done).",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to update",
                },
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done"],
                    "description": "The new status for the task",
                },
            },
            "required": ["task_id", "status"],
        },
    },
}

EDIT_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_task",
        "description": "Edit an existing task's title, due date, priority, or notes.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to edit",
                },
                "title": {
                    "type": "string",
                    "description": "New title for the task",
                },
                "due_date": {
                    "type": "string",
                    "description": "New due date in YYYY-MM-DD format",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "New priority level",
                },
                "notes": {
                    "type": "string",
                    "description": "Updated notes or context",
                },
            },
            "required": ["task_id"],
        },
    },
}

DELETE_TASK_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete_task",
        "description": "Permanently delete a task by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to delete",
                },
            },
            "required": ["task_id"],
        },
    },
}

LIST_PROJECTS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_projects",
        "description": "List all tracked projects partitioned across domains.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Optional domain to filter projects",
                },
            },
            "required": [],
        },
    },
}

QUERY_COURSEWORK_NOTES_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "query_coursework_notes",
        "description": "Searches and retrieves academic coursework notes and syllabus items.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search topic or course concept (e.g. RISC-V, hazards, calculus)",
                },
            },
            "required": ["query"],
        },
    },
}

SUMMARIZE_ACROSS_DOMAINS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "summarize_across_domains",
        "description": "Escalates to Nemotron-3 Ultra (550B) over pre-aggregated context for roadmap synthesis and cross-domain conflict analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to summarize in YYYY-MM-DD format, defaults to today",
                },
            },
            "required": [],
        },
    },
}

CHAT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "chat",
        "description": "General conversational fallback for greetings, questions, and non-actionable queries.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The user message or conversation input",
                },
            },
            "required": ["message"],
        },
    },
}

DETECT_DEADLINE_CONFLICTS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "detect_deadline_conflicts",
        "description": "Analyze all scheduled tasks and deadlines across hackathon, coursework, and code domains to detect overlapping commitments, resource contention, and deadline clustering within the next 7 days.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days ahead to scan for conflicts (default: 7)",
                },
            },
        },
    },
}

GET_CALENDAR_AVAILABILITY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_calendar_availability",
        "description": "Query free/busy windows and existing schedule blocks from Google Calendar and Compass tasks across a date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (defaults to today)",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (defaults to 7 days from start_date)",
                },
            },
        },
    },
}

PROPOSE_SCHEDULE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_schedule",
        "description": "Analyze unscheduled or pending tasks and use deterministic slot allocation to propose optimal, non-overlapping calendar time slots respecting working hours, buffers, and deadlines.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "Target date or start date for scheduling in YYYY-MM-DD format",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Optional domain filter for tasks to schedule",
                },
                "task_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific task IDs to schedule (if omitted, schedules all open unscheduled tasks)",
                },
            },
        },
    },
}

COMMIT_SCHEDULE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "commit_schedule",
        "description": "Commit approved time slots to tasks in PostgreSQL, synchronize with Google Calendar, and record to audit log. MUTATING ACTION requiring user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "integer"},
                            "scheduled_start": {"type": "string", "description": "ISO 8601 UTC start datetime"},
                            "scheduled_end": {"type": "string", "description": "ISO 8601 UTC end datetime"},
                        },
                        "required": ["task_id", "scheduled_start", "scheduled_end"],
                    },
                    "description": "List of task slot assignments to commit",
                },
                "rationale": {
                    "type": "string",
                    "description": "Summary rationale of the schedule plan",
                },
            },
            "required": ["assignments"],
        },
    },
}

DETECT_SCHEDULE_CONFLICTS_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "detect_schedule_conflicts",
        "description": "Analyze scheduled tasks, calendar events, and task dependency prerequisites to detect time overlaps, dependency timing violations, overdue/slipped tasks, and deadline breaches.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Optional start date filter (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "Optional end date filter (YYYY-MM-DD)"},
            },
        },
    },
}

DELEGATE_TO_SPECIALIST_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delegate_to_specialist",
        "description": "Delegate a specialized sub-task to the Specialist Multi-Agent System (coursework analysis, web research & verification, calendar free/busy scheduling, or memory retrieval).",
        "parameters": {
            "type": "object",
            "properties": {
                "capability": {
                    "type": "string",
                    "enum": ["coursework", "research", "calendar", "memory"],
                    "description": "Target specialist domain",
                },
                "task_description": {
                    "type": "string",
                    "description": "Detailed goal or query for the specialist agent",
                },
            },
            "required": ["capability", "task_description"],
        },
    },
}

ASSESS_FEASIBILITY_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "assess_feasibility",
        "description": (
            "Determine whether the user's open workload is actually achievable in the "
            "time they have, and produce a keep/defer/drop triage plan. Use when the "
            "user asks what to prioritise, what to drop, whether they can finish in "
            "time, or says they feel overloaded."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days available, default 5"},
                "hours_per_day": {"type": "number", "description": "Focused hours per day, default 4"},
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Optional: restrict to one domain",
                },
            },
            "required": [],
        },
    },
}

APPLY_TRIAGE_PLAN_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "apply_triage_plan",
        "description": "Apply a feasibility triage plan: mark dropped tasks done and keep deferred tasks open. MUTATING — requires user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "defer_ids": {"type": "array", "items": {"type": "integer"}, "description": "Task IDs to defer (set status=open)"},
                "drop_ids": {"type": "array", "items": {"type": "integer"}, "description": "Task IDs to drop (set status=done)"},
            },
            "required": [],
        },
    },
}

# Registered tools exposed to the Nemotron router
BASE_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    ADD_TASK_TOOL,
    QUERY_TASKS_TOOL,
    QUERY_COURSEWORK_TASKS_TOOL,
    QUERY_COURSEWORK_NOTES_TOOL,
    GET_HACKATHON_DEADLINES_TOOL,
    LOG_CODE_SNIPPET_TOOL,
    LOG_CODE_CONTEXT_TOOL,
    QUERY_CODE_CONTEXT_TOOL,
    SUMMARIZE_DAY_TOOL,
    SUMMARIZE_ACROSS_DOMAINS_TOOL,
    UPDATE_TASK_STATUS_TOOL,
    EDIT_TASK_TOOL,
    DELETE_TASK_TOOL,
    LIST_PROJECTS_TOOL,
    CHAT_TOOL,
    DETECT_DEADLINE_CONFLICTS_TOOL,
    GET_CALENDAR_AVAILABILITY_TOOL,
    PROPOSE_SCHEDULE_TOOL,
    COMMIT_SCHEDULE_TOOL,
    DETECT_SCHEDULE_CONFLICTS_TOOL,
    DELEGATE_TO_SPECIALIST_TOOL,
    ASSESS_FEASIBILITY_TOOL,
    APPLY_TRIAGE_PLAN_TOOL,
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Return active tool definitions for the Nemotron router.
    search_web, ingest_url, and verify_deadline are available when Tavily is enabled.
    """
    try:
        from backend.services.tavily import tavily_available
        if tavily_available():
            return BASE_TOOL_DEFINITIONS + [SEARCH_WEB_TOOL, INGEST_URL_TOOL, VERIFY_DEADLINE_TOOL]
    except Exception:
        pass
    return list(BASE_TOOL_DEFINITIONS)


TOOL_DEFINITIONS: List[Dict[str, Any]] = get_tool_definitions()

MUTATING_TOOLS = frozenset({
    "add_task",
    "edit_task",
    "update_task_status",
    "delete_task",
    "log_code_context",
    "log_code_snippet",
    "ingest_url",
    "apply_triage_plan",
    "commit_schedule",
})

