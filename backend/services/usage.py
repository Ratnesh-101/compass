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
PRICING_PER_1M = {
    # Normalized model keys
    "nemotron-nano": {"prompt": 0.08, "completion": 0.08},
    "nemotron-super": {"prompt": 0.40, "completion": 0.40},
    "nemotron-ultra": {"prompt": 0.80, "completion": 0.80},
    "qwen3-embedding": {"prompt": 0.02, "completion": 0.00},
    
    # Full Model ID mappings for OpenAI SDK compatibility
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {"prompt": 0.08, "completion": 0.08},
    "nvidia/nemotron-3-super-120b-a12b": {"prompt": 0.40, "completion": 0.40},
    "nvidia/Nemotron-3-Ultra-550b-a55b": {"prompt": 0.80, "completion": 0.80},
    "Qwen/Qwen3-Embedding-8B": {"prompt": 0.02, "completion": 0.00},
}

# In-Memory State Store — starts empty; populated exclusively by real API calls
_USAGE_STATE: Dict[str, Dict[str, Any]] = {}


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
    pricing = PRICING_PER_1M.get(norm_key, {"prompt": 0.08, "completion": 0.08})

    cost = (prompt_tokens * pricing["prompt"] / 1_000_000.0) + (
        completion_tokens * pricing["completion"] / 1_000_000.0
    )
    cost = round(cost, 6)

    # Update canonical model entry in memory
    for key in {norm_key, model_name}:
        if key not in _USAGE_STATE:
            _USAGE_STATE[key] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
        _USAGE_STATE[key]["calls"] += 1
        _USAGE_STATE[key]["prompt_tokens"] += prompt_tokens
        _USAGE_STATE[key]["completion_tokens"] += completion_tokens
        _USAGE_STATE[key]["cost"] = round(_USAGE_STATE[key]["cost"] + cost, 6)

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
        state = _USAGE_STATE.get(full_key) or _USAGE_STATE.get(short_key, {
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
        ]
    }
