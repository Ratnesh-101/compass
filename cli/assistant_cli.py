# -*- coding: utf-8 -*-
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
from __future__ import annotations

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
from rich import box
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

    resolved_url = (api_url or os.getenv("COMPASS_API_URL") or "http://localhost:8000").strip().rstrip("/")
    resolved_token = (auth_token or os.getenv("AUTH_TOKEN") or "dev-token").strip()
    return resolved_url, resolved_token


API_BASE, AUTH_TOKEN = load_config()

from cli.cli_formatters import (
    DOMAIN_COLORS,
    DOMAIN_EMOJI,
    PRIORITY_STYLE,
    STATUS_EMOJI,
    STEP_COLORS,
    console,
    format_domain_text,
    render_agent_activity_table,
    render_agent_runs_table,
    render_agent_stats_view,
    render_briefing_panel,
    render_projects_view,
    render_status_dashboard,
    render_tasks_table,
    render_usage_tables,
)
from cli.cli_agent_runner import (
    run_feasibility_triage_session,
    run_interactive_agent_session,
)

_domain_text = format_domain_text

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
        resp = httpx.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=30.0)
        resp.raise_for_status()
        return resp.json()
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        console.print("[compass.error]❌ Cannot connect to backend at "
                      f"{API_BASE} (error: {e}). Is the server running?[/]")
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


def _stream_chat(payload: dict) -> tuple[str, str | None, str | None]:
    """Consume the SSE streaming endpoint /api/chat/stream, printing tokens live.

    Returns (full_response, conversation_id, skill_used).
    Falls back cleanly to synchronous _post('/chat', payload) if streaming fails.
    """
    import json
    url = f"{API_BASE}/api/chat/stream"
    full_text = []
    conv_id = payload.get("conversation_id")
    skill_used = None

    try:
        with httpx.stream("POST", url, headers=_headers(), json=payload, timeout=60.0) as resp:
            if resp.status_code != 200:
                res = _post("/chat", payload)
                resp_text = res.get("response", "")
                console.print(resp_text)
                return resp_text, res.get("conversation_id"), res.get("skill_used")

            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    ev = json.loads(line[6:])
                except Exception:
                    continue

                ev_type = ev.get("type")
                if ev_type == "token":
                    val = ev.get("value", "")
                    console.print(val, end="", markup=False)
                    full_text.append(val)
                elif ev_type == "done":
                    conv_id = ev.get("conversation_id", conv_id)
                    skill_used = ev.get("skill_used")
                elif ev_type == "error":
                    err_msg = ev.get("message", "Unknown error")
                    console.print(f"\n[dim red]Error: {err_msg}[/]")

            console.print()
            return "".join(full_text), conv_id, skill_used

    except (httpx.ConnectError, httpx.HTTPError):
        res = _post("/chat", payload)
        resp_text = res.get("response", "")
        console.print(resp_text)
        return resp_text, res.get("conversation_id"), res.get("skill_used")


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
    """💬 Interactive conversation with Compass (streaming tokens live)."""
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

        console.print("\n[bold green]Compass[/]: ", end="")
        _, new_conv_id, skill = _stream_chat(payload)
        if new_conv_id:
            conversation_id = new_conv_id
        if skill:
            console.print(f"[dim]({skill})[/]")


@app.command()
def ask(
    query: str = typer.Argument(..., help="Your question for Compass"),
):
    """❓ Ask a one-shot question (streamed live from Nebius Token Factory)."""
    console.print("\n[bold green]Compass[/]: ", end="")
    _, _, skill = _stream_chat({"message": query})
    if skill:
        console.print(f"[dim]({skill})[/]")


@app.command()
def add(
    title: str = typer.Argument(..., help="Task title"),
    domain: str = typer.Option("general", "--domain", "-d", help="Domain: hackathon, coursework, code, general"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    due: Optional[str] = typer.Option(None, "--due", help="Due date (YYYY-MM-DD)"),
    priority: Optional[str] = typer.Option(None, "--priority", help="Priority: urgent, high, medium, low"),
    notes: Optional[str] = typer.Option(None, "--notes", "-n", help="Additional notes"),
):
    """➕ Add a new task via the chat endpoint."""
    parts = [f"Add task: {title}"]
    parts.append(f"--domain {domain}")
    if project:
        parts.append(f"--project {project}")
    if due:
        parts.append(f"--due {due}")
    if priority:
        parts.append(f"--priority {priority}")
    if notes:
        parts.append(f"--notes {notes}")

    message = " ".join(parts)
    result = _post("/chat", {"message": message})

    console.print("\n[compass.success]✅ Task sent to Compass[/]")
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
    render_tasks_table(data.get("tasks", []))


@app.command()
def projects(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Filter by domain"),
):
    """📁 List tracked projects."""
    params = {}
    if domain:
        params["domain"] = domain

    data = _get("/projects", params)
    render_projects_view(data.get("projects", []))


@app.command()
def log(
    summary: str = typer.Argument(..., help="Summary of what to log"),
    domain: str = typer.Option("code", "--domain", "-d", help="Domain: code, coursework, hackathon, general"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Associated project"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags"),
):
    """📝 Log a memory entry (code context, coursework note, etc.)."""
    payload = {
        "summary": summary,
        "domain": domain,
        "project": project,
        "tags": tags,
    }
    result = _post("/api/log", payload)

    console.print("\n[compass.success]✅ Memory logged to pgvector with 768-dim embedding[/]")
    console.print(f"   Domain:   {_domain_text(domain)}")
    if project:
        console.print(f"   Project:  [bold]{project}[/]")
    if tags:
        console.print(f"   Tags:     [cyan]{tags}[/]")
    console.print(f"   Status:   {result.get('message', 'Logged')}")


@app.command()
def status():
    """📊 Dashboard overview — formatted terminal table across Hackathon, Coursework, Code."""
    data = _get("/dashboard")
    render_status_dashboard(data)



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
    render_usage_tables(data)


@admin_app.command("consolidate")
def admin_consolidate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate without applying updates"),
    threshold: float = typer.Option(0.95, "--threshold", "-t", help="Cosine similarity threshold"),
    stale_days: int = typer.Option(7, "--stale-days", "-s", help="Days before marking thread stale"),
):
    """🧹 Trigger memory consolidation and overdue task flagging."""
    mode_text = "[yellow](DRY RUN)[/]" if dry_run else "[green](LIVE)[/]"
    console.print(f"🧭 Triggering memory consolidation {mode_text}...")

    payload = {
        "dry_run": dry_run,
        "similarity_threshold": threshold,
        "stale_thread_days": stale_days,
    }

    try:
        report = _post("/admin/consolidate", payload)
        console.print("\n[compass.success]✅ Consolidation complete[/]")
        console.print(f"  • Overdue tasks flagged: [bold]{report.get('overdue_tasks_flagged', 0)}[/]")
        console.print(f"  • Duplicate pairs merged: [bold]{report.get('duplicate_chunks_merged', 0)}[/]")
        console.print(f"  • Stale conversations rolled up: [bold]{report.get('stale_conversations_rolled_up', 0)}[/]")
    except Exception as e:
        console.print(f"[compass.error]❌ Remote consolidation request failed: {e}[/]")


# ---------------------------------------------------------------------------
# Agent — Autonomous ReAct multi-step planner
# ---------------------------------------------------------------------------
@app.command()
def agent(
    goal: str = typer.Argument(..., help="The goal for the agent to accomplish"),
    max_steps: int = typer.Option(8, "--max-steps", "-m", help="Max reasoning steps"),
    no_critic: bool = typer.Option(False, "--no-critic", help="Disable self-critique pass"),
    demo_reject: bool = typer.Option(False, "--demo-reject", help="Run in pre-loaded reject-path demo mode"),
    conversation_id: Optional[str] = typer.Option(None, "--conversation-id", "-c", help="Link run to an existing conversation"),
):
    """🧠 Run the autonomous agent to plan, analyze, and act on your tasks.

    The agent reasons step-by-step, calling tools autonomously to gather data
    and propose solutions. State-mutating actions require your confirmation.

    Examples:
        compass agent "Plan my week considering all deadlines"
        compass agent "Flag deadline conflicts and suggest resolutions"
        compass agent "Write a retrospective for the Compass project"
        compass agent --demo-reject "Reschedule conflicting tasks"
    """
    run_interactive_agent_session(
        api_base=API_BASE,
        auth_token=AUTH_TOKEN,
        goal=goal,
        max_steps=max_steps,
        no_critic=no_critic,
        demo_reject=demo_reject,
        conversation_id=conversation_id,
    )


@app.command("agent-undo")
def agent_undo(
    run_id: Optional[str] = typer.Option(None, "--run-id", "-r", help="Specific run ID to revert"),
    log_id: Optional[int] = typer.Option(None, "--log-id", "-l", help="Specific audit log entry ID to revert"),
):
    """Revert an agent-executed mutation using the audit log."""
    try:
        resp = httpx.post(
            f"{API_BASE}/api/agent/undo",
            json={"run_id": run_id, "audit_log_id": log_id},
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ok":
            console.print(f"[green]✅ {data.get('message')}[/]")
            if "reverted" in data:
                console.print(f"[dim]Reverted: {data['reverted']}[/]")
        else:
            console.print(f"[yellow]⚠️ {data.get('message', 'Nothing to undo')}[/]")
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to undo: {e}[/]")


@app.command("agent-activity")
def agent_activity(limit: int = typer.Option(15, "--limit", "-n", help="Number of entries to show")):
    """📋 View recent agent mutations from the audit log with per-item IDs for undo."""
    try:
        resp = httpx.get(f"{API_BASE}/api/agent/activity?limit={limit}", timeout=15.0)
        resp.raise_for_status()
        entries = resp.json().get("activity", [])
        render_agent_activity_table(entries)
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch activity: {e}[/]")


@app.command("agent-stats")
def agent_stats():
    """⚖️ Surface real self-critique pass effectiveness metrics."""
    try:
        resp = httpx.get(f"{API_BASE}/api/agent/critique-stats", timeout=15.0)
        resp.raise_for_status()
        render_agent_stats_view(resp.json())
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch critique stats: {e}[/]")


@app.command("agent-runs")
def agent_runs(
    limit: int = typer.Option(15, "--limit", "-n", help="Number of runs to show"),
    conversation_id: Optional[str] = typer.Option(None, "--conversation-id", "-c", help="Filter runs by conversation ID"),
):
    """📜 List recent agent execution runs with statuses and step counts."""
    try:
        url = f"{API_BASE}/api/agent/runs?limit={limit}"
        if conversation_id:
            url += f"&conversation_id={conversation_id}"
        resp = httpx.get(url, timeout=15.0)
        resp.raise_for_status()
        render_agent_runs_table(resp.json().get("runs", []))
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch agent runs: {e}[/]")


@app.command("agent-briefing")
def agent_briefing():
    """🌅 Inspect the latest autonomous overnight proactive briefing."""
    try:
        resp = httpx.get(f"{API_BASE}/api/agent/proactive-briefing", timeout=15.0)
        resp.raise_for_status()
        render_briefing_panel(resp.json())
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch proactive briefing: {e}[/]")


@app.command("triage")
def triage(
    days: int = typer.Option(5, "--days", "-d", help="Days available"),
    hours: float = typer.Option(4.0, "--hours", "-h", help="Focused hours per day"),
    domain: Optional[str] = typer.Option(None, "--domain", help="Restrict to domain"),
):
    run_feasibility_triage_session(
        api_base=API_BASE,
        headers=_headers(),
        days=days,
        hours=hours,
        domain=domain,
    )


@app.command("memory")
def view_memory():
    """🧠 View personal profile facts and preferences remembered by Compass."""
    try:
        resp = httpx.get(f"{API_BASE}/api/profile/facts", headers=_headers(), timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        facts = data.get("facts", {})
        if not facts:
            console.print("[compass.dim]No personal profile facts stored yet. Tell Compass your name, goals, or preferences in chat.[/]")
            return

        table = Table(
            title="🧠 What Compass Remembers About You",
            box=box.ROUNDED,
            header_style="bold magenta",
        )
        table.add_column("Category", style="cyan", width=18)
        table.add_column("Detail / Preference", style="green")

        for k, v in sorted(facts.items()):
            table.add_row(k.replace("_", " ").capitalize(), str(v))

        console.print(table)
    except Exception as e:
        console.print(f"[compass.error]❌ Failed to fetch memory facts: {e}[/]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app()

