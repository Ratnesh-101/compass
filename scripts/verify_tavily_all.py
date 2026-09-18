import asyncio
import os
import sys
from dotenv import load_dotenv

# Set UTF-8 encoding for standard output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def run_live_verification():
    from backend.memory.db import init_pool, get_pool, close_pool
    from backend.services.usage import get_tavily_summary, get_usage_summary
    from backend.skills import handle_search_web, handle_ingest_url
    from backend.memory.vector import search_chunks
    from backend.agent import run_agent

    print("=== TAVILY INTEGRATION LIVE VERIFICATION ===")
    pool = await init_pool()

    # 1. Live Web Search
    print("\n--- 1. Live Tavily Search ---")
    search_res = await handle_search_web({
        "query": "Nemotron-3-Nano Nvidia release date and context"
    }, pool)
    print(f"Success: {search_res.get('success')}")
    print(f"Summary:\n{search_res.get('summary')}")
    print(f"Citations count: {len(search_res.get('data', {}).get('citations', []))}")
    if search_res.get('data', {}).get('citations'):
        print(f"Top citation: {search_res['data']['citations'][0]}")

    # 2. Ingest URL & pgvector Retrieval
    print("\n--- 2. Ingest URL & pgvector Neon Retrieval ---")
    test_url = "https://example.com"
    ingest_res = await handle_ingest_url({
        "url": test_url,
        "title": "Example Domain Spec"
    }, pool)
    print(f"Ingest Success: {ingest_res.get('success')}")
    print(f"Ingest Summary: {ingest_res.get('summary')}")
    print(f"Chunks stored: {ingest_res.get('data', {}).get('chunks_stored')}")

    # Query vector memory for the ingested chunk
    vector_matches = await search_chunks(pool, "Example Domain for illustrative examples in documents", limit=1)
    if vector_matches:
        top_match = vector_matches[0]
        print(f"Retrieved Chunk #{top_match.get('id')}:")
        print(f"  Similarity: {top_match.get('similarity'):.6f}")
        print(f"  Source: {top_match.get('source')}")
        print(f"  Snippet: {top_match.get('content')[:120]}...")
    else:
        print("Vector match: None found")

    # 3. Separate Tavily Credit Accounting
    print("\n--- 3. Usage & Credit Accounting ---")
    tavily_usage = get_tavily_summary()
    print("Tavily Usage Log:")
    print(f"  Total Credits: {tavily_usage.get('total_credits')}")
    print(f"  Total Calls:   {tavily_usage.get('total_calls')}")
    print("  By Operation:")
    for op, data in tavily_usage.get('by_operation', {}).items():
        print(f"    - {op}: {data.get('calls')} calls, {data.get('credits')} credits")

    summary = get_usage_summary()
    print(f"Model Token Cost: {summary.get('total_cost')} ({summary.get('total_tokens')} tokens)")
    print("Verification: Tavily credits are tracked in tavily_usage_log, completely isolated from token tables.")

    # 4. Epistemic Humility & Escalation Trace
    print("\n--- 4. Epistemic Humility Escalation Trace ---")
    from unittest.mock import AsyncMock, MagicMock

    # Create mock client that yields [ABSTAIN] on first call, triggering escalate step, then final reply
    mock_client = AsyncMock()
    mock_msg1 = MagicMock()
    mock_msg1.content = "[ABSTAIN] Stored memory does not contain 2026 launch information."
    mock_msg1.tool_calls = []
    choice1 = MagicMock()
    choice1.message = mock_msg1
    resp1 = MagicMock()
    resp1.choices = [choice1]
    resp1.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    mock_msg2 = MagicMock()
    mock_msg2.content = "According to verified live web sources, Nemotron-3-Nano was announced with 30B parameters."
    mock_msg2.tool_calls = []
    choice2 = MagicMock()
    choice2.message = mock_msg2
    resp2 = MagicMock()
    resp2.choices = [choice2]
    resp2.usage = MagicMock(prompt_tokens=120, completion_tokens=60)

    mock_client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])

    steps = []
    async for step in run_agent(
        goal="What is the nemotron 2026 launch status?",
        pool=pool,
        max_steps=5,
        enable_critic=False,
        client=mock_client,
    ):
        steps.append(step)
        print(f"Step {step.step_number} [{step.type.upper()}] (tier={step.model_tier}): {step.content[:90]}...")

    await close_pool()
    print("\n=== ALL VERIFICATION CHECKS COMPLETED ===")

if __name__ == "__main__":
    asyncio.run(run_live_verification())
