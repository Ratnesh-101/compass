#!/usr/bin/env python3
"""
Compass — Router Latency Benchmark Script.

Measures the actual latency of the Nemotron-3 Nano router across 10 representative
queries to calculate min, median, and p95 response times on Nebius Token Factory.

Usage:
    export NEBIUS_API_KEY="your-real-key"
    python scripts/measure_router_latency.py
"""

import asyncio
import os
import sys
import time
from typing import List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import get_settings
from backend.router import route_message

REPRESENTATIVE_MESSAGES: List[str] = [
    "What are my deadlines this week?",
    "Add a task to submit the CS report tomorrow at 5pm",
    "What's the weather like today?",
    "Remember that my name is Alex",
    "Forget my goal",
    "Can you help me brainstorm ideas for my hackathon project?",
    "List my calendar events for tomorrow",
    "What notes do I have about machine learning?",
    "How can I balance coursework with hackathon prep?",
    "Tell me a joke",
]


def calculate_p95(latencies: List[float]) -> float:
    """Compute 95th percentile latency from sorted values."""
    sorted_vals = sorted(latencies)
    if not sorted_vals:
        return 0.0
    idx = int(0.95 * len(sorted_vals))
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


async def benchmark_router() -> None:
    settings = get_settings()

    api_key = settings.NEBIUS_API_KEY or os.environ.get("NEBIUS_API_KEY")
    is_placeholder = (
        not api_key
        or api_key.startswith("your_nebius")
        or api_key in ("mock", "mock-key-not-used-in-tests")
    )

    if is_placeholder:
        print("\n" + "=" * 65)
        print("⚠️  NEBIUS_API_KEY is not configured or is a placeholder.")
        print("=" * 65)
        print("To measure live router latency against Nebius Token Factory:")
        print("  1. export NEBIUS_API_KEY=\"<your_nebius_api_key>\"")
        print("  2. python scripts/measure_router_latency.py")
        print("\nNote: Fallback mock routing runs in sub-1ms and is not")
        print("reflective of live network and token generation latency.")
        print("=" * 65 + "\n")
        return

    print("\n" + "=" * 65)
    print("🚀 Benchmarking Nemotron-3 Nano Router on Nebius Token Factory")
    print(f"Model: {settings.ROUTER_MODEL}")
    print(f"Endpoint: {settings.NEBIUS_BASE_URL}")
    print(f"Sample size: {len(REPRESENTATIVE_MESSAGES)} representative messages")
    print("=" * 65 + "\n")

    latencies_ms: List[float] = []

    for i, msg in enumerate(REPRESENTATIVE_MESSAGES, start=1):
        print(f"[{i:02d}/{len(REPRESENTATIVE_MESSAGES):02d}] Prompt: \"{msg[:45]}...\"" if len(msg) > 45 else f"[{i:02d}/{len(REPRESENTATIVE_MESSAGES):02d}] Prompt: \"{msg}\"")
        start = time.perf_counter()
        skill, args, text = await route_message(msg)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        latencies_ms.append(elapsed_ms)

        routed_target = f"tool:{skill}" if skill else "chat_fallback"
        print(f"       ↳ Latency: {elapsed_ms:.1f}ms (target: {routed_target})")

    min_lat = min(latencies_ms)
    median_lat = sorted(latencies_ms)[len(latencies_ms) // 2]
    p95_lat = calculate_p95(latencies_ms)

    print("\n" + "-" * 65)
    print("📊 Latency Results:")
    print(f"   Min latency:    {min_lat:.1f} ms")
    print(f"   Median latency: {median_lat:.1f} ms")
    print(f"   P95 latency:    {p95_lat:.1f} ms")
    print("-" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(benchmark_router())
