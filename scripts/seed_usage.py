#!/usr/bin/env python3
"""
Compass — Usage Seeding & Activity Harness.

Exercises all skills (add_task, query_tasks, query_code_context,
summarize_day, log_code_context, query_coursework_notes, search_web)
dozens of times to populate realistic usage metrics for `compass admin usage`
and `/api/usage/summary`.
"""

import os
import sys
import time
import httpx
from pathlib import Path

# Add project root to path
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from backend.config import get_settings
from backend.services.usage import record_usage, get_usage_summary

settings = get_settings()

API_BASE = os.getenv("COMPASS_API_URL", "http://127.0.0.1:8000")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", settings.AUTH_TOKEN or "dev-token")
HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}

SCENARIOS = [
    # Router / Add Task
    ("add_task", "add a task: Prepare submission slide deck for Best Apps & Agents track, domain hackathon, priority high"),
    ("add_task", "add a task: Review distributed systems checkpoint 3 lab, domain coursework, due 2026-09-12"),
    ("add_task", "add a task: Refactor vector cosine distance query in vector.py, domain code, priority medium"),
    ("add_task", "add a task: Record 3-minute video walkthrough of Compass copilot, domain hackathon, priority urgent"),
    ("add_task", "add a task: Write comprehensive unit tests for rate limiting middleware, domain code, priority high"),
    ("add_task", "add a task: Submit final Devpost entry before deadline, domain hackathon, due 2026-09-10"),
    ("add_task", "add a task: Study GPU memory hierarchy and TensorRT optimizations, domain coursework"),
    ("add_task", "add a task: Verify SSE token streaming on CLI client, domain code"),

    # Task Queries
    ("query_tasks", "What are my upcoming hackathon deliverables?"),
    ("query_tasks", "List all open tasks across coursework and code"),
    ("query_tasks", "Show me tasks due in the next 48 hours"),
    ("query_tasks", "What high priority items remain for the Compass hackathon?"),

    # Code Context Queries
    ("query_code_context", "How is the pgvector HNSW index initialized in schema.sql?"),
    ("query_code_context", "Where is the sliding window rate limiter defined in backend/main.py?"),
    ("query_code_context", "Explain how Matryoshka 768-dim embeddings are generated"),
    ("query_code_context", "Show me how the CLI consumes the SSE stream endpoint"),

    # Coursework Queries
    ("query_coursework_notes", "What notes do we have on distributed consensus and Raft?"),
    ("query_coursework_notes", "Summarize the key takeaways from lecture 4 on memory consistency"),
    ("query_coursework_notes", "Check upcoming deadlines for CS 61C assignments"),

    # Multi-domain Synthesis (Ultra)
    ("summarize_day", "Summarize my day across coursework, hackathon, and coding progress."),
    ("summarize_day", "Provide an executive briefing on what I accomplished and what is overdue."),
    ("summarize_day", "Give me a prioritized roadmap for tomorrow morning."),

    # Web Search
    ("search_web", "What are the latest updates on NVIDIA Nemotron 3 models in 2026?"),
    ("search_web", "Check current Devpost hackathon submission guidelines for Best Apps and Agents"),
]

CODE_SNIPPETS = [
    ("Configured HNSW index with m=16, ef_construction=64 on memory_chunks.embedding", "code", "compass-db"),
    ("Added sliding-window IP rate limiter to /api/chat and /api/chat/stream endpoints", "code", "compass-backend"),
    ("Implemented streaming response in assistant_cli.py using httpx.stream", "code", "compass-cli"),
    ("Created live usage counter in App.jsx wired to /api/usage/summary", "code", "compass-ui"),
    ("Integrated Tavily search_web skill to augment router with external web lookup", "code", "compass-skills"),
]


def seed_via_http():
    """Attempt to seed via live HTTP calls against the running backend."""
    print(f"Connecting to backend at {API_BASE}...")
    success_count = 0

    with httpx.Client(base_url=API_BASE, headers=HEADERS, timeout=15.0) as client:
        # Check health
        try:
            r = client.get("/health")
            print(f"Health check: HTTP {r.status_code}")
        except Exception as e:
            print(f"Backend not responding over HTTP ({e}); switching to direct recorder.")
            return False

        # 1. Log code snippets
        for snippet, domain, project in CODE_SNIPPETS:
            try:
                r = client.post("/api/log", json={"content": snippet, "domain": domain, "project": project})
                if r.status_code == 200:
                    success_count += 1
            except Exception:
                pass

        # 2. Run chat queries
        for skill_hint, query in SCENARIOS:
            try:
                r = client.post("/api/chat", json={"message": query})
                if r.status_code == 200:
                    success_count += 1
            except Exception:
                pass

    print(f"Completed {success_count} live HTTP requests.")
    return success_count > 0


def seed_direct_usage():
    """Directly record realistic token usage metrics in usage_log for testing / demos."""
    print("Directly seeding usage_log with realistic multi-turn model telemetry...")
    import random

    models = {
        settings.ROUTER_MODEL: (60, 180, 20, 60),        # Nano: prompt 60-180, comp 20-60
        settings.SKILL_MODEL: (120, 350, 80, 220),       # Super: prompt 120-350, comp 80-220
        settings.SYNTHESIS_MODEL: (400, 900, 250, 600),  # Ultra: prompt 400-900, comp 250-600
        settings.EMBEDDING_MODEL: (32, 128, 0, 0),       # Qwen: prompt 32-128
    }

    total_seeded = 0
    # Seed 35 Router calls (Nano)
    for _ in range(35):
        p_min, p_max, c_min, c_max = models[settings.ROUTER_MODEL]
        record_usage(settings.ROUTER_MODEL, random.randint(p_min, p_max), random.randint(c_min, c_max))
        total_seeded += 1

    # Seed 20 Super calls (Skills)
    for _ in range(20):
        p_min, p_max, c_min, c_max = models[settings.SKILL_MODEL]
        record_usage(settings.SKILL_MODEL, random.randint(p_min, p_max), random.randint(c_min, c_max))
        total_seeded += 1

    # Seed 18 Ultra calls (Synthesis)
    for _ in range(18):
        p_min, p_max, c_min, c_max = models[settings.SYNTHESIS_MODEL]
        record_usage(settings.SYNTHESIS_MODEL, random.randint(p_min, p_max), random.randint(c_min, c_max))
        total_seeded += 1

    # Seed 22 Embedding calls (Qwen3)
    for _ in range(22):
        p_min, p_max, c_min, c_max = models[settings.EMBEDDING_MODEL]
        record_usage(settings.EMBEDDING_MODEL, random.randint(p_min, p_max), 0)
        total_seeded += 1

    summary = get_usage_summary()
    print(f"Seeded {total_seeded} usage records.")
    print(f"Total requests: {summary['total_requests']}")
    print(f"Total tokens: {summary['total_input_tokens'] + summary['total_output_tokens']}")
    print(f"Total cost: ${summary['total_estimated_cost_usd']:.5f}")


if __name__ == "__main__":
    http_ok = seed_via_http()
    if not http_ok:
        seed_direct_usage()
    else:
        # Also ensure rich statistical variety
        seed_direct_usage()
