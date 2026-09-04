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
from pathlib import Path
from typing import Optional

# Fix Windows console encoding before importing Rich
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Python 3.11+ tomllib or fallback
try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Load environment & persistent config (~/.compass/config.toml)
# ---------------------------------------------------------------------------
load_dotenv()

CONFIG_DIR = Path.home() / ".compass"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def load_config() -> tuple[str, str]:
    """Read API base URL and AUTH_TOKEN from ~/.compass/config.toml, env vars, or defaults."""
    api_url = os.getenv("COMPASS_API_URL")
    auth_token = os.getenv("AUTH_TOKEN")

    if CONFIG_FILE.exists():
        try:
            content = CONFIG_FILE.read_text(encoding="utf-8")
            if tomllib:
                cfg = tomllib.loads(content)
                api_url = api_url or cfg.get("api_url")
                auth_token = auth_token or cfg.get("auth_token")
            else:
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("api_url"):
                        api_url = api_url or line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("auth_token"):
                        auth_token = auth_token or line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass

    return api_url or "http://localhost:8000", auth_token or ""


API_BASE, AUTH_TOKEN = load_config()

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
    domain: str = typer.Option("code", "--domain", "-d", help="Domain: code, coursework, hackathon, general"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Associated project"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
):
    """📝 Log a memory entry (code context, coursework note, etc.)."""
    parts = [f"Log memory: {summary}"]
    parts.append(f"--domain {domain}")
    if project:
        parts.append(f"--project {project}")
    if tags:
        parts.append(f"--tags {tags}")

    message = " ".join(parts)
    result = _post("/chat", {"message": message})

    console.print(f"\n[compass.success]✅ Memory logged[/]")
    console.print(f"   Domain:   {_domain_text(domain)}")
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


@app.command()
def config(
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Set the Compass API base URL"),
    token: Optional[str] = typer.Option(None, "--token", "-t", help="Set the Bearer auth token"),
):
    """⚙️ View or update persistent CLI settings (~/.compass/config.toml)."""
    global API_BASE, AUTH_TOKEN
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if url is None and token is None:
        console.print(Panel(
            f"[bold cyan]Compass CLI Configuration[/]\n\n"
            f"  [bold]Config file:[/] {CONFIG_FILE}\n"
            f"  [bold]API URL:[/]     {API_BASE}\n"
            f"  [bold]Auth Token:[/]  {'*' * len(AUTH_TOKEN) if AUTH_TOKEN else '[dim]not set[/]'}",
            border_style="cyan",
        ))
        return

    new_url = url or API_BASE
    new_token = token or AUTH_TOKEN

    content = f'api_url = "{new_url}"\nauth_token = "{new_token}"\n'
    CONFIG_FILE.write_text(content, encoding="utf-8")
    API_BASE = new_url
    AUTH_TOKEN = new_token

    console.print(f"[compass.success]✅ Configuration saved to {CONFIG_FILE}[/]")
    console.print(f"   API URL:    {new_url}")
    console.print(f"   Auth Token: {'*' * len(new_token) if new_token else '[dim]not set[/]'}")


@app.command()
def login():
    """🔐 Interactively configure Compass API URL and Bearer token."""
    console.print(Panel(
        "[bold cyan]🧭 Compass Login[/]\n\n"
        "Configure your backend endpoint and authentication token.",
        border_style="cyan",
    ))
    new_url = Prompt.ask("Compass API Base URL", default=API_BASE)
    new_token = Prompt.ask("Bearer Auth Token", password=True, default=AUTH_TOKEN)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    content = f'api_url = "{new_url}"\nauth_token = "{new_token}"\n'
    CONFIG_FILE.write_text(content, encoding="utf-8")

    console.print(f"\n[compass.success]✅ Credentials saved to {CONFIG_FILE}[/]")


# ---------------------------------------------------------------------------
# Admin Sub-Typer
# ---------------------------------------------------------------------------
admin_app = typer.Typer(
    name="admin",
    help="🛠️ Admin maintenance commands (token usage, database consolidation)",
    no_args_is_help=True,
)
app.add_typer(admin_app, name="admin")


@admin_app.command("usage")
def admin_usage():
    """💰 Pretty-print token consumption and estimated USD cost across models."""
    data = _get("/admin/usage")

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


@admin_app.command("consolidate")
def admin_consolidate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate without applying updates"),
    threshold: float = typer.Option(0.95, "--threshold", "-t", help="Cosine similarity threshold"),
    stale_days: int = typer.Option(7, "--stale-days", "-s", help="Days before marking thread stale"),
):
    """🧹 Trigger memory consolidation and overdue task flagging."""
    import asyncio
    from backend.jobs.consolidate import run_consolidation

    mode_text = "[yellow](DRY RUN)[/]" if dry_run else "[green](LIVE)[/]"
    console.print(f"🧭 Running memory consolidation {mode_text}...")

    try:
        report = asyncio.run(run_consolidation(
            similarity_threshold=threshold,
            stale_thread_days=stale_days,
            dry_run=dry_run,
        ))
        console.print(f"\n[compass.success]✅ Consolidation complete[/]")
        console.print(f"  • Overdue tasks flagged: [bold]{report.get('overdue_tasks_flagged', 0)}[/]")
        console.print(f"  • Duplicate pairs merged: [bold]{report.get('duplicate_chunks_merged', 0)}[/]")
        console.print(f"  • Stale conversations rolled up: [bold]{report.get('stale_conversations_rolled_up', 0)}[/]")
    except Exception as e:
        console.print(f"[compass.error]❌ Consolidation failed: {e}[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app()
