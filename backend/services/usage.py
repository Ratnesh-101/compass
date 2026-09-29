"""
Compass — Token & Cost Accounting Store.

Tracks token consumption and computes estimated cost for Nebius & NVIDIA models.
Records usage into both an in-memory accumulator and PostgreSQL usage_log table.
"""

import logging
from typing import Optional, Dict, Any
import asyncpg

logger = logging.getLogger("compass.services.usage")

# Pricing Constants per 1,000,000 tokens (USD)
# Verified Nebius Token Factory catalog rates:
# - Nemotron-3 Nano: $0.06 / 1M prompt, $0.24 / 1M completion
# - Nemotron-3 Super: $0.30 / 1M prompt, $0.90 / 1M completion
# Note: Nemotron-3 Ultra and Qwen3-Embedding rates are estimated, not independently verified from the dashboard directly.
PRICING_PER_1M = {
    # Normalized model keys
    "nemotron-nano": {"prompt": 0.06, "completion": 0.24},
    "nemotron-super": {"prompt": 0.30, "completion": 0.90},
    "nemotron-ultra": {"prompt": 0.80, "completion": 2.40},
    "qwen3-embedding": {"prompt": 0.02, "completion": 0.00},
    
    # Full Model ID mappings for OpenAI SDK compatibility
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {"prompt": 0.06, "completion": 0.24},
    "nvidia/nemotron-3-super-120b-a12b": {"prompt": 0.30, "completion": 0.90},
    "nvidia/Nemotron-3-Ultra-550b-a55b": {"prompt": 0.80, "completion": 2.40},
    "Qwen/Qwen3-Embedding-8B": {"prompt": 0.02, "completion": 0.00},
}

def _normalize_model_name(name: str) -> str:
    """Normalize model string to standard keys."""
    n = name.lower()
    if "nano" in n:
        return "nemotron-nano"
    if "super" in n:
        return "nemotron-super"
    if "ultra" in n:
        return "nemotron-ultra"
    if "embedding" in n or "qwen" in n:
        return "qwen3-embedding"
    return name


def compute_step_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute estimated USD cost for a single model call based on token counts."""
    norm_key = _normalize_model_name(model_name)
    pricing = PRICING_PER_1M.get(norm_key, {"prompt": 0.30, "completion": 0.90})
    cost = (prompt_tokens * pricing["prompt"] / 1_000_000.0) + (completion_tokens * pricing["completion"] / 1_000_000.0)
    return round(cost, 6)


# In-Memory State Store — starts empty (zeroed); hydrated from usage_log on startup
_USAGE_STATE: Dict[str, Dict[str, Any]] = {}


async def hydrate_usage_from_db(pool=None) -> Dict[str, Any]:
    """Hydrate in-memory _USAGE_STATE from the persistent usage_log table in Neon PostgreSQL.

    Ensures usage dashboards and admin commands reflect genuine historical database telemetry.
    """
    global _USAGE_STATE
    if pool is None:
        try:
            from backend.memory.db import get_pool
            pool = await get_pool()
        except Exception:
            return _USAGE_STATE
    if not pool:
        return _USAGE_STATE

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT model,
                       COUNT(*) as calls,
                       COALESCE(SUM(input_tokens), 0) as prompt_tokens,
                       COALESCE(SUM(output_tokens), 0) as completion_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0.0) as cost
                FROM usage_log
                GROUP BY model
                """
            )
            new_state: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                norm_key = _normalize_model_name(r["model"])
                if norm_key not in new_state:
                    new_state[norm_key] = {
                        "calls": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cost": 0.0,
                    }
                entry = new_state[norm_key]
                entry["calls"] += int(r["calls"])
                entry["prompt_tokens"] += int(r["prompt_tokens"])
                entry["completion_tokens"] += int(r["completion_tokens"])
                entry["cost"] = round(entry["cost"] + float(r["cost"]), 6)
                new_state[r["model"]] = entry

            _USAGE_STATE = new_state
            logger.info(f"Hydrated usage state from usage_log: {len(rows)} model groups loaded.")

            # Hydrate Tavily credit telemetry
            try:
                tavily_rows = await conn.fetch(
                    "SELECT operation, COUNT(*) as calls, COALESCE(SUM(credits), 0) as credits FROM tavily_usage_log GROUP BY operation"
                )
                for tr in tavily_rows:
                    op = tr["operation"]
                    _TAVILY_STATE[op] = {"calls": int(tr["calls"]), "credits": int(tr["credits"])}
                logger.info(f"Hydrated Tavily credits: {get_tavily_summary()['total_credits']} total credits.")
            except Exception as te:
                logger.debug(f"Could not hydrate tavily_usage_log (table might be initializing): {te}")
    except Exception as e:
        logger.warning(f"Failed to hydrate usage from DB: {e}")

    return _USAGE_STATE


# Tavily credit state store — starts at 0, tracked separately from token costs
_TAVILY_STATE: Dict[str, Dict[str, int]] = {
    "search": {"calls": 0, "credits": 0},
    "extract": {"calls": 0, "credits": 0},
}


def get_tavily_summary() -> Dict[str, Any]:
    """Return consolidated Tavily credit accounting summary."""
    total_credits = sum(v.get("credits", 0) for v in _TAVILY_STATE.values())
    total_calls = sum(v.get("calls", 0) for v in _TAVILY_STATE.values())
    return {
        "by_operation": {k: dict(v) for k, v in _TAVILY_STATE.items()},
        "total_credits": total_credits,
        "total_calls": total_calls,
    }


async def _persist_tavily_to_db(
    operation: str,
    credits: int,
    conn: Optional[asyncpg.Connection] = None,
) -> None:
    """Insert a record into tavily_usage_log table."""
    try:
        if conn is not None:
            await conn.execute(
                "INSERT INTO tavily_usage_log (operation, credits) VALUES ($1, $2)",
                operation, credits,
            )
        else:
            from backend.memory.db import get_pool
            pool = await get_pool()
            async with pool.acquire() as db_conn:
                await db_conn.execute(
                    "INSERT INTO tavily_usage_log (operation, credits) VALUES ($1, $2)",
                    operation, credits,
                )
    except Exception as err:
        logger.warning(f"Failed to persist tavily_usage_log: {err}")


async def record_tavily_credits(
    operation: str,
    credits: int,
    conn: Optional[asyncpg.Connection] = None,
) -> None:
    """Record Tavily credit usage and persist asynchronously with strong reference."""
    import asyncio
    st = _TAVILY_STATE.setdefault(operation, {"calls": 0, "credits": 0})
    st["calls"] += 1
    st["credits"] += credits

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_persist_tavily_to_db(operation, credits, conn=conn))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_on_persist_done)
    except RuntimeError:
        pass

    logger.info(f"Tavily credit recorded: operation={operation}, credits={credits}")



# Background task set to prevent premature garbage collection of in-flight writes
_BACKGROUND_TASKS: set = set()


def _on_persist_done(task: Any) -> None:
    """Callback to clean up background task reference and log any unhandled exceptions."""
    _BACKGROUND_TASKS.discard(task)
    if not task.cancelled():
        exc = task.exception()
        if exc:
            logger.error(f"Background usage_log persistence failed: {exc}", exc_info=exc)


async def _persist_to_db(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost: float,
    skill: Optional[str] = None,
    conn: Optional[asyncpg.Connection] = None,
) -> None:
    """Insert a usage record into the usage_log table."""
    try:
        if conn is not None:
            await conn.execute(
                """
                INSERT INTO usage_log (model, input_tokens, output_tokens, estimated_cost_usd, skill)
                VALUES ($1, $2, $3, $4, $5)
                """,
                model_name, prompt_tokens, completion_tokens, cost, skill,
            )
        else:
            from backend.memory.db import get_pool
            pool = await get_pool()
            async with pool.acquire() as db_conn:
                await db_conn.execute(
                    """
                    INSERT INTO usage_log (model, input_tokens, output_tokens, estimated_cost_usd, skill)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    model_name, prompt_tokens, completion_tokens, cost, skill,
                )
        logger.debug(f"usage_log row persisted: {model_name} ({prompt_tokens} in / {completion_tokens} out)")
    except Exception as db_err:
        logger.warning(f"Failed to persist usage_log: {db_err}")


def record_usage(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    conn: Optional[asyncpg.Connection] = None,
    skill: Optional[str] = None,
) -> float:
    """Record token consumption and compute cost.

    Updates in-memory accumulators synchronously.
    Schedules an async INSERT into usage_log table using a managed background task.

    Args:
        model_name: Name or alias of the model used
        prompt_tokens: Number of prompt/input tokens
        completion_tokens: Number of completion/output tokens
        conn: Optional active asyncpg connection to persist into database
        skill: Optional skill or pipeline stage identifier
    """
    import asyncio

    norm_key = _normalize_model_name(model_name)
    pricing = PRICING_PER_1M.get(norm_key, {"prompt": 0.06, "completion": 0.24})

    cost = (prompt_tokens * pricing["prompt"] / 1_000_000.0) + (
        completion_tokens * pricing["completion"] / 1_000_000.0
    )
    cost = round(cost, 6)

    # Update canonical model entry in memory
    canonical_key = norm_key
    if canonical_key not in _USAGE_STATE:
        _USAGE_STATE[canonical_key] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
    entry = _USAGE_STATE[canonical_key]
    entry["calls"] += 1
    entry["prompt_tokens"] += prompt_tokens
    entry["completion_tokens"] += completion_tokens
    entry["cost"] = round(entry["cost"] + cost, 6)
    _USAGE_STATE[model_name] = entry

    # Schedule DB persistence with a strong reference and completion callback
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            _persist_to_db(model_name, prompt_tokens, completion_tokens, cost, skill, conn=conn)
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_on_persist_done)
    except RuntimeError:
        # No running event loop (e.g. running in synchronous CLI or worker)
        pass

    logger.info(
        f"Usage recorded: {model_name} | {prompt_tokens} in / {completion_tokens} out | ${cost:.6f}"
    )
    return cost


async def flush_usage_tasks() -> None:
    """Wait for all pending usage persistence background tasks to complete."""
    import asyncio
    if _BACKGROUND_TASKS:
        tasks = list(_BACKGROUND_TASKS)
        await asyncio.gather(*tasks, return_exceptions=True)


def get_usage_summary() -> Dict[str, Any]:
    """Return consolidated usage summary and detailed model breakdown table.

    Formatted to match CLI admin usage expectations and dashboard metrics.
    """
    total_calls = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_usd = 0.0

    # Build breakdown dictionary
    by_model: Dict[str, Dict[str, Any]] = {}

    # Report standard model identifiers
    report_keys = [
        ("nemotron-nano", "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
        ("nemotron-super", "nvidia/nemotron-3-super-120b-a12b"),
        ("nemotron-ultra", "nvidia/Nemotron-3-Ultra-550b-a55b"),
        ("qwen3-embedding", "Qwen/Qwen3-Embedding-8B"),
    ]

    for short_key, full_key in report_keys:
        state = _USAGE_STATE.get(short_key) or _USAGE_STATE.get(full_key, {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0
        })

        calls = state.get("calls", 0)
        p_tokens = state.get("prompt_tokens", 0)
        c_tokens = state.get("completion_tokens", 0)
        c_cost = float(state.get("cost", 0.0))

        total_calls += calls
        total_prompt_tokens += p_tokens
        total_completion_tokens += c_tokens
        total_cost_usd += c_cost

        by_model[full_key] = {
            "calls": calls,
            "input_tokens": p_tokens,
            "output_tokens": c_tokens,
            "estimated_cost_usd": round(c_cost, 6),
        }

    return {
        "total_requests": total_calls,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "total_input_tokens": total_prompt_tokens,
        "total_output_tokens": total_completion_tokens,
        "total_estimated_cost_usd": round(total_cost_usd, 6),
        "total_cost": f"${total_cost_usd:.4f}",
        "by_model": by_model,
        "breakdown": [
            {
                "model": k,
                "calls": v["calls"],
                "tokens": v["input_tokens"] + v["output_tokens"],
                "cost": f"${v['estimated_cost_usd']:.6f}"
            }
            for k, v in by_model.items()
        ],
        "tavily": get_tavily_summary(),
    }
