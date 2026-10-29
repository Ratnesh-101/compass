# -*- coding: utf-8 -*-
"""
Compass CLI — Interactive Agent Runner.

Handles live SSE streaming, terminal panel updates, and interactive user
confirmation / rejection feedback loops for autonomous ReAct agent runs.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx
import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from cli.cli_formatters import STEP_COLORS, console, console_err


def _strip_inline_md(text: str) -> str:
    """Remove inline Markdown bold/italic/code markers from plain text."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'__(.+?)__', r'\1', text)       # __bold__
    text = re.sub(r'`(.+?)`', r'\1', text)         # `code`
    text = re.sub(r'\*(.+?)\*', r'\1', text)       # *italic*
    return text


# Human-readable descriptions for tool names shown during agent execution
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "query_tasks": "Checking your tasks",
    "add_task": "Adding a task",
    "update_task": "Updating a task",
    "delete_task": "Deleting a task",
    "query_memory": "Searching memory",
    "ingest_url": "Ingesting URL into memory",
    "search_web": "Searching the web",
    "query_projects": "Looking up projects",
    "query_schedules": "Checking your schedule",
    "query_deadlines": "Checking upcoming deadlines",
    "get_profile": "Reading your profile",
    "update_profile": "Updating your profile",
}


def _tool_label(tool: str) -> str:
    """Return a human-readable description for a tool name."""
    return _TOOL_DESCRIPTIONS.get(tool, tool.replace("_", " ").capitalize())


def run_interactive_agent_session(
    api_base: str,
    auth_token: Optional[str] = None,
    goal: str = "",
    max_steps: int = 8,
    no_critic: bool = False,
    demo_reject: bool = False,
    conversation_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """Run interactive SSE agent session in terminal with live step panels."""
    req_headers = dict(headers) if headers else {}
    if not req_headers and auth_token:
        req_headers["Authorization"] = f"Bearer {auth_token}"

    critic_label = "off" if no_critic else "on"
    console.print(Panel(
        f"[bold]{goal}[/]\n"
        f"[dim]Max steps: {max_steps}  ·  Self-critique: {critic_label}[/]",
        title="🧠 Compass Agent",
        border_style="blue",
        padding=(1, 2),
    ))

    pending_actions: List[Dict[str, Any]] = []
    run_id: Optional[str] = None

    try:
        with httpx.stream(
            "POST",
            f"{api_base}/api/agent/run",
            json={
                "goal": goal,
                "max_steps": max_steps,
                "enable_critic": not no_critic,
                "confirmed_actions": [],
                "conversation_id": conversation_id,
            },
            headers=req_headers,
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            buffer = ""
            step_counter = 0
            for chunk in response.iter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue

                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    if event.get("run_id"):
                        run_id = event["run_id"]

                    step_type = event.get("type", "think")
                    content = event.get("content", "")
                    step_n = event.get("step", 0)
                    elapsed = event.get("elapsed_ms", 0)
                    tool = event.get("tool", "")
                    args = event.get("args", {})

                    color, label = STEP_COLORS.get(step_type, ("dim", "Step"))

                    if step_type == "tool_call":
                        step_counter += 1
                        human_desc = _tool_label(tool)
                        elapsed_s = f"{elapsed / 1000:.1f}s" if elapsed else ""
                        timing = f"  [dim]{elapsed_s}[/]" if elapsed_s else ""
                        console.print(
                            f"  [bold cyan]Step {step_counter}[/]  [{color}]{human_desc}…[/]{timing}"
                        )

                    elif step_type == "observe":
                        short = content.strip()
                        if len(short) <= 200:
                            # Strip inline Markdown markers for inline display
                            clean = _strip_inline_md(short)
                            # Collapse multiple newlines to single space for inline hint
                            inline = " ".join(clean.split())
                            console.print(f"  [dim]↳ {inline[:160]}[/]")
                        else:
                            console.print(Panel(
                                Markdown(short),
                                title=f"[{color}]{label}[/]",
                                border_style="green",
                                padding=(0, 1),
                            ))

                    elif step_type == "think":
                        # Thinking is internal — suppress to keep output clean
                        pass

                    elif step_type == "confirm_request":
                        console.print(Panel(
                            content,
                            title=f"[{color}]{label}[/]",
                            border_style="red",
                            padding=(0, 1),
                        ))
                        pending_actions.append({"tool": tool, "args": args})

                    elif step_type == "critic":
                        short = content.strip()[:200]
                        console.print(f"  [magenta]⚖  {short}[/]")

                    elif step_type == "synthesize":
                        console.print(Panel(
                            Markdown(content),
                            title=f"[{color}]{label}[/]",
                            border_style="cyan",
                            padding=(1, 2),
                        ))

                    elif step_type == "done":
                        try:
                            done_data = json.loads(content)
                            tools_list = done_data.get("tools_used", [])
                            total = done_data.get("total_steps", 0)
                            pending_count = len(done_data.get("pending_confirmations", []))
                            tools_str = ", ".join(_tool_label(t) for t in tools_list) or "none"
                            summary_lines = [
                                f"  [bold]Steps completed:[/] {total}",
                                f"  [bold]Tools used:[/]     {tools_str}",
                            ]
                            if pending_count > 0:
                                summary_lines.append(
                                    f"\n  [yellow]⚠  {pending_count} action(s) awaiting your approval.[/]"
                                )
                            console.print(Panel(
                                "\n".join(summary_lines),
                                title=f"[{color}]{label}[/]",
                                border_style="green",
                                padding=(1, 2),
                            ))
                        except json.JSONDecodeError:
                            console.print(Panel(
                                content,
                                title=f"[{color}]{label}[/]",
                                border_style="green",
                            ))

                    elif step_type == "error":
                        console.print(f"  [bold red]✗  {content.strip()}[/]")

                    else:
                        border = color.split()[-1] if " " in color else "blue"
                        console.print(Panel(
                            content,
                            title=f"[{color}]{label}[/] [dim]Step {step_n} · {elapsed}ms[/]",
                            border_style=border,
                            padding=(0, 1),
                        ))

    except httpx.HTTPStatusError as e:
        console.print(f"[compass.error]❌ Agent request failed: {e.response.status_code}[/]")
        return
    except httpx.ConnectError:
        console.print(f"[compass.error]❌ Cannot connect to backend at {api_base}[/]")
        return

    # Handle pending confirmations interactively
    if pending_actions:
        console.print()
        console.print(f"[bold red]⚠  {len(pending_actions)} action(s) need your approval:[/]")
        for i, action in enumerate(pending_actions):
            console.print(f"  {i+1}. [yellow]{_tool_label(action['tool'])}[/]  {json.dumps(action['args'])}")

        if demo_reject:
            console.print("[yellow]⚡ Demo: Simulating rejection of deadline conflict…[/]")
            confirm = "no"
            feedback = "Do not move OS Homework 2 deadline"
        else:
            confirm = Prompt.ask("\nApprove these actions?", choices=["yes", "no"], default="no")
            feedback = None

        if confirm == "yes":
            console.print("[green]Executing approved actions…[/]")
            try:
                resp = httpx.post(
                    f"{api_base}/api/agent/confirm",
                    json={"actions": pending_actions, "run_id": run_id if 'run_id' in locals() else None},
                    headers=req_headers,
                    timeout=30.0,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                for r in results:
                    status = r.get("status", "unknown")
                    tool_name = r.get("tool", "")
                    if status == "success":
                        console.print(f"  ✅ {_tool_label(tool_name)}: done")
                    else:
                        console.print(f"  ❌ {_tool_label(tool_name)}: {r.get('message', 'failed')}")
            except Exception as e:
                console.print(f"[compass.error]❌ Failed to execute actions: {e}[/]")
        else:
            if not feedback:
                feedback = Prompt.ask("Reason or alternative instruction (optional)", default="User rejected this action")
            console.print(f"[dim]Actions declined ({feedback}). Feeding back to agent for re-planning…[/]")
            active_rid = run_id if 'run_id' in locals() else None
            if active_rid:
                try:
                    with httpx.stream(
                        "POST",
                        f"{api_base}/api/agent/run",
                        json={
                            "run_id": active_rid,
                            "action": "reject",
                            "feedback": feedback,
                        },
                        headers=req_headers,
                        timeout=120.0,
                    ) as resp:
                        resp.raise_for_status()
                        buf = ""
                        for ch in resp.iter_text():
                            buf += ch
                            while "\n" in buf:
                                line_str, buf = buf.split("\n", 1)
                                line_str = line_str.strip()
                                if not line_str.startswith("data: "):
                                    continue
                                try:
                                    ev = json.loads(line_str[6:])
                                except Exception:
                                    continue
                                stype = ev.get("type", "think")
                                c = ev.get("content", "")
                                col, lbl = STEP_COLORS.get(stype, ("dim", "Step"))
                                if stype == "synthesize":
                                    console.print(Panel(Markdown(c), title=f"[{col}]{lbl}[/]", border_style="cyan"))
                                elif stype not in ("done", "think"):
                                    console.print(Panel(c, title=f"[{col}]{lbl}[/]", border_style="blue", padding=(0, 1)))
                except Exception as ex:
                    console.print(f"[compass.error]❌ Re-planning failed: {ex}[/]")


def run_feasibility_triage_session(
    api_base: str,
    headers: Dict[str, str],
    days: int = 5,
    hours: float = 4.0,
    domain: Optional[str] = None,
) -> None:
    """Run interactive Planner <-> Realist triage stream."""
    console.print(f"[bold cyan]⚖  Starting feasibility negotiation[/] ({days}d × {hours}h/d)")
    try:
        with httpx.stream(
            "POST",
            f"{api_base}/api/agent/feasibility",
            json={"days": days, "hours_per_day": hours, "domain": domain},
            headers=headers,
            timeout=120.0,
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                agent = ev.get("metadata", {}).get("agent", "")
                colour = {"planner": "cyan", "realist": "red"}.get(agent, "white")
                console.print(f"[{colour}]{ev.get('type', '').upper()}[/] {ev.get('content', '')}")
                if ev.get("type") == "done":
                    md = ev.get("metadata", {}).get("artifact_markdown", "")
                    if md:
                        console.print(Markdown(md))
    except Exception as e:
        console_err.print(f"[compass.error]❌ Triage failed: {e}[/]")
        raise typer.Exit(1)
