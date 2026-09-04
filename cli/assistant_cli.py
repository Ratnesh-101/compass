"""
Compass — CLI Interface.

Interactive command-line client for the Compass personal AI assistant.
Communicates with the backend at http://localhost:8000 via httpx.

Usage:
    compass --help          Show all available commands
    compass chat            Interactive conversation REPL
    compass ask "question"  One-shot question
    compass tasks           View current tasks
    compass add "title"     Add a new task
    compass projects        List tracked projects
    compass log "summary"   Log a memory entry
    compass status          Dashboard overview

Install:
    pip install -e ./cli
"""

import os
import sys
from typing import Optional

# Fix Windows console encoding before importing Rich
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import httpx
import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_BASE = os.getenv("COMPASS_API_URL", "http://localhost:8000")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")

# Domain color branding
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

# ---------------------------------------------------------------------------
# Rich Console
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Typer App
# ---------------------------------------------------------------------------
app = typer.Typer(
    name="compass",
    help="🧭 Compass — Your personal AI assistant CLI",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------

def _headers() -> dict:
    """Return auth headers for API requests."""
    if not AUTH_TOKEN:
        console.print(
            "[compass.error]❌ AUTH_TOKEN not set. "
            "Copy .env.example → .env and set your token.[/]"
        )
        raise typer.Exit(1)
    return {"Authorization": f"Bearer {AUTH_TOKEN}"}


def _get(path: str, params: dict | None = None) -> dict:
    """Make an authenticated GET request to the backend."""
    try:
        resp = httpx.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print("[compass.error]❌ Cannot connect to backend at "
                      f"{API_BASE}. Is the server running?[/]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[compass.error]❌ API error {e.response.status_code}: "
                      f"{e.response.text}[/]")
        raise typer.Exit(1)


def _post(path: str, data: dict) -> dict:
    """Make an authenticated POST request to the backend."""
    try:
        resp = httpx.post(f"{API_BASE}{path}", headers=_headers(), json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print("[compass.error]❌ Cannot connect to backend at "
                      f"{API_BASE}. Is the server running?[/]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[compass.error]❌ API error {e.response.status_code}: "
                      f"{e.response.text}[/]")
        raise typer.Exit(1)


def _domain_text(domain: str) -> Text:
    """Return a Rich Text styled with the domain's color."""
    emoji = DOMAIN_EMOJI.get(domain, "")
    color = DOMAIN_COLORS.get(domain, "white")
    return Text(f"{emoji} {domain}", style=f"bold {color}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def chat():
    """💬 Interactive conversation with Compass."""
    console.print(Panel(
        "[compass.title]🧭 Compass Chat[/]\n"
        "Type your message and press Enter. Type [bold]quit[/] or [bold]exit[/] to leave.",
        border_style="cyan",
    ))

    conversation_id: str | None = None

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye! 👋[/]")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye! 👋[/]")
            break

        if not user_input.strip():
            continue

        payload = {"message": user_input}
        if conversation_id:
            payload["conversation_id"] = conversation_id

        result = _post("/chat", payload)
        conversation_id = result.get("conversation_id")
        response_text = result.get("response", "")
        skill = result.get("skill_used")

        skill_tag = f" [dim]({skill})[/]" if skill else ""
        console.print(f"\n[bold green]Compass[/]{skill_tag}: {response_text}")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Your question for Compass"),
):
    """❓ Ask a one-shot question."""
    result = _post("/chat", {"message": query})
    response_text = result.get("response", "")
    skill = result.get("skill_used")

    skill_tag = f" [dim]({skill})[/]" if skill else ""
    console.print(f"\n[bold green]Compass[/]{skill_tag}: {response_text}")


@app.command()
def add(
    title: str = typer.Argument(..., help="Task title"),
    domain: str = typer.Option("general", "--domain", "-d", help="Domain: hackathon, coursework, code, general"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    due: Optional[str] = typer.Option(None, "--due", help="Due date (YYYY-MM-DD)"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Additional notes"),
):
    """➕ Add a new task via the chat endpoint."""
    parts = [f"Add task: {title}"]
    parts.append(f"--domain {domain}")
    if project:
        parts.append(f"--project {project}")
    if due:
        parts.append(f"--due {due}")
    if notes:
        parts.append(f"--notes {notes}")

    message = " ".join(parts)
    result = _post("/chat", {"message": message})

    console.print(f"\n[compass.success]✅ Task sent to Compass[/]")
    console.print(f"   Response: {result.get('response', '')}")


@app.command()
def tasks(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project name"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """📋 View current tasks."""
    params = {}
    if domain:
        params["domain"] = domain
    if project:
        params["project"] = project
    if status:
        params["status"] = status

    data = _get("/tasks", params)
    task_list = data.get("tasks", [])

    if not task_list:
        console.print("[dim]No tasks found.[/]")
        return

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

    for task in task_list:
        domain_name = task["domain"]
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        status_str = task["status"]
        status_icon = STATUS_EMOJI.get(status_str, "")
        priority_str = task["priority"]
        priority_style = PRIORITY_STYLE.get(priority_str, "white")
        project_name = task["project"]["name"] if task.get("project") else "—"
        due_str = task.get("due_date") or "—"

        table.add_row(
            str(task["id"]),
            Text(f"{emoji} {domain_name}", style=f"bold {color}"),
            task["title"],
            f"{status_icon} {status_str}",
            Text(priority_str, style=priority_style),
            due_str,
            project_name,
        )

    console.print(table)


@app.command()
def projects(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
):
    """📁 List tracked projects."""
    params = {}
    if domain:
        params["domain"] = domain

    data = _get("/projects", params)
    project_list = data.get("projects", [])

    if not project_list:
        console.print("[dim]No projects found.[/]")
        return

    console.print(Panel("[compass.title]🧭 Compass Projects[/]", border_style="cyan"))

    # Group by domain
    grouped: dict[str, list] = {}
    for proj in project_list:
        d = proj["domain"]
        grouped.setdefault(d, []).append(proj)

    for domain_name, projs in grouped.items():
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        console.print(f"\n  [{color}]{emoji} {domain_name.upper()}[/{color}]")
        for p in projs:
            desc = f" — {p['description']}" if p.get("description") else ""
            console.print(f"    • [bold]{p['name']}[/]{desc}")


@app.command()
def log(
    summary: str = typer.Argument(..., help="Summary of what to log"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Associated project"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
):
    """📝 Log a memory entry (code context, coursework note, etc.)."""
    parts = [f"Log memory: {summary}"]
    if project:
        parts.append(f"--project {project}")
    if tags:
        parts.append(f"--tags {tags}")

    message = " ".join(parts)
    result = _post("/chat", {"message": message})

    console.print(f"\n[compass.success]✅ Memory logged[/]")
    console.print(f"   Response: {result.get('response', '')}")


@app.command()
def status():
    """📊 Dashboard overview — deadlines, task counts, and activity."""
    data = _get("/dashboard")

    console.print(Panel(
        "[compass.title]🧭 Compass Dashboard[/]",
        border_style="cyan",
    ))

    total_tasks = data.get("total_open_tasks", 0)
    total_projects = data.get("total_projects", 0)
    console.print(f"\n  📊 [bold]{total_projects}[/] projects  •  "
                  f"[bold]{total_tasks}[/] open tasks\n")

    domains = data.get("domains", {})
    for domain_name, stats in domains.items():
        color = DOMAIN_COLORS.get(domain_name, "white")
        emoji = DOMAIN_EMOJI.get(domain_name, "")
        proj_count = stats.get("project_count", 0)
        task_count = stats.get("open_task_count", 0)
        deadline = stats.get("nearest_deadline")

        console.print(f"  [{color}]{emoji} {domain_name.upper()}[/{color}]")
        console.print(f"    Projects: {proj_count}  |  Open tasks: {task_count}")

        if deadline:
            console.print(
                f"    ⏰ [bold yellow]Next deadline:[/] {deadline['title']} "
                f"(due {deadline['due_date']})"
            )
        console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app()
