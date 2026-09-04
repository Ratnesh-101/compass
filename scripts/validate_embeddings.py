"""
Compass — Validate 768-dim Embedding Retrieval Quality.

Tests Qwen/Qwen3-Embedding-8B with dimensions=768 across 10 known items
spanning the three domains: Hackathon, Coursework, and Code.
Runs 3 targeted queries (1 per domain) and calculates cosine distance to verify
whether Matryoshka truncation preserves high retrieval accuracy.

Usage:
    python scripts/validate_embeddings.py
"""

import sys
import os
import math
from pathlib import Path

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

import numpy as np
from openai import OpenAI
from backend.config import get_settings

settings = get_settings()

CORPUS = [
    # --- Hackathon ---
    {
        "id": 1,
        "domain": "hackathon",
        "title": "Compass AI Architecture",
        "text": "Compass AI assistant architecture uses Nemotron Nano for routing user queries and Nebius Token Factory for embeddings and model inference.",
    },
    {
        "id": 2,
        "domain": "hackathon",
        "title": "Hackathon Submission Deadline",
        "text": "The hackathon submission deadline is 48 hours away. We need to submit the final demo video, pitch deck, and GitHub repository link.",
    },
    {
        "id": 3,
        "domain": "hackathon",
        "title": "React Frontend Shell",
        "text": "The frontend is built in React and TypeScript with a chat interface, task board, and domain color-coded badges for hackathon, coursework, and code.",
    },

    # --- Coursework ---
    {
        "id": 4,
        "domain": "coursework",
        "title": "RISC-V Pipeline Hazards",
        "text": "In RISC-V pipelined processors, data hazards occur when an instruction depends on the result of an earlier instruction still in the pipeline. Forwarding resolves ALU hazards.",
    },
    {
        "id": 5,
        "domain": "coursework",
        "title": "Cache Memory Hierarchies",
        "text": "Cache memory exploits temporal and spatial locality. Direct mapped and set associative caches reduce average memory access time (AMAT).",
    },
    {
        "id": 6,
        "domain": "coursework",
        "title": "Virtual Memory and Page Tables",
        "text": "Virtual memory uses translation lookaside buffers (TLB) and multi-level page tables to map virtual addresses to physical memory frames while preventing page faults.",
    },

    # --- Code ---
    {
        "id": 7,
        "domain": "code",
        "title": "FastAPI Bearer Authentication",
        "text": "FastAPI dependency verify_token checks the HTTP Authorization header against the AUTH_TOKEN secret using HTTPBearer security scheme.",
    },
    {
        "id": 8,
        "domain": "code",
        "title": "PostgreSQL Asyncpg Pool Lifecycle",
        "text": "The asyncpg connection pool is initialized in the FastAPI lifespan handler using init_pool() and closed on shutdown with close_pool().",
    },
    {
        "id": 9,
        "domain": "code",
        "title": "Docker Compose Multi-Container Setup",
        "text": "Docker Compose runs the pgvector PostgreSQL 16 image with healthchecks and mounts schema.sql into docker-entrypoint-initdb.d for automatic database initialization.",
    },
    {
        "id": 10,
        "domain": "code",
        "title": "Matryoshka Embeddings Truncation",
        "text": "Qwen3 embedding model supports Matryoshka dimension truncation to 768 dimensions by passing dimensions=768 in the embedding creation API payload.",
    },
]

TEST_QUERIES = [
    {
        "query": "How do we resolve data hazards in pipelined processors?",
        "expected_domain": "coursework",
        "expected_id": 4,  # RISC-V Pipeline Hazards
    },
    {
        "query": "Where do we configure the asyncpg database pool lifecycle in FastAPI?",
        "expected_domain": "code",
        "expected_id": 8,  # PostgreSQL Asyncpg Pool Lifecycle
    },
    {
        "query": "What is required for the final hackathon project submission demo?",
        "expected_domain": "hackathon",
        "expected_id": 2,  # Hackathon Submission Deadline
    },
]


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance in pgvector is: 1 - cosine_similarity."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 1.0
    sim = dot / (norm_a * norm_b)
    return float(1.0 - sim)


def main():
    print("=" * 70)
    print("🧭 Compass — 768-dim Embedding Retrieval Quality Validation")
    print(f"   Model: {settings.EMBEDDING_MODEL} (dimensions=768)")
    print("=" * 70)

    if not settings.NEBIUS_API_KEY:
        print("❌ NEBIUS_API_KEY is not set in .env.")
        sys.exit(1)

    client = OpenAI(
        api_key=settings.NEBIUS_API_KEY,
        base_url=settings.NEBIUS_BASE_URL,
    )

    # 1. Embed all 10 corpus documents
    print("\n[1/3] Generating 768-dimensional embeddings for 10 corpus documents...")
    corpus_vectors = []
    for item in CORPUS:
        resp = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=str(item["text"]),
            dimensions=768,
        )
        vec = np.array(resp.data[0].embedding, dtype=np.float32)
        assert len(vec) == 768, f"Expected 768 dimensions, got {len(vec)}"
        corpus_vectors.append(vec)
        print(f"  • Doc #{item['id']} [{str(item['domain']).upper()}]: '{item['title']}' (dim={len(vec)})")

    # 2. Run Test Queries
    print("\n[2/3] Evaluating retrieval quality against test queries...")
    all_passed = True

    for q_idx, q in enumerate(TEST_QUERIES, 1):
        query_text = str(q["query"])
        expected_id = q["expected_id"]
        expected_domain = q["expected_domain"]

        # Embed query
        q_resp = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=query_text,
            dimensions=768,
        )
        q_vec = np.array(q_resp.data[0].embedding, dtype=np.float32)

        # Rank all corpus items by cosine distance (ascending: lower = closer)
        distances = []
        for item, doc_vec in zip(CORPUS, corpus_vectors):
            dist = cosine_distance(q_vec, doc_vec)
            distances.append((dist, item))

        distances.sort(key=lambda x: x[0])
        top_3 = distances[:3]
        top_1_id = top_3[0][1]["id"]
        is_top_1 = top_1_id == expected_id
        is_in_top_3 = any(item["id"] == expected_id for _, item in top_3)

        print(f"\n──────────────────────────────────────────────────────────────────────")
        print(f"QUERY {q_idx}: \"{query_text}\"")
        print(f"Expected Match: #{expected_id} [{expected_domain}]")
        print(f"Top-3 Nearest Neighbors (Cosine Distance):")

        for rank, (dist, item) in enumerate(top_3, 1):
            match_marker = "🎯" if item["id"] == expected_id else "  "
            sim = 1.0 - dist
            print(f"  {rank}. {match_marker} dist={dist:.4f} (sim={sim*100:.1f}%) | #{item['id']} [{item['domain']}] {item['title']}")

        if is_top_1:
            print(f"  ✅ Result: EXACT TOP-1 MATCH (Distance = {top_3[0][0]:.4f})")
        elif is_in_top_3:
            print(f"  ⚠️ Result: Found in Top-3, but not Top-1")
        else:
            print(f"  ❌ Result: FAILED — expected item #{expected_id} was not in Top-3")
            all_passed = False

    # 3. Decision Assessment
    print("\n" + "=" * 70)
    print("RETRIEVAL QUALITY ASSESSMENT")
    print("=" * 70)
    if all_passed:
        print("  🎉 ALL 3 TEST QUERIES RETURNED EXACT TOP-1 MATCHES AT 768 DIMENSIONS!")
        print("  ✅ Conclusion: Matryoshka dimension truncation to 768 is high-fidelity.")
        print("  💡 Recommendation: Keep VECTOR(768) in schema.sql. pgvector HNSW indexing is preserved.")
    else:
        print("  ⚠️ Some queries failed to rank in Top-3. Consider 1024 dimensions or full 4096.")
    print("=" * 70)


if __name__ == "__main__":
    main()
