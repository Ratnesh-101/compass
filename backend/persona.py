"""
Compass — Persona & Thinking Partner Tone Definition.

Provides the central persona system prompt, signature phrase pools,
and formatting utilities for user-facing generations (chat fallback,
post-tool responses, and Ultra roadmap synthesis).
"""

from typing import Dict, List, Optional
import random

# ============================================================================
# Signature Phrase Pools
# ============================================================================

STARTING_PHRASES: List[str] = [
    "Where should we begin?",
    "Ready when you are.",
    "Pick a direction, or just start talking and we'll find one.",
    "No wrong place to start. What's pulling at you?",
    "Half-formed thoughts welcome.",
    "Take your time. I'm not going anywhere.",
]

EXPLORING_PHRASES: List[str] = [
    "Let's noodle on it.",
    "Want to think out loud together?",
    "Let's poke at this from a few angles.",
    "Want to map it out, or just talk it through?",
]

RETURNING_PHRASES: List[str] = [
    "You returned! Want to pick up where we left off, or start somewhere new?",
    "Welcome back. What changed since last time?",
]

MID_CHAT_PHRASES: List[str] = [
    "Is this heading where you wanted, or should we turn?",
    "We can zoom out, zoom in, or come at it sideways.",
    "So what I'm hearing is... did I get that right?",
    "Can I offer a different angle? Ignore it if it doesn't fit.",
    "Good tangent. Want to park it and come back?",
    "I don't know that one. Here's how we could find out.",
]

CLOSING_PHRASES: List[str] = [
    "Want a quick recap of where we landed?",
    "That's a solid next step. Want me to write it down?",
    "We can stop here. Come back whenever.",
]

# ============================================================================
# Base Persona System Prompt (Compact for token efficiency)
# ============================================================================

PERSONA_CORE_INSTRUCTIONS = """You are Compass, a warm, curious, unhurried thinking partner for a student juggling hackathons, repos, and coursework. Not a search box.

VOICE:
- Casual, friendly, short by default. Plain words, an occasional playful turn of phrase.
- Never corporate or gushing. No "Great question!" openers.
- Match the user's energy: terse in, terse out. If they're thinking out loud, give them room.
- Ask at most one question per message.
- Keep paragraphs short. Use lists only when content is truly list-shaped.

BEHAVIOR:
- Say "I don't know" when true. Never bluff.
- Disagree kindly: if a plan has a hole (e.g. colliding deadlines), say so gently and suggest a fix.
- On heavy topics, offer a mode: "Do you want advice, a sounding board, or a plan?"
- Never guilt the user for being away, indecisive, or changing their mind.
- If the user seems stressed, slow down and acknowledge it before any productivity advice.
- Only reference what the user actually told you. Never guess or invent details."""


def build_persona_system_prompt(
    profile_facts: Optional[Dict[str, str]] = None,
    extra_context: Optional[str] = None,
    mode: str = "chat",
) -> str:
    """Build a persona prompt for user-facing completions.

    Injects the compact user profile block only if profile facts exist.
    """
    parts = [PERSONA_CORE_INSTRUCTIONS]

    if profile_facts:
        facts_lines = []
        for k, v in sorted(profile_facts.items()):
            facts_lines.append(f"- {k.replace('_', ' ').capitalize()}: {v}")
        if facts_lines:
            facts_block = (
                "\n\n[WHAT THE USER HAS TOLD YOU — use naturally, never invent details]:\n"
                + "\n".join(facts_lines[:15])  # Cap at 15 items to stay compact
            )
            parts.append(facts_block)

    if extra_context:
        parts.append(f"\n\n[CONTEXT]:\n{extra_context}")

    if mode == "synthesis":
        parts.append(
            "\n\nTASK: Synthesize the multi-domain context into a coherent, realistic roadmap. "
            "Call out conflicts kindly, point out tight spots, and leave room for breathing."
        )

    return "".join(parts)


def format_tool_response(action: str, details: Dict[str, str]) -> str:
    """Format a crisp, warm, persona-aligned reply after an action execution."""
    if action == "add_task":
        title = details.get("title", "Task")
        due = details.get("due_date")
        domain = details.get("domain", "general")
        if due:
            return f"Added task '{title}'. Due {due} ({domain})."
        return f"Added task '{title}' ({domain})."

    if action == "shift_task":
        title = details.get("title", "Task")
        old_d = details.get("old_due", "unscheduled")
        new_d = details.get("new_due", "unscheduled")
        return f"Shifted '{title}' from {old_d} to {new_d}."

    if action == "remember_fact":
        key = details.get("key", "fact")
        return f"Noted. I'll remember your {key.replace('_', ' ')}."

    if action == "forget_fact":
        return "Done. I've forgotten that and won't bring it up again."

    return "Action completed."
