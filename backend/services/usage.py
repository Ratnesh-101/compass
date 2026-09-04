"""
Compass — Token & Cost Accounting Store.

Tracks token consumption and computes estimated cost for Nebius & NVIDIA models.
Records usage into the PostgreSQL `usage_log` table and provides fallback in-memory metrics.
"""

import logging
from typing import Optional, Dict, Any
import asyncpg
from backend.config import get_settings

logger = logging.getLogger("compass.services.usage")
settings = get_settings()

# Pricing constants (USD per 1M tokens)
PRICE_PER_1M_INPUT = {
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": 0.12,
    "nvidia/nemotron-3-super-120b-a12b": 0.40,
    "nvidia/Nemotron-3-Ultra-550b-a55b": 3.00,
    "Qwen/Qwen3-Embedding-8B": 0.05,
}

PRICE_PER_1M_OUTPUT = {
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": 0.12,
    "nvidia/nemotron-3-super-120b-a12b": 0.40,
    "nvidia/Nemotron-3-Ultra-550b-a55b": 3.00,
    "Qwen/Qwen3-Embedding-8B": 0.00,
}

# In-memory fallback accumulator
_IN_MEMORY_USAGE: Dict[str, Dict[str, Any]] = {
    m: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
    for m in PRICE_PER_1M_INPUT
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in USD based on model pricing."""
    in_rate = PRICE_PER_1M_INPUT.get(model, 0.12)
    out_rate = PRICE_PER_1M_OUTPUT.get(model, 0.12)
    cost = (input_tokens * in_rate / 1_000_000.0) + (output_tokens * out_rate / 1_000_000.0)
    return round(cost, 6)


async def record_usage(
    conn: Optional[asyncpg.Connection],
    model: str,
    input_tokens: int,
    output_tokens: int,
    skill: Optional[str] = None,
) -> float:
    """Record token consumption in PostgreSQL usage_log or in-memory fallback."""
    cost = compute_cost(model, input_tokens, output_tokens)

    # Always update in-memory tracker
    if model in _IN_MEMORY_USAGE:
        _IN_MEMORY_USAGE[model]["calls"] += 1
        _IN_MEMORY_USAGE[model]["input_tokens"] += input_tokens
        _IN_MEMORY_USAGE[model]["output_tokens"] += output_tokens
        _IN_MEMORY_USAGE[model]["estimated_cost_usd"] = round(
            _IN_MEMORY_USAGE[model]["estimated_cost_usd"] + cost, 6
        )

    # Persist in DB if connection available
    if conn:
        try:
            await conn.execute(
                """
                INSERT INTO usage_log (model, input_tokens, output_tokens, estimated_cost_usd, skill)
                VALUES ($1, $2, $3, $4, $5)
                """,
                model, input_tokens, output_tokens, cost, skill,
            )
        except Exception as e:
            logger.warning(f"Could not persist usage_log to DB: {e}")

    return cost


async def seed_initial_demo_usage(conn: asyncpg.Connection) -> None:
    """Populate baseline realistic usage entries for the demo recording if empty."""
    count = await conn.fetchval("SELECT COUNT(*) FROM usage_log")
    if count == 0:
        logger.info("Seeding baseline token usage metrics for demo...")
        # 1. Nemotron Nano router calls (warmup + function classification)
        await record_usage(conn, "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", 2450, 480, skill="router")
        # 2. Nemotron Super reasoning
        await record_usage(conn, "nvidia/nemotron-3-super-120b-a12b", 1820, 620, skill="synthesis")
        # 3. Nemotron Ultra cross-domain roadmap
        await record_usage(conn, "nvidia/Nemotron-3-Ultra-550b-a55b", 3100, 950, skill="synthesis")
        # 4. Qwen3-Embedding-8B vector generations
        await record_usage(conn, "Qwen/Qwen3-Embedding-8B", 4200, 0, skill="embeddings")
