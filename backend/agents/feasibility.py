"""
The Realist — adversarial feasibility agent for Compass.

Two agents with opposing objectives negotiate over the user's actual workload:

    Planner  (Nemotron-3 Super, 120B) — optimistic; estimates effort, orders work,
                                        wants to fit everything in.
    Realist  (Nemotron-3 Ultra, 550B) — adversarial; independently computes capacity
                                        against demand and rejects infeasible plans
                                        with explicit arithmetic.

They negotiate for at most MAX_ROUNDS. The output is a TriagePlan: keep / defer / drop,
with a defensible arithmetic justification.

Design guarantees (these matter during a live demo):
  * Every model call is individually wrapped; a failure degrades, never crashes.
  * If Nebius is unreachable entirely, a pure-Python deterministic fallback still
    produces a real, arithmetically-correct verdict.
  * The negotiation is hard-capped — no unbounded loops, no runaway credit spend.
  * Nothing in this module mutates the database. Applying a TriagePlan goes through
    the existing confirm-gate (see apply_triage_plan in §4).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from backend.config import get_settings
from backend.memory import structured
from backend.services.usage import record_usage

logger = logging.getLogger("compass.agents.feasibility")

MAX_ROUNDS = 2
MODEL_TIMEOUT_S = 45.0
DEFAULT_HOURS_PER_DAY = 4.0
MAX_TASKS_CONSIDERED = 40

VALID_DOMAINS = {"hackathon", "coursework", "code", "general"}

# Deterministic effort heuristic (hours), used both as a prior for the Planner
# and as the sole source of truth if every model call fails.
_PRIORITY_HOURS = {"urgent": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
_DOMAIN_MULTIPLIER = {"hackathon": 1.25, "code": 1.1, "coursework": 1.0, "general": 0.75}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TaskLoad(BaseModel):
    """One task with an effort estimate attached."""

    task_id: int
    title: str
    domain: str = "general"
    priority: str = "medium"
    due_date: Optional[str] = None
    estimated_hours: float = Field(default=2.0, ge=0.25, le=40.0)
    rationale: str = ""

    @field_validator("domain")
    @classmethod
    def _valid_domain(cls, v: str) -> str:
        return v if v in VALID_DOMAINS else "general"

    @field_validator("estimated_hours", mode="before")
    @classmethod
    def _coerce_hours(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 2.0
        return min(max(f, 0.25), 40.0)


class PlannerProposal(BaseModel):
    """The optimistic plan: everything, in an order."""

    loads: List[TaskLoad] = Field(default_factory=list)
    ordering_rationale: str = ""
    claimed_total_hours: float = 0.0

    def real_total_hours(self) -> float:
        return round(sum(t.estimated_hours for t in self.loads), 2)


class FeasibilityVerdict(BaseModel):
    """The Realist's ruling."""

    verdict: Literal["FEASIBLE", "AT_RISK", "INFEASIBLE"] = "AT_RISK"
    demand_hours: float = 0.0
    capacity_hours: float = 0.0
    overcommit_hours: float = 0.0
    utilisation_pct: float = 0.0
    must_cut_hours: float = 0.0
    reasoning: str = ""
    challenged_estimates: List[str] = Field(default_factory=list)

    @property
    def accepts(self) -> bool:
        return self.verdict == "FEASIBLE"


class TriagePlan(BaseModel):
    """The tangible artifact the user takes away."""

    keep: List[TaskLoad] = Field(default_factory=list)
    defer: List[TaskLoad] = Field(default_factory=list)
    drop: List[TaskLoad] = Field(default_factory=list)
    verdict: FeasibilityVerdict
    rounds_used: int = 0
    narrative: str = ""
    degraded: bool = False  # True when produced by the offline fallback

    def kept_hours(self) -> float:
        return round(sum(t.estimated_hours for t in self.keep), 2)

    def as_markdown(self) -> str:
        """Copy-pasteable artifact — this is what the user keeps."""
        v = self.verdict
        lines = [
            "# Compass — Feasibility Triage",
            "",
            f"**Verdict:** {v.verdict}",
            f"**Demand:** {v.demand_hours}h  |  **Capacity:** {v.capacity_hours}h  "
            f"|  **Utilisation:** {v.utilisation_pct}%",
        ]
        if v.overcommit_hours > 0:
            lines.append(f"**Overcommitted by:** {v.overcommit_hours}h")
        lines += ["", f"_{self.narrative}_", ""]

        for label, bucket in (("Keep", self.keep), ("Defer", self.defer), ("Drop", self.drop)):
            lines.append(f"## {label} ({len(bucket)})")
            if not bucket:
                lines.append("_none_")
            for t in bucket:
                due = f" — due {t.due_date}" if t.due_date else ""
                why = f" — {t.rationale}" if t.rationale else ""
                lines.append(f"- **{t.title}** [{t.domain}] · {t.estimated_hours}h{due}{why}")
            lines.append("")

        if v.challenged_estimates:
            lines.append("## Estimates the Realist challenged")
            lines += [f"- {c}" for c in v.challenged_estimates]
            lines.append("")

        lines.append(f"_Negotiation rounds: {self.rounds_used}_")
        if self.degraded:
            lines.append("_Produced by the offline deterministic fallback "
                         "(model provider unreachable)._")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """You are the PLANNER inside Compass, a personal AI assistant.

Your objective: get the user's work done. You are constructive and want to fit as \
much in as possible.

You will be given a list of the user's open tasks. For EACH task, estimate the \
realistic number of focused working hours it requires and give a one-line rationale. \
Then order the tasks by what should be attempted first, considering deadlines first \
and priority second.

Be honest about effort. Underestimating gets caught by the Realist and wastes a round.

Respond with ONLY a JSON object, no prose, no markdown fences:
{
  "loads": [
    {"task_id": 1, "title": "...", "domain": "hackathon", "priority": "high",
     "due_date": "2026-10-30", "estimated_hours": 3.5, "rationale": "..."}
  ],
  "ordering_rationale": "one or two sentences",
  "claimed_total_hours": 12.5
}"""

PLANNER_REPLAN_SYSTEM = """You are the PLANNER inside Compass. Your previous plan was \
REJECTED by the Realist as infeasible.

You must now produce a plan that fits within the stated capacity. You may lower an \
estimate ONLY if you can justify it. Otherwise, move work out: put items in "defer" \
(still matters, later) or "drop" (should not be attempted this period).

Deadlines are hard constraints. Never defer or drop something whose deadline falls \
inside this period unless nothing else can give — and if you must, say so explicitly.

Respond with ONLY a JSON object, no prose, no markdown fences:
{
  "keep":  [{"task_id": 1, "title": "...", "domain": "...", "priority": "...",
             "due_date": null, "estimated_hours": 2.0, "rationale": "why this survives"}],
  "defer": [{"task_id": 2, "title": "...", "domain": "...", "priority": "...",
             "due_date": null, "estimated_hours": 3.0, "rationale": "why this waits"}],
  "drop":  [{"task_id": 3, "title": "...", "domain": "...", "priority": "...",
             "due_date": null, "estimated_hours": 1.0, "rationale": "why this goes"}],
  "narrative": "two sentences explaining the trade-off you made"
}"""

REALIST_SYSTEM = """You are the REALIST inside Compass. You are ADVERSARIAL by design.

Your objective is NOT to be agreeable. It is to determine whether the Planner's \
proposal is arithmetically achievable in the time available, and to reject it if it \
is not. Optimistic plans that fail cost the user more than honest plans that are \
smaller.

Rules you must follow:
1. Do the arithmetic. demand = sum of estimated hours. capacity is given to you. \
Compare them. Do not hand-wave.
2. Apply a realism discount: humans do not achieve 100% of nominal capacity. Treat \
effective capacity as 80% of nominal unless told otherwise.
3. Challenge any estimate that looks implausibly low for the work described. List \
each one you challenge.
4. Verdict rules:
   - FEASIBLE   if demand <= effective capacity
   - AT_RISK    if demand <= effective capacity * 1.15
   - INFEASIBLE if demand >  effective capacity * 1.15
5. If INFEASIBLE, state exactly how many hours must be cut.

Respond with ONLY a JSON object, no prose, no markdown fences:
{
  "verdict": "FEASIBLE" | "AT_RISK" | "INFEASIBLE",
  "demand_hours": 0.0,
  "capacity_hours": 0.0,
  "overcommit_hours": 0.0,
  "utilisation_pct": 0.0,
  "must_cut_hours": 0.0,
  "reasoning": "two or three sentences showing the arithmetic",
  "challenged_estimates": ["'task title' at 1h is optimistic because ..."]
}"""


# ---------------------------------------------------------------------------
# Model plumbing
# ---------------------------------------------------------------------------

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    settings = get_settings()
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.NEBIUS_API_KEY,
            base_url=settings.NEBIUS_BASE_URL,
            timeout=MODEL_TIMEOUT_S,
        )
    return _client


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _safe_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse model output into a dict, tolerating fences and surrounding prose."""
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw.strip())
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


async def _call_model(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 1400,
) -> Optional[Dict[str, Any]]:
    """One guarded model call. Returns parsed JSON, or None on any failure."""
    settings = get_settings()
    if not settings.NEBIUS_API_KEY:
        logger.warning("NEBIUS_API_KEY unset — skipping model call to %s", model)
        return None
    try:
        client = _get_client()
        completions: Any = client.chat.completions
        resp = await asyncio.wait_for(
            completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.2,
            ),
            timeout=MODEL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning("Model %s timed out after %ss", model, MODEL_TIMEOUT_S)
        return None
    except Exception as e:
        logger.warning("Model %s call failed: %s", model, e)
        return None

    try:
        usage = getattr(resp, "usage", None)
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        record_usage(model, p_tok, c_tok)
    except Exception as e:  # accounting must never break the run
        logger.debug("record_usage failed for %s: %s", model, e)

    try:
        content = resp.choices[0].message.content
    except (AttributeError, IndexError):
        content = None
    return _safe_json(content)


# ---------------------------------------------------------------------------
# Deterministic fallbacks — these are why the demo cannot crash
# ---------------------------------------------------------------------------

def _heuristic_hours(task: Dict[str, Any]) -> float:
    base = _PRIORITY_HOURS.get(str(task.get("priority") or "medium").lower(), 2.0)
    mult = _DOMAIN_MULTIPLIER.get(str(task.get("domain") or "general").lower(), 1.0)
    title_len = len(str(task.get("title") or ""))
    size_bump = 1.0 if title_len < 60 else 1.3
    return round(base * mult * size_bump, 2)


def _heuristic_proposal(tasks: List[Dict[str, Any]]) -> PlannerProposal:
    loads: List[TaskLoad] = []
    for t in tasks:
        loads.append(
            TaskLoad(
                task_id=int(t.get("id", 0) or 0),
                title=str(t.get("title") or "untitled"),
                domain=str(t.get("domain") or "general"),
                priority=str(t.get("priority") or "medium"),
                due_date=_iso(t.get("due_date")),
                estimated_hours=_heuristic_hours(t),
                rationale="heuristic estimate (priority × domain weighting)",
            )
        )
    loads.sort(key=lambda x: (x.due_date or "9999-12-31",
                              -_PRIORITY_HOURS.get(x.priority, 2.0)))
    return PlannerProposal(
        loads=loads,
        ordering_rationale="Ordered by deadline, then priority.",
        claimed_total_hours=round(sum(load.estimated_hours for load in loads), 2),
    )


def _arithmetic_verdict(demand: float, capacity: float) -> FeasibilityVerdict:
    effective = round(capacity * 0.8, 2)
    over = round(max(0.0, demand - effective), 2)
    util = round((demand / effective * 100.0), 1) if effective > 0 else 999.9
    verdict: Literal["FEASIBLE", "AT_RISK", "INFEASIBLE"]
    if demand <= effective:
        verdict = "FEASIBLE"
    elif demand <= effective * 1.15:
        verdict = "AT_RISK"
    else:
        verdict = "INFEASIBLE"
    return FeasibilityVerdict(
        verdict=verdict,
        demand_hours=round(demand, 2),
        capacity_hours=round(capacity, 2),
        overcommit_hours=over,
        utilisation_pct=util,
        must_cut_hours=over if verdict == "INFEASIBLE" else 0.0,
        reasoning=(
            f"{demand}h of work against {capacity}h nominal capacity "
            f"({effective}h effective at 80%). Utilisation {util}%."
        ),
        challenged_estimates=[],
    )


def _greedy_triage(proposal: PlannerProposal,
                   verdict: FeasibilityVerdict) -> TriagePlan:
    """Deterministic cut: keep by deadline then priority until capacity is full."""
    effective = round(verdict.capacity_hours * 0.8, 2)
    ordered = sorted(
        proposal.loads,
        key=lambda x: (x.due_date or "9999-12-31", -_PRIORITY_HOURS.get(x.priority, 2.0)),
    )
    keep: List[TaskLoad] = []
    defer: List[TaskLoad] = []
    drop: List[TaskLoad] = []
    running = 0.0
    for t in ordered:
        if running + t.estimated_hours <= effective:
            keep.append(t)
            running += t.estimated_hours
        elif t.priority in ("urgent", "high") or t.due_date:
            t.rationale = "over capacity — deferred, but still time-sensitive"
            defer.append(t)
        else:
            t.rationale = "over capacity and not time-sensitive"
            drop.append(t)
    return TriagePlan(
        keep=keep, defer=defer, drop=drop, verdict=verdict, rounds_used=0,
        narrative=(
            f"Fitted {round(running, 2)}h into {effective}h of effective capacity. "
            f"{len(defer)} deferred, {len(drop)} dropped."
        ),
        degraded=True,
    )


def _iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    return s[:10] if s else None


# ---------------------------------------------------------------------------
# The negotiation
# ---------------------------------------------------------------------------

def _sse(step_type: str, content: str, *, step: int, t0: float,
         **metadata: Any) -> Dict[str, Any]:
    """Emit in the same SSE envelope the existing agent loop uses."""
    return {
        "type": step_type,
        "content": content,
        "step": step,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        "metadata": metadata or {},
    }


async def _fetch_open_tasks(pool, domain: Optional[str]) -> List[Dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await structured.list_tasks(conn, domain=domain, status="open")
    return [dict(r) for r in rows][:MAX_TASKS_CONSIDERED]


def _describe(tasks: List[Dict[str, Any]]) -> str:
    out = []
    for t in tasks:
        out.append(
            f"- id={t.get('id')} | {t.get('title')} | domain={t.get('domain')} "
            f"| priority={t.get('priority')} | due={_iso(t.get('due_date')) or 'none'}"
        )
    return "\n".join(out) if out else "(no open tasks)"


async def run_feasibility_review(
    pool,
    *,
    days: int = 5,
    hours_per_day: float = DEFAULT_HOURS_PER_DAY,
    domain: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream the Planner ↔ Realist negotiation as SSE-shaped dicts.

    The terminal event is always type="done" carrying the TriagePlan, even when
    every model call failed — in that case the plan is produced arithmetically
    and flagged degraded=True.
    """
    t0 = time.perf_counter()
    step = 0
    settings = get_settings()
    capacity = round(max(0.5, float(days) * float(hours_per_day)), 2)

    # --- Gather -----------------------------------------------------------
    step += 1
    yield _sse("think", f"Pulling open tasks and computing capacity: "
                        f"{days} days × {hours_per_day}h = {capacity}h nominal.",
               step=step, t0=t0, model_tier="Compass System")

    try:
        tasks = await _fetch_open_tasks(pool, domain)
    except Exception as e:
        logger.error("Could not load tasks for feasibility review: %s", e, exc_info=True)
        step += 1
        yield _sse("error", "I couldn't read your task list, so I can't assess "
                            "feasibility. Nothing was changed.",
                   step=step, t0=t0, recoverable=False)
        return

    if not tasks:
        step += 1
        empty = TriagePlan(
            keep=[], defer=[], drop=[],
            verdict=_arithmetic_verdict(0.0, capacity),
            rounds_used=0,
            narrative="No open tasks — nothing to triage.",
        )
        yield _sse("done", "No open tasks to assess.", step=step, t0=t0,
                   triage_plan=empty.model_dump(), artifact_markdown=empty.as_markdown())
        return

    step += 1
    yield _sse("observe", f"{len(tasks)} open task(s) in scope.",
               step=step, t0=t0, task_count=len(tasks),
               model_tier="Neon Postgres Engine")

    # --- Round 1: Planner proposes ---------------------------------------
    step += 1
    yield _sse("think", "PLANNER (Nemotron-3 Super) is estimating effort per task.",
               step=step, t0=t0, agent="planner", model_tier="Nemotron-3 Super (120B)")

    planner_raw = await _call_model(
        settings.SKILL_MODEL,
        PLANNER_SYSTEM,
        f"Open tasks:\n{_describe(tasks)}\n\n"
        f"Available capacity: {days} days at {hours_per_day}h/day = {capacity}h nominal.",
    )

    degraded = False
    if planner_raw:
        try:
            proposal = PlannerProposal.model_validate(planner_raw)
            if not proposal.loads:
                raise ValueError("planner returned zero loads")
        except Exception as e:
            logger.warning("Planner output invalid (%s) — using heuristic", e)
            proposal = _heuristic_proposal(tasks)
            degraded = True
    else:
        proposal = _heuristic_proposal(tasks)
        degraded = True

    demand = proposal.real_total_hours()
    step += 1
    yield _sse("propose",
               f"PLANNER: {len(proposal.loads)} task(s), {demand}h of work. "
               f"{proposal.ordering_rationale}",
               step=step, t0=t0, agent="planner", demand_hours=demand,
               degraded=degraded, model_tier="Nemotron-3 Super (120B)")

    # --- Round 1: Realist adjudicates ------------------------------------
    step += 1
    yield _sse("think", "REALIST (Nemotron-3 Ultra) is independently checking the math.",
               step=step, t0=t0, agent="realist", model_tier="Nemotron-3 Ultra (550B)")

    realist_raw = await _call_model(
        settings.SYNTHESIS_MODEL,
        REALIST_SYSTEM,
        "Planner proposal:\n"
        + "\n".join(f"- {load.title} [{load.domain}/{load.priority}] "
                    f"est {load.estimated_hours}h — {load.rationale}" for load in proposal.loads)
        + f"\n\nTotal claimed: {demand}h\nNominal capacity: {capacity}h",
        max_tokens=900,
    )

    verdict = _arithmetic_verdict(demand, capacity)
    if realist_raw:
        try:
            model_verdict = FeasibilityVerdict.model_validate(realist_raw)
            # Trust the model's reasoning and challenges, but never its arithmetic.
            verdict.reasoning = model_verdict.reasoning or verdict.reasoning
            verdict.challenged_estimates = model_verdict.challenged_estimates[:6]
        except Exception as e:
            logger.warning("Realist output invalid (%s) — arithmetic verdict stands", e)
    else:
        degraded = True

    step += 1
    yield _sse("verdict",
               f"REALIST: {verdict.verdict} — {verdict.demand_hours}h demanded vs "
               f"{verdict.capacity_hours}h capacity ({verdict.utilisation_pct}% "
               f"utilisation). {verdict.reasoning}",
               step=step, t0=t0, agent="realist",
               verdict=verdict.model_dump(), model_tier="Nemotron-3 Ultra (550B)")

    if verdict.accepts:
        round1_plan = TriagePlan(
            keep=proposal.loads, defer=[], drop=[], verdict=verdict, rounds_used=1,
            narrative="The plan fits within effective capacity. No cuts required.",
            degraded=degraded,
        )
        step += 1
        yield _sse("done", "Plan accepted on the first round.", step=step, t0=t0,
                   triage_plan=round1_plan.model_dump(),
                   artifact_markdown=round1_plan.as_markdown(),
                   rounds_used=1, agents_involved=["planner", "realist"])
        return

    # --- Round 2: Planner re-plans under the constraint -------------------
    step += 1
    yield _sse("replan",
               f"PLANNER is re-planning. Must shed {verdict.must_cut_hours or verdict.overcommit_hours}h.",
               step=step, t0=t0, agent="planner",
               must_cut_hours=verdict.must_cut_hours or verdict.overcommit_hours,
               model_tier="Nemotron-3 Super (120B)")

    replan_raw = await _call_model(
        settings.SKILL_MODEL,
        PLANNER_REPLAN_SYSTEM,
        "Your plan was rejected.\n"
        f"Verdict: {verdict.verdict}\nReasoning: {verdict.reasoning}\n"
        f"You must cut at least {verdict.must_cut_hours or verdict.overcommit_hours}h.\n\n"
        "Original plan:\n"
        + "\n".join(f"- id={load.task_id} {load.title} [{load.domain}/{load.priority}] "
                    f"est {load.estimated_hours}h due {load.due_date or 'none'}"
                    for load in proposal.loads),
    )

    revised_plan: Optional[TriagePlan] = None
    if replan_raw:
        try:
            revised_plan = TriagePlan(
                keep=[TaskLoad.model_validate(x) for x in replan_raw.get("keep", [])],
                defer=[TaskLoad.model_validate(x) for x in replan_raw.get("defer", [])],
                drop=[TaskLoad.model_validate(x) for x in replan_raw.get("drop", [])],
                verdict=verdict,
                rounds_used=2,
                narrative=str(replan_raw.get("narrative") or ""),
                degraded=degraded,
            )
            if not revised_plan.keep and not revised_plan.defer and not revised_plan.drop:
                revised_plan = None
        except Exception as e:
            logger.warning("Re-plan output invalid (%s) — falling back to greedy", e)
            revised_plan = None

    if revised_plan is None:
        revised_plan = _greedy_triage(proposal, verdict)
        revised_plan.rounds_used = 2
        degraded = True
        revised_plan.degraded = True

    # Final arithmetic check on the revised plan — the Realist's own rule.
    final_verdict = _arithmetic_verdict(revised_plan.kept_hours(), capacity)
    final_verdict.challenged_estimates = verdict.challenged_estimates
    revised_plan.verdict = final_verdict

    step += 1
    yield _sse("verdict",
               f"REALIST re-check: revised plan is {final_verdict.verdict} at "
               f"{revised_plan.kept_hours()}h kept against {capacity}h capacity.",
               step=step, t0=t0, agent="realist",
               verdict=final_verdict.model_dump(),
               model_tier="Nemotron-3 Ultra (550B)")

    step += 1
    yield _sse("done",
               f"Negotiated in {revised_plan.rounds_used} round(s): "
               f"{len(revised_plan.keep)} kept, {len(revised_plan.defer)} deferred, {len(revised_plan.drop)} dropped.",
               step=step, t0=t0,
               triage_plan=revised_plan.model_dump(),
               artifact_markdown=revised_plan.as_markdown(),
               rounds_used=revised_plan.rounds_used,
               agents_involved=["planner", "realist"],
               degraded=revised_plan.degraded)


async def assess_feasibility(
    pool,
    *,
    days: int = 5,
    hours_per_day: float = DEFAULT_HOURS_PER_DAY,
    domain: Optional[str] = None,
) -> TriagePlan:
    """Non-streaming wrapper. Always returns a TriagePlan or raises RuntimeError."""
    final: Optional[Dict[str, Any]] = None
    async for ev in run_feasibility_review(
        pool, days=days, hours_per_day=hours_per_day, domain=domain
    ):
        if ev["type"] == "done":
            final = ev
        elif ev["type"] == "error":
            raise RuntimeError(ev["content"])
    if not final:
        raise RuntimeError("Feasibility review produced no verdict")
    return TriagePlan.model_validate(final["metadata"]["triage_plan"])
