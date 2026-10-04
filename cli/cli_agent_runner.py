# -*- coding: utf-8 -*-
"""
Compass CLI — Interactive Agent Runner.

Handles live SSE streaming, terminal panel updates, and interactive user
confirmation / rejection feedback loops for autonomous ReAct agent runs.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from cli.cli_formatters import STEP_COLORS, console


def run_interactive_agent_session(
    api_base: str,
    auth_token: str,
    goal: str,
    max_steps: int = 8,
    no_critic: bool = False,
    demo_reject: bool = False,
    conversation_id: Optional[str] = None,
) -> None:
    """Run interactive SSE agent session in terminal with live step panels."""
    console.print(Panel(
        f"[bold]Goal:[/] {goal}\n"
        f"[dim]Max steps: {max_steps} | Critic: {'disabled' if no_critic else 'enabled'}[/]",
        title="🧠 Compass Agent",
        border_style="blue",
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
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            buffer = ""
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

                    color, label = STEP_COLORS.get(step_type, ("dim", "STEP"))

                    if step_type == "tool_call":
                        args_str = json.dumps(args) if args else ""
                        console.print(Panel(
                            f"[yellow]{tool}[/]({args_str})",
                            title=f"[{color}]{label}[/] [dim]Step {step_n} · {elapsed}ms[/]",
                            border_style="yellow",
                            padding=(0, 1),
                        ))
                    elif step_type == "confirm_request":
                        console.print(Panel(
                            content,
                            title=f"[{color}]{label}[/]",
                            border_style="red",
                            padding=(0, 1),
                        ))
                        pending_actions.append({"tool": tool, "args": args})
                    elif step_type == "done":
                        try:
                            done_data = json.loads(content)
                            tools_list = ", ".join(done_data.get("tools_used", [])) or "none"
                            total = done_data.get("total_steps", 0)
                            pending_count = len(done_data.get("pending_confirmations", []))
                            done_text = f"Completed in {total} steps. Tools: {tools_list}."
                            if pending_count > 0:
                                done_text += f"\n⚠️ {pending_count} action(s) pending your approval."
                            console.print(Panel(done_text, title=f"[{color}]{label}[/]", border_style="green"))
                        except json.JSONDecodeError:
                            console.print(Panel(content, title=f"[{color}]{label}[/]", border_style="green"))
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
        console.print(f"[bold red]⚠️ {len(pending_actions)} action(s) need your approval:[/]")
        for i, action in enumerate(pending_actions):
            console.print(f"  {i+1}. [yellow]{action['tool']}[/]({json.dumps(action['args'])})")

        if demo_reject:
            console.print("[yellow]⚡ Demo Trigger: Simulating user decline for deadline conflict...[/]")
            confirm = "no"
            feedback = "Do not move OS Homework 2 deadline"
        else:
            confirm = Prompt.ask("\nApprove these actions?", choices=["yes", "no"], default="no")
            feedback = None

        if confirm == "yes":
            console.print("[green]Executing approved actions...[/]")
            try:
                resp = httpx.post(
                    f"{api_base}/api/agent/confirm",
                    json={"actions": pending_actions, "run_id": run_id if 'run_id' in locals() else None},
                    headers={"Authorization": f"Bearer {auth_token}"},
                    timeout=30.0,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                for r in results:
                    status = r.get("status", "unknown")
                    tool_name = r.get("tool", "")
                    if status == "success":
                        console.print(f"  ✅ {tool_name}: success")
                    else:
                        console.print(f"  ❌ {tool_name}: {r.get('message', 'failed')}")
            except Exception as e:
                console.print(f"[compass.error]❌ Failed to execute actions: {e}[/]")
        else:
            if not feedback:
                feedback = Prompt.ask("Reason / alternative plan instruction (optional)", default="User rejected this action")
            console.print(f"[dim]Actions rejected ({feedback}). Feeding rejection back to agent for re-planning...[/]")
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
                                col, lbl = STEP_COLORS.get(stype, ("dim", "STEP"))
                                if stype == "synthesize":
                                    console.print(Panel(c, title=f"[{col}]{lbl}[/]", border_style="cyan"))
                                elif stype != "done":
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
    console.print(f"[bold cyan]⚖️  Starting feasibility negotiation[/] ({days}d × {hours}h/d)")
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
        console.print(f"[compass.error]❌ Triage failed: {e}[/]")
