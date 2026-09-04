"""
Compass — Cross-Domain Synthesis & Usage Logging.

Handles calling nvidia/Nemotron-3-Ultra-550b-a55b for daily standups,
overdue summaries, and logging token consumption to the usage_log table.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import asyncpg
from openai import OpenAI

from backend.config import get_settings

logger = logging.getLogger("compass.skills.synthesis")
settings = get_settings()


async def log_token_usage(
    conn: asyncpg.Connection,
    model: str,
    input_tokens: int,
    output_tokens: int,
    skill: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate cost based on configured token rates and write to usage_log."""
    rate_in = settings.COST_PER_1M_INPUT.get(model, 0.0)
    rate_out = settings.COST_PER_1M_OUTPUT.get(model, 0.0)

    cost = ((input_tokens / 1_000_000.0) * rate_in) + ((output_tokens / 1_000_000.0) * rate_out)
    cost = round(cost, 6)

    try:
        row = await conn.fetchrow(
            """
            INSERT INTO usage_log (model, input_tokens, output_tokens, estimated_cost_usd, skill)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, model, input_tokens, output_tokens, estimated_cost_usd, skill, created_at
            """,
            model, input_tokens, output_tokens, cost, skill
        )
        return dict(row) if row else {}
    except Exception as e:
        logger.warning(f"Failed to insert into usage_log: {e}")
        return {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
            "skill": skill,
        }
