import asyncio
import json
import statistics
import time
from typing import Any, Dict, List

import httpx

BASE_URL = "http://localhost:8000"
AUTH_HEADER = {"Authorization": "Bearer dev-token", "Content-Type": "application/json"}
WARM_RUNS = 5


async def single_stream_run(prompt: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    first_byte_time = None
    first_token_time = None
    tokens_received = []
    done_time = None
    skill_used = None

    async with httpx.AsyncClient(timeout=45.0) as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/api/chat/stream",
            headers=AUTH_HEADER,
            json={"message": prompt},
        ) as response:
            t_connect = time.perf_counter() - t0
            first_byte_time = t_connect

            async for chunk in response.aiter_lines():
                t_now = time.perf_counter() - t0
                if not chunk or not chunk.startswith("data:"):
                    continue
                raw_json = chunk[5:].strip()
                try:
                    data = json.loads(raw_json)
                    if data.get("type") == "token":
                        if first_token_time is None:
                            first_token_time = t_now
                        tokens_received.append(data.get("value", ""))
                    elif data.get("type") == "done":
                        done_time = t_now
                        skill_used = data.get("skill_used")
                except Exception:
                    pass

    full_text = "".join(tokens_received)
    total_time = done_time or (time.perf_counter() - t0)
    return {
        "connect_ms": (first_byte_time or 0) * 1000,
        "ttft_ms": (first_token_time or 0) * 1000,
        "total_ms": total_time * 1000,
        "tokens": len(tokens_received),
        "words": len(full_text.split()),
        "skill": skill_used,
        "text": full_text[:80],
    }


async def single_sync_run(prompt: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=45.0) as client:
        res = await client.post(
            f"{BASE_URL}/api/chat",
            headers=AUTH_HEADER,
            json={"message": prompt},
        )
        total_time = time.perf_counter() - t0
        data = res.json()
        return {
            "total_ms": total_time * 1000,
            "skill": data.get("skill_used"),
            "text": str(data.get("response", ""))[:80],
        }


def compute_stats(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"mean": 0.0, "var": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0}
    mean = statistics.mean(vals)
    var = statistics.variance(vals) if len(vals) > 1 else 0.0
    stddev = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return {
        "mean": round(mean, 1),
        "var": round(var, 1),
        "stddev": round(stddev, 1),
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
    }


async def benchmark_scenario(name: str, prompt: str, is_stream: bool) -> Dict[str, Any]:
    print("\n=======================================================")
    print(f"BENCHMARK: {name}")
    print(f"Prompt: \"{prompt}\"")
    print("=======================================================")

    # 1. Isolated Cold Start run (Run 0)
    if is_stream:
        cold_res = await single_stream_run(prompt)
        print(
            f"  [Cold Start]: TTFT={cold_res['ttft_ms']:.1f}ms, Total={cold_res['total_ms']:.1f}ms, "
            f"Connect={cold_res['connect_ms']:.1f}ms, Chunks={cold_res['tokens']}"
        )
    else:
        cold_res = await single_sync_run(prompt)
        print(f"  [Cold Start]: Total={cold_res['total_ms']:.1f}ms, Skill={cold_res['skill']}")

    await asyncio.sleep(0.5)

    # 2. Warm iterations (Runs 1 to WARM_RUNS)
    warm_results = []
    for i in range(1, WARM_RUNS + 1):
        if is_stream:
            res = await single_stream_run(prompt)
            print(
                f"  Run {i}/{WARM_RUNS} (Warm): TTFT={res['ttft_ms']:.1f}ms, Total={res['total_ms']:.1f}ms, "
                f"Connect={res['connect_ms']:.1f}ms, Skill={res['skill']}, Chunks={res['tokens']}"
            )
        else:
            res = await single_sync_run(prompt)
            print(f"  Run {i}/{WARM_RUNS} (Warm): Total={res['total_ms']:.1f}ms, Skill={res['skill']}")
        warm_results.append(res)
        await asyncio.sleep(0.3)

    warm_total_stats = compute_stats([r["total_ms"] for r in warm_results])
    warm_ttft_stats = compute_stats([r["ttft_ms"] for r in warm_results]) if is_stream else None
    warm_connect_stats = compute_stats([r["connect_ms"] for r in warm_results]) if is_stream else None
    avg_chunks = round(statistics.mean([r["tokens"] for r in warm_results])) if is_stream else 0

    print(f"-> Summary for {name} (Warm State N={WARM_RUNS}):")
    if warm_ttft_stats:
        print(f"   TTFT:   mean={warm_ttft_stats['mean']}ms, stddev=±{warm_ttft_stats['stddev']}ms, var={warm_ttft_stats['var']}")
    print(f"   Total:  mean={warm_total_stats['mean']}ms, stddev=±{warm_total_stats['stddev']}ms, var={warm_total_stats['var']}")
    if is_stream:
        print(f"   Chunks: average={avg_chunks} chunks per response")

    return {
        "name": name,
        "is_stream": is_stream,
        "cold": cold_res,
        "warm_ttft": warm_ttft_stats,
        "warm_connect": warm_connect_stats,
        "warm_total": warm_total_stats,
        "chunks": avg_chunks,
    }


async def main():
    benchmarks = [
        ("Conversational — Stream", "hey, what can you help with", True),
        ("Conversational — Sync", "hey, what can you help with", False),
        ("Skill/Tool — Stream", "show my coursework tasks", True),
        ("Skill/Tool — Sync", "show my coursework tasks", False),
    ]

    all_data = []
    for name, prompt, is_stream in benchmarks:
        data = await benchmark_scenario(name, prompt, is_stream)
        all_data.append(data)

    print("\n\n" + "=" * 80)
    print("CONSOLIDATED MULTI-RUN BENCHMARK REPORT (WARM-STATE N=5 WITH SEPARATE COLD-START)")
    print("=" * 80)
    print("| Scenario | Mode | Cold Start (TTFT / Total) | Warm TTFT Mean (±StdDev) [Var] | Warm Total Mean (±StdDev) [Var] | Chunks |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for d in all_data:
        mode = "Stream" if d["is_stream"] else "Sync"
        if d["is_stream"]:
            cold_str = f"{d['cold']['ttft_ms']:.1f}ms / {d['cold']['total_ms']:.1f}ms"
            ttft_str = f"**{d['warm_ttft']['mean']} ms** (±{d['warm_ttft']['stddev']} ms) [{d['warm_ttft']['var']}]"
            chunks_str = f"{d['chunks']} chunks"
        else:
            cold_str = f"N/A / {d['cold']['total_ms']:.1f}ms"
            ttft_str = "N/A (Sync buffer)"
            chunks_str = "1 (Monolithic)"
        tot_str = f"**{d['warm_total']['mean']} ms** (±{d['warm_total']['stddev']} ms) [{d['warm_total']['var']}]"
        print(f"| {d['name']} | {mode} | {cold_str} | {ttft_str} | {tot_str} | {chunks_str} |")


if __name__ == "__main__":
    asyncio.run(main())
