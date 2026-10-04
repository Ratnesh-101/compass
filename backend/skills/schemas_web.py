"""
Compass — Web and Research Tool Schemas.

Defines schemas for Tavily live web search, deep multi-source research, web ingestion,
deadline verification, and verified memory persistence.
"""

from typing import Any, Dict

SEARCH_WEB_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the live web for current information that is NOT in Compass's "
            "stored memory. Automatically ranks results by domain authority. Use only "
            "after checking memory first. Good for: current deadlines, library/API changes, "
            "facts that post-date stored context."
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
            "memory so it becomes semantically searchable later. MUTATING — requires confirmation."
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
            "Searches for deadline announcements or updates and flags schedule drift with official verdicts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to verify against live web sources",
                },
            },
            "required": ["task_id"],
        },
    },
}

DEEP_RESEARCH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "deep_research",
        "description": (
            "Perform comprehensive, multi-step web research on a complex question or topic. "
            "Autonomously decomposes the topic into targeted subqueries, searches live authoritative sources, "
            "ranks evidence by domain authority, and synthesizes a structured report with numbered citations ([1], [2])."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The research question, technology comparison, or objective to investigate",
                },
                "max_subqueries": {
                    "type": "integer",
                    "description": "Maximum number of subqueries to decompose into (budget cap: 1-3, default 3)",
                },
                "search_depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": "Search depth level (default: basic)",
                },
            },
            "required": ["topic"],
        },
    },
}

SAVE_VERIFIED_FINDING_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "save_verified_finding",
        "description": (
            "Persist a high-confidence, verified research finding into long-term vector memory. "
            "Stores structured knowledge with provenance citations instead of polluting memory with noisy raw page dumps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "finding": {
                    "type": "string",
                    "description": "The concise fact or verified knowledge statement to persist",
                },
                "source_url": {
                    "type": "string",
                    "description": "The authoritative web source URL where the fact was verified",
                },
                "domain": {
                    "type": "string",
                    "enum": ["hackathon", "coursework", "code", "general"],
                    "description": "Compass knowledge domain to save under",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project name to associate with",
                },
                "citation": {
                    "type": "string",
                    "description": "Optional citation reference badge or notes",
                },
            },
            "required": ["finding", "source_url"],
        },
    },
}
