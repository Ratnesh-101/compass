"""
Compass — Database Seeding Script.

Idempotently populates the database with realistic sample data across domains:
  - Projects: Hackathon ("Compass AI Assistant"), Coursework ("CS 61C - Architecture"), Code ("Nebius Integration")
  - Tasks with realistic deadlines (e.g. within 48-72 hours, overdue, completed)
  - Memory chunks with 768-dimension vectors (live from Nebius Token Factory or deterministic fallback)
  - Sample conversation history

Usage:
    python scripts/seed_data.py
"""

import os
import sys
import math
import asyncio
from datetime import datetime, date, timedelta, timezone
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

import asyncpg
from pgvector.asyncpg import register_vector
from backend.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Embedding Generator (Live Nebius or Deterministic 768-dim Vector)
# ---------------------------------------------------------------------------

def _generate_deterministic_embedding(text: str, dim: int = 768) -> list[float]:
    """Fallback generator: creates a deterministic normalized unit vector based on text hash."""
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(text))
    raw = [math.sin(seed + i * 0.17) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def get_embedding(text: str, client = None) -> list[float]:
    """Get a 768-dim embedding from the single canonical embedding service."""
    from backend.services.embeddings import get_embedding_sync
    return get_embedding_sync(text)


# ---------------------------------------------------------------------------
# Seed Data Definitions
# ---------------------------------------------------------------------------

PROJECTS = [
    {
        "name": "Compass AI Assistant",
        "domain": "hackathon",
        "description": "Personal AI assistant with persistent memory, Nemotron routing, and pgvector storage.",
    },
    {
        "name": "CS 61C - Architecture",
        "domain": "coursework",
        "description": "Great Ideas in Computer Architecture (Machine Structures) — RISC-V, pipelining, and memory hierarchy.",
    },
    {
        "name": "Nebius Integration",
        "domain": "code",
        "description": "Production integration for Nebius Token Factory models, Serverless Endpoints, and Neon PostgreSQL.",
    },
]

def get_tasks_data(project_ids: dict[str, int]) -> list[dict]:
    today = date.today()
    return [
        # Hackathon tasks (deadlines within 48-72h)
        {
            "domain": "hackathon",
            "project_id": project_ids["Compass AI Assistant"],
            "title": "Draft API specs and contract schemas",
            "due_date": today + timedelta(days=2),  # 48 hours
            "status": "in_progress",
            "priority": "urgent",
            "notes": "Ensure 100% parity with docs/api_contract.md for Nandani's frontend components.",
        },
        {
            "domain": "hackathon",
            "project_id": project_ids["Compass AI Assistant"],
            "title": "Ship router with Nemotron Nano function calling",
            "due_date": today + timedelta(days=3),  # 72 hours
            "status": "open",
            "priority": "high",
            "notes": "Confirmed native tool calling on nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B.",
        },
        # Coursework tasks
        {
            "domain": "coursework",
            "project_id": project_ids["CS 61C - Architecture"],
            "title": "Lab 3 submission — Two-stage pipelined CPU in Logisim",
            "due_date": today + timedelta(days=4),
            "status": "open",
            "priority": "high",
            "notes": "Resolve structural hazards between instruction fetch and memory writeback.",
        },
        {
            "domain": "coursework",
            "project_id": project_ids["CS 61C - Architecture"],
            "title": "Review RISC-V pipeline hazards lecture",
            "due_date": today - timedelta(days=1),  # Overdue task for timer/alert testing
            "status": "open",
            "priority": "medium",
            "notes": "Data hazards: forward-from-EX/MEM and forward-from-MEM/WB.",
        },
        # Code tasks
        {
            "domain": "code",
            "project_id": project_ids["Nebius Integration"],
            "title": "Embeddings truncation and Matryoshka dimension verification",
            "due_date": today + timedelta(days=7),
            "status": "done",
            "priority": "medium",
            "notes": "Qwen3-Embedding-8B supports dimensions=768, keeping vectors within HNSW limits.",
        },
        {
            "domain": "code",
            "project_id": project_ids["Nebius Integration"],
            "title": "Configure nightly memory consolidation cron job",
            "due_date": today + timedelta(days=5),
            "status": "open",
            "priority": "high",
            "notes": "Deploy batch/v1 CronJob running backend.jobs.consolidate at 02:00 UTC.",
        },
    ]


MEMORY_CHUNKS = [
    {
        "project_name": "Compass AI Assistant",
        "domain": "hackathon",
        "content": (
            "Compass Architecture Decision Record: We route user queries using Nemotron-3 Nano "
            "(nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B). Verified that native OpenAI function schemas "
            "work without requiring fallback JSON prompting."
        ),
        "source": "docs/architecture_decisions.md",
        "tags": ["architecture", "nemotron", "routing", "hackathon"],
    },
    {
        "project_name": "CS 61C - Architecture",
        "domain": "coursework",
        "content": (
            "RISC-V Pipeline Hazards Summary: A data hazard occurs when an instruction depends on the "
            "result of a previous instruction still in the pipeline. Forwarding (bypassing) routes data "
            "directly from EX/MEM or MEM/WB registers to the ALU inputs, avoiding pipeline stalls."
        ),
        "source": "notes/cs61c_week4_hazards.txt",
        "tags": ["coursework", "riscv", "pipelining", "hazards"],
    },
    {
        "project_name": "Nebius Integration",
        "domain": "code",
        "content": (
            "Nebius Token Factory Client Setup:\n"
            "client = OpenAI(api_key=NEBIUS_API_KEY, base_url='https://api.tokenfactory.nebius.com/v1/')\n"
            "res = client.embeddings.create(model='Qwen/Qwen3-Embedding-8B', input=text, dimensions=768)\n"
            "This ensures standard vector(768) columns with HNSW cosine indexes can be used."
        ),
        "source": "backend/memory/vector.py",
        "tags": ["code", "nebius", "pgvector", "embeddings"],
    },
]


# ---------------------------------------------------------------------------
# Database Seeder
# ---------------------------------------------------------------------------

async def seed():
    print("🧭 Starting Compass database seeding...")

    # Initialize OpenAI client if credentials exist
    client = None
    if settings.NEBIUS_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.NEBIUS_API_KEY, base_url=settings.NEBIUS_BASE_URL)
            print("  🔑 Nebius Token Factory API key detected — will generate live embeddings")
        except Exception as e:
            print(f"  ⚠️ Could not initialize OpenAI client ({e}), falling back to deterministic embeddings")

    dsn = settings.DATABASE_URL
    print(f"  🔌 Connecting to database: {dsn.split('@')[-1] if '@' in dsn else dsn}")

    try:
        conn = await asyncpg.connect(dsn)
        await register_vector(conn)
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        print("   Make sure PostgreSQL is running (e.g. docker compose up -d postgres)")
        sys.exit(1)

    try:
        # 1. Seed Projects
        print("\n  [1/4] Seeding Projects...")
        project_ids = {}
        for p in PROJECTS:
            row = await conn.fetchrow(
                """
                INSERT INTO projects (name, domain, description)
                VALUES ($1, $2, $3)
                ON CONFLICT (name) DO UPDATE
                SET description = EXCLUDED.description
                RETURNING id, name
                """,
                p["name"], p["domain"], p["description"]
            )
            if row:
                project_ids[row["name"]] = row["id"]
                print(f"    • Project [{p['domain'].upper()}]: '{p['name']}' (id={row['id']})")

        # 2. Seed Tasks
        print("\n  [2/4] Seeding Tasks...")
        tasks = get_tasks_data(project_ids)
        for t in tasks:
            # Check if task already exists
            existing = await conn.fetchrow(
                "SELECT id FROM tasks WHERE project_id = $1 AND title = $2",
                t["project_id"], t["title"]
            )
            if existing:
                print(f"    - Task already exists: '{t['title']}' (id={existing['id']})")
                continue

            row = await conn.fetchrow(
                """
                INSERT INTO tasks (domain, project_id, title, due_date, status, priority, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                t["domain"], t["project_id"], t["title"], t["due_date"],
                t["status"], t["priority"], t["notes"]
            )
            if row:
                print(f"    + Created task: '{t['title']}' (due {t['due_date']}, id={row['id']})")

        # 3. Seed Memory Chunks
        print("\n  [3/4] Seeding Memory Chunks with 768-dim Embeddings...")
        for mc in MEMORY_CHUNKS:
            existing = await conn.fetchrow(
                "SELECT id FROM memory_chunks WHERE source = $1",
                mc["source"]
            )
            if existing:
                print(f"    - Chunk already exists from source '{mc['source']}' (id={existing['id']})")
                continue

            emb = get_embedding(str(mc["content"]), client)
            proj_id = project_ids.get(mc["project_name"])
            row = await conn.fetchrow(
                """
                INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                mc["domain"], proj_id, mc["content"], emb, mc["source"], mc["tags"]
            )
            if row:
                print(f"    + Created chunk for '{mc['project_name']}' (dim={len(emb)}, id={row['id']})")

        # 4. Seed Conversation History
        print("\n  [4/4] Seeding Sample Conversation History...")
        conv_row = await conn.fetchrow(
            """
            INSERT INTO conversations (started_at, last_active_at)
            VALUES ($1, $2)
            RETURNING id
            """,
            datetime.now(timezone.utc) - timedelta(hours=2),
            datetime.now(timezone.utc)
        )
        if conv_row:
            cid = conv_row["id"]
            messages = [
                ("user", "What tasks do I have due this week?"),
                ("assistant", "You have 2 upcoming tasks:\n1. Draft API specs and contract schemas (due in 2 days)\n2. Ship router with Nemotron Nano function calling (due in 3 days)"),
            ]
            for role, content in messages:
                await conn.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, skill_called, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    cid, role, content, "tasks" if role == "assistant" else None, datetime.now(timezone.utc)
                )
            print(f"    • Seeded conversation {cid} with 2 messages.")

        print("\n✅ Database seeding complete!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
