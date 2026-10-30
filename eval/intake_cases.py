"""Regression cases for chat task intake routing (questions vs commands vs pasted lists).

Each case is (message, expected outcome) where the outcome is what route_message decides offline:
  "no_task"      - nothing is created and no task tool is chosen
  "task:<title>" - a single add_task with exactly this title
  "preview"      - several tasks are previewed for confirmation (nothing written)
Used by tests/test_intake_eval_cases.py (CI gate) and by promptfooconfig.yaml.
"""

from __future__ import annotations

from typing import List, Tuple

TABLE = (
    "Title | Domain | Due | Priority | Duration\n"
    "Record demo video | Hackathon | Today, 9:00 PM | High | 4h\n"
    "Finalize Devpost submission | Hackathon | Today, 10:00 PM | High | 2h\n"
)

CASES: List[Tuple[str, str]] = [
    # capability / information questions never create tasks
    ("can you add deadlines for me?", "no_task"),
    ("Can you add deadlines for me", "no_task"),
    ("do you support adding deadlines?", "no_task"),
    ("could you create a task for me?", "no_task"),
    ("can I add a reminder?", "no_task"),
    ("can you add a task?", "no_task"),
    ("what are my deadlines?", "no_task"),
    ("when is the demo due?", "no_task"),
    ("how do I add a task?", "no_task"),
    ("hello", "no_task"),
    # commands with no task name ask for one
    ("add deadlines for me", "no_task"),
    ("add a task", "no_task"),
    ("create a task for tomorrow", "no_task"),
    # real commands keep working
    ("add task buy milk tomorrow 5pm", "task:Buy milk"),
    ("add a task: write the report by friday", "task:Write the report"),
    ("create task submit lab 5", "task:Submit lab 5"),
    ("please add task call mom tomorrow", "task:Call mom"),
    ("can you add a task to buy milk tomorrow?", "task:Buy milk"),
    ("could you add task review notes friday?", "task:Review notes"),
    ("add task Do it by Friday", "task:Do it"),
    # pasted lists are previewed, never written directly
    (TABLE, "preview"),
    ("add these tasks:\nWrite report | Coursework | Tomorrow | High | 2h\nFix bug | Code | Friday | Low | 1h", "preview"),
    ("add these tasks:\n- Lab report - tomorrow\n- Call mom - friday", "preview"),
    # ordinary pipe / tab / numbered text is not a task list
    ("explain this\nls | grep foo\ncat a | wc -l", "no_task"),
    ("Summarize these deadlines:\n1. Lab report\n2. Quiz prep", "no_task"),
]


async def decide(message: str) -> str:
    """Offline routing outcome for a message (no database, no model call)."""
    from backend.router import route_message

    skill, args, _reply = await route_message(message)
    if skill == "add_task":
        return f"task:{(args or {}).get('title', '')}"
    if skill == "add_tasks_preview":
        return "preview"
    return "no_task"
