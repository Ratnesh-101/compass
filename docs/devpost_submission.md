# Compass — Devpost Submission Draft

## 1. Project Overview
* **Tagline**: Personal AI assistant with persistent memory across hackathons, coursework, and code repositories.
* **Track / Category**: Best Use of Nebius Token Factory & NVIDIA Open-Source Models.
* **Team**: Ratnesh Singh (Infra / Deployment / Backend), Nandani (Frontend / UI), Rhythm (Memory / Skills).

---

## 2. Inspiration
Engineers, researchers, and students constantly context-switch between three distinct spheres:
1. Fast-paced hackathon projects with imminent submission deadlines.
2. University coursework with assignments, lecture concepts, and exam timelines.
3. Multi-repo codebases with scattered configs, architecture decisions, and setup patterns.

Standard LLM chats lose context between sessions, while rigid task trackers lack cognitive understanding. We built **Compass** to act as a single, persistent cognitive layer — one shared brain accessible via a rich web dashboard and a lightning-fast CLI.

---

## 3. What It Does
* **Unified Multi-Domain Memory**: Automatically categorizes and routes context across Hackathon, Coursework, Code, and General domains.
* **Instant Conversational Task Dispatch**: Users say natural instructions like *"Schedule Compass submission video on Oct 30 under Hackathon"*, and Compass parses, fuzzy-resolves the project, and persists it into PostgreSQL.
* **Cross-Session Vector Retrieval**: Semantically recalls snippets, architecture decisions, and coursework notes using pgvector cosine search.
* **Autonomous Memory Consolidation**: A nightly worker flags overdue deadlines, merges near-duplicate vector chunks, and rolls up stale conversations into dense long-term summaries.

---

## 4. How We Built It
Compass is powered by a multi-tiered architecture orchestrated across Nebius Token Factory:

```
[Clients: Web Dashboard (React + Vite) & CLI (Typer + Rich)]
                           │
                     (Bearer Auth)
                           ▼
          [FastAPI Backend & Skills Registry]
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
 [Nemotron-3 Nano]   [Nemotron Super]    [Nemotron Ultra]
  Routing & Tools     Skill Reasoning     Daily Standup &
  (<400ms latency)    & Execution         Consolidation
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ▼
             [Qwen3-Embedding-8B (768d)]
                           ▼
        [Nebius Managed PostgreSQL 16 + pgvector]
          (HNSW 768-dim Index, Tasks, Messages)
```

* **FastAPI Backend**: Clean asynchronous service using `asyncpg` connection pooling and lifespan management.
* **Routing Tier**: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on Nebius Token Factory using native OpenAI-compatible function calling schemas.
* **Vector Tier**: `Qwen/Qwen3-Embedding-8B` utilizing **Matryoshka dimension truncation (`dimensions=768`)** to fit within PostgreSQL's 2,000-dimension HNSW indexing ceiling without precision loss.
* **Storage Tier**: PostgreSQL 16 with `pgvector` hosted on **Nebius Managed Service for PostgreSQL**.

---

## 5. Challenges & How We Overcame Them

### 1. Vector Dimension Ceilings in PostgreSQL
* **Challenge**: `Qwen/Qwen3-Embedding-8B` outputs 4096-dimensional vectors by default. However, `pgvector`'s high-speed HNSW index currently enforces a 2,000-dimension limit.
* **Solution**: We leveraged the model's native Matryoshka Representation Learning via `dimensions=768` on Nebius Token Factory. We designed a validation suite (`scripts/validate_embeddings.py`) evaluating 10 domain documents against 3 targeted queries. The truncated 768-dim embeddings achieved 100% Top-1 recall with a >25% cosine margin above distractors.

### 2. Eliminating Fragile JSON Fallback Parsing
* **Challenge**: Many router implementations rely on prompting models for raw JSON strings, which frequently suffer from markdown formatting errors, syntax truncation, and hallucinations.
* **Solution**: We verified that `NVIDIA-Nemotron-3-Nano-30B-A3B` natively accepts OpenAI function definitions (`tools` and `tool_choice: "auto"`). Arguments are validated directly into Pydantic models.

---

## 6. Feedback for Nebius & NVIDIA

* **Nebius Token Factory**: Model inference speeds were exceptional. The Nemotron Nano response latency consistently hovered around 350-400ms, making conversational interaction feel instant.
* **Matryoshka Support**: The ability to pass the `dimensions` parameter directly in the embeddings API call without client-side slicing significantly reduced network overhead and storage costs.
* **Managed PostgreSQL**: Co-locating the pgvector database inside the same Nebius VPC brought vector query latencies down to sub-3ms.
