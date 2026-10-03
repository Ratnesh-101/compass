"""
Compass — Task Verification, Dependencies, and Demo Seeding Endpoints.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.dependencies import _get_current_identity, _get_or_create_user_id, rate_limit
from backend.memory import structured
from backend.memory.db import get_pool
from backend.models import AddDependencyBody

logger = logging.getLogger("compass.routers.tasks_verification")

router = APIRouter(tags=["tasks_verification"])


# ---- Task Dependencies Endpoints --------------------------------------
@router.get("/api/tasks/{task_id}/dependencies")
async def get_task_dependencies_endpoint(task_id: int):
    """Retrieve prerequisite dependencies for a task."""
    pool = await get_pool()
    if not pool:
        return []
    async with pool.acquire() as conn:
        return await structured.get_task_dependencies(conn, task_id)


@router.post("/api/tasks/{task_id}/dependencies")
async def add_task_dependency_endpoint(task_id: int, body: AddDependencyBody):
    """Add a prerequisite dependency: task_id depends on body.depends_on_task_id."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")
    try:
        prereq_id = body.get_prerequisite_id()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    async with pool.acquire() as conn:
        try:
            dep = await structured.add_task_dependency(conn, task_id, prereq_id)
            return {"status": "ok", "dependency": dep}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/tasks/{task_id}/dependencies/{depends_on_task_id}")
async def remove_task_dependency_endpoint(task_id: int, depends_on_task_id: int):
    """Remove a dependency edge."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")
    async with pool.acquire() as conn:
        deleted = await structured.remove_task_dependency(conn, task_id, depends_on_task_id)
        return {"status": "ok", "deleted": deleted}


# ---- 1-Click Judge Demo Persona Seeding ------------------------------------
@router.post("/api/demo/seed", dependencies=[Depends(rate_limit)])
async def seed_demo_persona_endpoint(request: Request):
    """Seed or refresh the Dual-Degree Hackathon Competitor demo persona for judges.
    Requires an authenticated user session or verified guest identity.
    Writes seeded tasks and memories strictly bound to the caller's identity.
    """
    ident = _get_current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Authentication required: active session or guest token required to seed demo data.")

    user_id = ident.id
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")

    today = date.today()
    days_to_sunday = (6 - today.weekday()) % 7
    if days_to_sunday == 0:
        days_to_sunday = 7
    upcoming_sunday = today + timedelta(days=days_to_sunday)

    async with pool.acquire() as conn:
        p_hack = await structured.get_or_create_project(conn, name="Compass AI Assistant", domain="hackathon")
        p_course = await structured.get_or_create_project(conn, name="CS 61C - Computer Architecture", domain="coursework")
        p_code = await structured.get_or_create_project(conn, name="Nebius Integration & Infrastructure", domain="code")

        demo_tasks: list[dict[str, Any]] = [
            {
                "title": "36-hour Hackathon Sprint: Final Demo Build",
                "domain": "hackathon",
                "project_id": p_hack["id"],
                "due_date": upcoming_sunday,
                "priority": "urgent",
                "duration_minutes": 2160,
                "notes": "Full weekend sprint to finalize 3-minute video demo, pitch deck, and Nebius Token Factory endpoints.",
            },
            {
                "title": "CS 61C Lab 4: RISC-V Pipeline Synthesis",
                "domain": "coursework",
                "project_id": p_course["id"],
                "due_date": upcoming_sunday,
                "priority": "urgent",
                "duration_minutes": 480,
                "notes": "Two-stage pipelined CPU in Logisim with forwarding and hazard resolution.",
            },
            {
                "title": "Nebius Buildathon Phase 2 Submission",
                "domain": "hackathon",
                "project_id": p_hack["id"],
                "due_date": date(2026, 9, 17),
                "priority": "high",
                "duration_minutes": 120,
                "notes": "Original hackathon milestone to demonstrate live Tavily schedule drift detection.",
            },
            {
                "title": "Embeddings truncation and Matryoshka dimension verification",
                "domain": "code",
                "project_id": p_code["id"],
                "due_date": today + timedelta(days=5),
                "priority": "medium",
                "status": "done",
                "duration_minutes": 90,
                "notes": "Qwen3-Embedding-8B truncated to 768 dims to fit pgvector HNSW limit (<2,000 dims).",
            },
            {
                "title": "Record 3-minute Devpost demo video",
                "domain": "hackathon",
                "project_id": p_hack["id"],
                "due_date": today + timedelta(days=3),
                "priority": "urgent",
                "duration_minutes": 180,
                "notes": "Record, edit, and upload demo video to YouTube. Cover epistemic abstention, confirm gates, and feasibility engine.",
            },
            {
                "title": "CS 61C Midterm Review: Cache Hierarchies & Virtual Memory",
                "domain": "coursework",
                "project_id": p_course["id"],
                "due_date": today + timedelta(days=6),
                "priority": "high",
                "duration_minutes": 300,
                "notes": "Review L1/L2 cache design, TLB mechanics, page table walks, and AMAT calculations.",
            },
            {
                "title": "Deploy Compass backend to Nebius Serverless Endpoints",
                "domain": "code",
                "project_id": p_code["id"],
                "due_date": today + timedelta(days=4),
                "priority": "high",
                "duration_minutes": 240,
                "notes": "Activate deploy/serverless_endpoint.yaml manifest on Nebius AI Cloud. Verify health probes and autoscaling.",
            },
        ]

        seeded_task_ids = []
        for t in demo_tasks:
            existing = await conn.fetchrow(
                "SELECT id FROM tasks WHERE title = $1 AND (user_id = $2 OR user_id IS NULL)",
                t["title"], user_id,
            )
            if existing:
                seeded_task_ids.append(existing["id"])
                continue

            row = await structured.create_task(
                conn,
                domain=str(t["domain"]),
                title=str(t["title"]),
                project_id=t.get("project_id"),
                due_date=t.get("due_date"),
                priority=str(t.get("priority", "medium")),
                status=str(t.get("status", "open")),
                notes=t.get("notes"),
                user_id=user_id,
            )
            if t.get("duration_minutes"):
                await structured.update_task(conn, row["id"], duration_minutes=int(t["duration_minutes"]))
            seeded_task_ids.append(row["id"])

        memories: list[dict[str, Any]] = [
            {
                "domain": "code",
                "project_id": p_code["id"],
                "content": (
                    "Why Compass uses Matryoshka 768-dimension embeddings: pgvector HNSW index has a 2000-dimension limit. "
                    "Qwen3-Embedding-8B outputs 4096 dims by default. We truncate to 768 dims with L2 normalization, "
                    "preserving 100% top-1 recall in retrieval benchmarks while achieving sub-5ms cosine search (<->)."
                ),
                "tags": ["architecture", "pgvector", "embeddings", "matryoshka", "nebius"],
            },
            {
                "domain": "hackathon",
                "project_id": p_hack["id"],
                "content": (
                    "Compass 3-Tier NVIDIA Nemotron Architecture: Nemotron-3 Nano (30B MoE, 3B active) executes sub-400ms "
                    "intent routing; Nemotron-3 Super (120B MoE, 12B active) executes ReAct multi-step planning and grounded "
                    "code retrieval; Nemotron-3 Ultra (550B MoE, 55B active) executes executive roadmaps. "
                    "Hosted on Nebius Token Factory on NVIDIA Tensor Core H100/H200 GPUs with active MoE parameter routing."
                ),
                "tags": ["nemotron", "nvidia", "nebius", "routing", "moe"],
            },
            {
                "domain": "coursework",
                "project_id": p_course["id"],
                "content": (
                    "CS 61C Coursework Lab 4 Architecture: Two-stage pipelined CPU datapath with hazard detection unit, "
                    "EX/MEM and MEM/WB forwarding paths, and 1-cycle stall branch prediction penalty simulation in Logisim."
                ),
                "tags": ["coursework", "cs61c", "riscv", "pipeline"],
            },
        ]

        from backend.services.embeddings import get_embedding
        seeded_mem_count = 0
        for m in memories:
            ex_mem = await conn.fetchval(
                "SELECT id FROM memory_chunks WHERE content = $1 AND (user_id = $2 OR ($2 IS NULL AND user_id IS NULL)) LIMIT 1",
                m["content"],
                user_id,
            )
            if ex_mem:
                continue
            emb = await get_embedding(m["content"])
            await conn.execute(
                """
                INSERT INTO memory_chunks (domain, project_id, content, embedding, source, tags, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                m["domain"], m["project_id"], m["content"], emb, "judge_demo_persona", m["tags"], user_id,
            )
            seeded_mem_count += 1

    return {
        "status": "ok",
        "message": "Judge Demo Persona loaded successfully.",
        "persona": "Dual-Degree Hackathon Competitor",
        "tasks_seeded": len(seeded_task_ids),
        "memories_seeded": seeded_mem_count,
    }


# ---- Tavily Live Deadline Verification -------------------------------------
@router.post("/api/tasks/{task_id}/verify")
async def verify_task_deadline_endpoint(task_id: int, request: Request):
    """Verify a task deadline against live official web sources using Tavily."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")
    try:
        from backend.skills.handlers.web import handle_verify_deadline
        result = await handle_verify_deadline({"task_id": task_id}, pool)
        return result
    except Exception as e:
        logger.error(f"Failed to verify task {task_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": "Internal verification error",
            "summary": "Verification could not be completed at this time.",
            "data": {},
        }


@router.post("/api/tasks/verify-deadlines")
async def verify_all_deadlines_endpoint(request: Request):
    """Proactively verify open deadlines across tasks using Tavily web search."""
    pool = await get_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="Database unavailable")
    ident = _get_current_identity(request)
    user_id = ident.id if ident else None
    try:
        from backend.skills.handlers.web import handle_verify_deadline
        async with pool.acquire() as conn:
            open_tasks = await structured.list_tasks(conn, status="open", user_id=user_id, limit=5)

        verifications = []
        for t in open_tasks:
            if not t.get("title"):
                continue
            res = await handle_verify_deadline({"task_id": t["id"]}, pool)
            verifications.append({
                "task_id": t["id"],
                "title": t["title"],
                "domain": t.get("domain", "general"),
                "due_date": str(t.get("due_date") or ""),
                "result": res,
            })

        return {
            "status": "ok",
            "checked_count": len(verifications),
            "verifications": verifications,
        }
    except Exception as e:
        logger.error(f"Failed to batch verify deadlines: {e}", exc_info=True)
        return {
            "status": "error",
            "error": "Internal verification error",
            "verifications": [],
        }
