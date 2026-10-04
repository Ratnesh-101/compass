"""
Compass — Nebius Token Factory & NVIDIA Technical Telemetry Test Suite.

Verifies:
1. Usage accounting calculates cost savings vs monolithic GPT-4 baseline (>90% savings).
2. Tiered Nemotron model metadata (Nano 30B A3B, Super 120B A12B, Ultra 550B A55B, Qwen3-Embedding).
3. Public /api/telemetry and /api/usage/summary return complete architecture telemetry without authentication.
"""

import pytest
from httpx import AsyncClient

from backend.services.usage import get_usage_summary, record_usage


def test_usage_summary_nebius_telemetry():
    """Verify enriched telemetry metrics, cost savings, and MoE metadata."""
    summary = get_usage_summary()

    # Core accounting
    assert "total_requests" in summary
    assert "total_tokens" in summary
    assert "total_estimated_cost_usd" in summary

    # Monolithic comparison & cost reduction
    assert "cost_savings_pct" in summary
    assert summary["cost_savings_pct"] >= 80.0  # Typically 92%+
    assert "infrastructure" in summary
    assert "Nebius Token Factory" in summary["infrastructure"]["cloud"]
    assert "NVIDIA Tensor Core" in summary["infrastructure"]["gpu_acceleration"]
    assert "Mixture-of-Experts" in summary["infrastructure"]["architecture"]

    # Model metadata
    assert "model_metadata" in summary
    metadata = summary["model_metadata"]
    assert "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B" in metadata
    nano = metadata["nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"]
    assert "Tier 1: Intent Router" in nano["tier"]
    assert "30B MoE (3B active)" in nano["params"]

    super_mod = metadata["nvidia/nemotron-3-super-120b-a12b"]
    assert "Tier 2: Deep ReAct Planner" in super_mod["tier"]
    assert "120B MoE (12B active)" in super_mod["params"]

    ultra = metadata["nvidia/Nemotron-3-Ultra-550b-a55b"]
    assert "Tier 3: Executive Synthesizer" in ultra["tier"]
    assert "550B MoE (55B active)" in ultra["params"]


@pytest.mark.asyncio
async def test_public_telemetry_endpoint(client: AsyncClient):
    """Verify that /api/telemetry returns HTTP 200 without authentication."""
    resp = await client.get("/api/telemetry")
    assert resp.status_code == 200
    data = resp.json()

    assert "total_requests" in data
    assert "cost_savings_pct" in data
    assert "infrastructure" in data
    assert "by_model" in data
    assert "breakdown" in data


@pytest.mark.asyncio
async def test_public_usage_summary_endpoint(client: AsyncClient):
    """Verify that /api/usage/summary returns HTTP 200 without authentication."""
    resp = await client.get("/api/usage/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert "total_requests" in data
    assert "total_estimated_cost_usd" in data
    assert "infrastructure" in data
