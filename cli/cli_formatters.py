# -*- coding: utf-8 -*-
"""
Compass CLI Formatters & Visual Themes.

Provides Rich tables, panels, branded color palettes, and presentation
logic for the Compass interactive command-line interface.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Domain color branding & status indicators
# ---------------------------------------------------------------------------
DOMAIN_COLORS = {
    "hackathon": "#f59e0b",   # Amber
    "coursework": "#3b82f6",  # Blue
    "code": "#10b981",        # Green
    "general": "dim white",
}

DOMAIN_EMOJI = {
    "hackathon": "🚀",
    "coursework": "📚",
    "code": "💻",
    "general": "📌",
}

STATUS_EMOJI = {
    "open": "⬚",
    "in_progress": "▶",
    "done": "✅",
    "overdue": "🔴",
}

PRIORITY_STYLE = {
    "urgent": "bold red",
    "high": "bold yellow",
    "medium": "white",
    "low": "dim",
}

STEP_COLORS = {
    "think": ("bold blue", "🧠 THINKING"),
    "tool_call": ("bold yellow", "🔧 TOOL CALL"),
    "observe": ("bold green", "👁️ RESULT"),
    "confirm_request": ("bold red", "⚠️ CONFIRM"),
    "critic": ("bold magenta", "⚖️ SELF-CRITIQUE"),
    "synthesize": ("bold cyan", "✨ SYNTHESIS"),
    "error": ("bold red", "❌ ERROR"),
    "done": ("bold green", "✅ COMPLETE"),
}

compass_theme = Theme({
    "hackathon": "bold #f59e0b",
    "coursework": "bold #3b82f6",
    "code": "bold #10b981",
    "general": "dim white",
    "compass.title": "bold cyan",
    "compass.error": "bold red",
    "compass.success": "bold green",
})

console = Console(theme=compass_theme, legacy_windows=False)


def format_domain_text(domain: str) -> Text:
    """Return a Rich Text styled with the domain's color and emoji."""
    emoji = DOMAIN_EMOJI.get(domain, "")
    color = DOMAIN_COLORS.get(domain, "white")
    return Text(f"{emoji} {domain}", style=f"bold {color}")


def render_tasks_table(task_list: List[Dict[str, Any]]) -> None:
    """Render formatted interactive tasks table."""
    table = Table(
        title="🧭 Compass Tasks",
        title_style="bold cyan",
        border_style="dim",
        show_lines=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Domain", width=12)
    table.add_column("Title", min_width=25)
    table.add_column("Status", width=12, justify="center")
    table.add_column("Priority", width=10, justify="center")
    table.add_column("Due", width=12, justify="center")
    table.add_column("Project", width=15)

    if not task_list:
        console.print(table)
        console.print("[dim]No tasks found.[/]")
        return

    for task in task_list:
        domain_name = task.get("domain", "general")
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        status_str = task.get("status", "open")
        status_icon = STATUS_EMOJI.get(status_str, "")
        priority_str = task.get("priority", "medium")
        priority_style = PRIORITY_STYLE.get(priority_str, "white")
        project_name = task["project"]["name"] if task.get("project") else "—"
        due_str = task.get("due_date") or "—"

        table.add_row(
            str(task.get("id", "")),
            Text(f"{emoji} {domain_name}", style=f"bold {color}"),
            task.get("title", ""),
            f"{status_icon} {status_str}",
            Text(priority_str, style=priority_style),
            due_str,
            project_name,
        )

    console.print(table)


def render_projects_view(project_list: List[Dict[str, Any]]) -> None:
    """Render grouped projects overview."""
    console.print(Panel("[compass.title]🧭 Compass Projects[/]", border_style="cyan"))
    if not project_list:
        console.print("[dim]No projects found.[/]")
        return

    grouped: Dict[str, list] = {}
    for proj in project_list:
        d = proj.get("domain", "general")
        grouped.setdefault(d, []).append(proj)

    for domain_name, projs in grouped.items():
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        console.print(f"\n  [{color}]{emoji} {domain_name.upper()}[/{color}]")
        for p in projs:
            desc = f" — {p['description']}" if p.get("description") else ""
            console.print(f"    • [bold]{p.get('name', '')}[/]{desc}")


def render_status_dashboard(data: Dict[str, Any]) -> None:
    """Render cognitive memory overview across domains."""
    console.print(Panel(
        "[compass.title]🧭 Compass Cognitive Memory Overview[/]",
        border_style="cyan",
    ))

    table = Table(title="Cross-Domain Active Metrics", border_style="dim", show_lines=True)
    table.add_column("Domain", width=18)
    table.add_column("Projects", justify="center", width=10)
    table.add_column("Open Tasks", justify="center", width=12)
    table.add_column("Nearest Deadline", min_width=32)

    domains = data.get("domains", {})
    for domain_name, stats in domains.items():
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        proj_count = stats.get("project_count", 0)
        task_count = stats.get("open_task_count", 0)
        deadline = stats.get("nearest_deadline")

        deadline_str = f"⏰ {deadline['title']} (due {deadline['due_date']})" if deadline else "—"
        table.add_row(
            Text(f"{emoji} {domain_name.upper()}", style=f"bold {color}"),
            str(proj_count),
            str(task_count),
            deadline_str,
        )

    console.print(table)
    total_tasks = data.get("total_open_tasks", 0)
    total_projects = data.get("total_projects", 0)
    console.print(f"\n  📊 [bold]{total_projects}[/] total projects  •  [bold]{total_tasks}[/] total open tasks across persistent memory\n")


def render_usage_tables(data: Dict[str, Any]) -> None:
    """Render token consumption breakdown and estimated USD cost."""
    console.print(Panel(
        "[compass.title]🧭 Compass Token Usage & Cost Overview[/]",
        border_style="cyan",
    ))

    table = Table(title="Model Consumption Breakdown", border_style="dim")
    table.add_column("Model", style="bold cyan")
    table.add_column("Calls", justify="right", style="magenta")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Est. Cost (USD)", justify="right", style="bold green")

    by_model = data.get("by_model", {})
    for m_id, stats in by_model.items():
        table.add_row(
            m_id.split("/")[-1],
            str(stats.get("calls", 0)),
            f"{stats.get('input_tokens', 0):,}",
            f"{stats.get('output_tokens', 0):,}",
            f"${stats.get('estimated_cost_usd', 0.0):.6f}",
        )

    console.print(table)
    console.print(
        f"\n  [bold]Total Input:[/]  {data.get('total_input_tokens', 0):,} tokens\n"
        f"  [bold]Total Output:[/] {data.get('total_output_tokens', 0):,} tokens\n"
        f"  [bold green]Total Estimated Cost:[/] ${data.get('total_estimated_cost_usd', 0.0):.6f}\n"
    )

    tavily_data = data.get("tavily")
    if tavily_data:
        t_table = Table(title="Tavily Web Search & Extraction Credits", border_style="dim")
        t_table.add_column("Operation", style="bold yellow")
        t_table.add_column("Calls", justify="right", style="magenta")
        t_table.add_column("Credits Consumed", justify="right", style="bold green")
        by_op = tavily_data.get("by_operation", {})
        for op, stats in by_op.items():
            t_table.add_row(op.title(), str(stats.get("calls", 0)), str(stats.get("credits", 0)))
        console.print(t_table)
        console.print(f"  [bold yellow]Total Tavily Credits:[/] {tavily_data.get('total_credits', 0)} credits\n")


def render_agent_activity_table(entries: List[Dict[str, Any]]) -> None:
    """Render agent mutations audit trail."""
    if not entries:
        console.print("[dim]No agent activity recorded yet.[/]")
        return

    table = Table(
        title="📋 Agent Activity Log (Audit Trail)",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Log ID", style="bold", justify="right")
    table.add_column("Tool", style="yellow")
    table.add_column("Target", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Timestamp", style="dim")
    table.add_column("Run ID", style="dim cyan")

    for item in entries:
        lid = str(item.get("id", ""))
        tool = item.get("tool", "")
        tbl = item.get("affected_table", "tasks")
        aff_id = str(item.get("affected_id") or "")
        reverted = item.get("is_reverted", False)
        st_badge = "[red]REVERTED[/]" if reverted else "[green]ACTIVE[/]"
        ts = item.get("created_at", "")[:19].replace("T", " ")
        rid = (item.get("run_id") or "")[:12]

        table.add_row(lid, tool, f"{tbl} #{aff_id}", st_badge, ts, rid)

    console.print(table)
    console.print("[dim]Revert any mutation using: compass agent-undo --log-id <ID>[/]")


def render_agent_stats_view(data: Dict[str, Any]) -> None:
    """Render self-critique pass effectiveness metrics."""
    tot = data.get("total_runs_analyzed", 0)
    crit = data.get("runs_with_critique", 0)
    flagged = data.get("critique_issues_flagged", 0)
    rate = data.get("critique_effectiveness_rate", 0.0)

    panel_content = (
        f"[bold]Total Agent Runs Analyzed:[/] {tot}\n"
        f"[bold]Runs with Self-Critique Pass:[/] {crit}\n"
        f"[bold]Critique Issues Flagged / Revised:[/] [yellow]{flagged}[/]\n"
        f"[bold]Critique Intervention Rate:[/] [cyan]{rate}%[/]\n\n"
        "[dim]A single-model self-critique pass checks plan constraints against real database data before final synthesis.[/]"
    )
    console.print(Panel(panel_content, title="⚖️ Self-Critique Effectiveness", border_style="magenta"))

    recent = data.get("recent_critique_evaluations", [])
    if recent:
        t = Table(title="Recent Self-Critique Evaluations", box=box.SIMPLE, header_style="bold magenta")
        t.add_column("Run ID", style="dim cyan")
        t.add_column("Flagged Issue?", justify="center")
        t.add_column("Critique Summary", style="white")

        for ev in recent[:5]:
            f_icon = "⚠️ YES" if ev.get("flagged_issue") else "✅ NO"
            t.add_row(ev.get("run_id", "")[:12], f_icon, ev.get("critique_summary", "")[:80])
        console.print(t)


def render_agent_runs_table(runs: List[Dict[str, Any]]) -> None:
    """Render recent agent execution runs history."""
    if not runs:
        console.print("[dim]No agent runs found.[/]")
        return

    table = Table(
        title="📜 Compass Agent Runs History",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Run ID", style="dim cyan")
    table.add_column("Goal", style="white")
    table.add_column("Status", style="bold")
    table.add_column("Steps", justify="right", style="magenta")
    table.add_column("Created", style="dim")
    table.add_column("Conv ID", style="dim yellow")

    for r in runs:
        rid = (r.get("id") or "")[:18]
        goal = (r.get("goal") or "")[:40]
        if len(r.get("goal") or "") > 40:
            goal += "..."
        status = r.get("status", "unknown")
        st_style = "[green]COMPLETED[/]" if status == "completed" else f"[yellow]{status.upper()}[/]"
        steps = str(r.get("steps_count", 0))
        created = (r.get("created_at") or "")[:19].replace("T", " ")
        cid = (r.get("conversation_id") or "—")[:8]
        table.add_row(rid, goal, st_style, steps, created, cid)

    console.print(table)


def render_briefing_panel(data: Dict[str, Any]) -> None:
    """Render autonomous morning executive briefing."""
    if not data.get("briefing"):
        console.print("[dim]No proactive briefing available yet. Trigger one with: curl -X POST http://localhost:8000/api/agent/trigger-nightly[/]")
        return

    run_id = data.get("run_id", "Unknown")
    created = data.get("created_at", "")[:19].replace("T", " ")
    briefing_text = data.get("briefing", "")
    steps_count = data.get("steps_count", 0)

    content = (
        f"[bold cyan]Run ID:[/] {run_id}  |  [bold]Generated:[/] {created}  |  [bold]Steps:[/] {steps_count}\n\n"
        f"{briefing_text}"
    )
    console.print(Panel(
        content,
        title="🌅 Autonomous Morning Executive Briefing",
        border_style="magenta",
        padding=(1, 2),
    ))


render_agent_briefing_panel = render_briefing_panel
