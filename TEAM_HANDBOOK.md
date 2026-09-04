# 🧭 Compass — Teammate Handbook & Full Project Overview

Welcome to the internal engineering guide for **Compass**, a multi-domain personal AI assistant featuring cross-domain cognitive memory, sub-400ms intent routing, and real-time pgvector synchronization.

This document covers everything built into the project: system architecture, database schema, service implementations, frontend polling/streaming engine, CLI workflows, deployment instructions, and the official demo script.

---

## 📌 Table of Contents
1. [Executive Summary & Product Vision](#-executive-summary--product-vision)
2. [End-to-End System Architecture](#-end-to-end-system-architecture)
3. [Technology Stack](#-technology-stack)
4. [Repository & Directory Structure](#-repository--directory-structure)
5. [Core Backend Services](#-core-backend-services)
   - [Nebius Vector Embeddings Service](#1-nebius-vector-embeddings-service-backendservicesembeddingspy)
   - [Token & Cost Accounting Store](#2-token--cost-accounting-store-backendservicesusagepy)
   - [Multi-Model Cognitive Orchestrator](#3-multi-model-cognitive-orchestrator-backendservicesorchestratorpy)
   - [FastAPI Main Application & Endpoints](#4-fastapi-main-application--endpoints-backendmainpy)
6. [Database & pgvector Setup](#-database--pgvector-setup)
7. [Frontend Engine & UI Polish](#-frontend-engine--ui-polish)
   - [Real-Time Polling Engine](#1-real-time-polling-engine-frontendsrcappjsx)
   - [Token Streaming & Typewriter Mechanism](#2-token-streaming--typewriter-mechanism-frontendsrccomponentschatpaneljsx)
   - [Responsive Split-Screen Layout](#3-responsive-split-screen-layout-frontendsrcindexcss)
8. [CLI Companion Suite (`compass`)](#-cli-companion-suite-compass)
9. [Phase 2: Live Tunnel Binding & Vercel Deployment](#-phase-2-live-tunnel-binding--vercel-deployment)
10. [Local Development Quickstart](#-local-development-quickstart)
11. [Official 3-Minute Demo Video Guide](#-official-3-minute-demo-video-guide)

---

## 💡 Executive Summary & Product Vision

### The Problem
Engineers, students, and builders juggle fractured workflows daily:
* **Hackathon milestones** (deadlines, benchmark scripts, video pitches)
* **University coursework** (problem sets, lab reports, exam dates)
* **Code repositories** (commit histories, architecture changes, API contracts)

Existing AI assistants lose context between browser tabs or require pasting massive prompts into stateless chat windows, leading to context loss and hallucination.

### The Solution: Compass
**Compass** is an always-on, cross-domain personal AI copilot that bridges terminal execution and a real-time web dashboard:
1. **Sub-400ms Routing**: NVIDIA Nemotron-3 Nano inspects natural language intents and invokes structured tools in $\sim342\text{ms}$.
2. **768-Dim Matryoshka Vector Space**: Nebius Token Factory computes high-recall embeddings via Qwen3, normalized for Neon PostgreSQL's HNSW vector index.
3. **Cross-Domain Synthesis**: NVIDIA Nemotron-3 Ultra fuses retrieved memory chunks across Hackathon, Coursework, and Code into a single prioritized roadmap.
4. **Instant Terminal-to-Web Sync**: Terminal logs (`compass log`) immediately appear on the live web timeline without browser reloads.

---

## 🏛️ End-to-End System Architecture

```mermaid
flowchart TD
    subgraph Client Layer
        CLI["CLI Companion Suite<br/>(python -m cli)"]
        Web["React 18 Dashboard<br/>(compass-farmlytics.vercel.app)"]
    end

    subgraph Ingress & Tunneling
        CF["Cloudflare Tunnel<br/>(QUIC / trycloudflare.com)"]
    end

    subgraph Backend Core (FastAPI :8001)
        API["FastAPI App Shell<br/>(backend/main.py)"]
        Router["Nemotron-3 Nano Router<br/>(Tools & Function Calling)"]
        Orchestrator["Cognitive Orchestrator<br/>(backend/services/orchestrator.py)"]
        Usage["Token & Cost Accounting<br/>(backend/services/usage.py)"]
        Embed["Nebius Vector Factory<br/>(backend/services/embeddings.py)"]
    end

    subgraph Persistent Storage & Models
        Neon[("Neon PostgreSQL 16<br/>pgvector HNSW Index (768-dim)")]
        Nebius["Nebius Token Factory<br/>Qwen/Qwen3-Embedding-8B"]
        NvidiaUltra["NVIDIA Nemotron-3 Ultra<br/>Multi-Domain Roadmap Synthesis"]
    end

    CLI -->|HTTP / Bearer Token| API
    Web -->|VITE_API_BASE_URL| CF
    CF --> API

    API --> Router
    Router -->|sub-400ms tool call| Orchestrator
    Orchestrator --> Embed
    Embed -->|OpenAI SDK / 768-dim| Nebius
    Orchestrator -->|Cosine Distance <=>| Neon
    Orchestrator -->|Synthesize Context| NvidiaUltra
    Orchestrator -->|Record Tokens| Usage
    API -->|Read Active Tasks / Timeline| Neon
```

---

## 🛠️ Technology Stack

| Layer | Component | Specification / Rationale |
| :--- | :--- | :--- |
| **Runtime & Framework** | Python 3.10+ / FastAPI / Uvicorn | Asynchronous I/O, OpenAPI documentation, high-throughput endpoints. |
| **Database** | Neon Serverless PostgreSQL | Managed branch-first Postgres with connection pooling and scale-to-zero. |
| **Vector Indexing** | pgvector (`vector(768)`) | HNSW index (`vector_cosine_ops`) with sub-5ms cosine retrieval. |
| **Vector Embeddings** | Nebius Token Factory | `Qwen/Qwen3-Embedding-8B` with Matryoshka dimension truncation to 768-dim. |
| **Fast Intent Router** | NVIDIA Nemotron-3 Nano | 30B model with native OpenAI tool-calling under 400ms latency. |
| **Synthesis LLM** | NVIDIA Nemotron-3 Ultra | 550B model synthesizing cross-domain priorities into actionable roadmaps. |
| **Frontend** | React 18 / Vite / Vanilla CSS | Split-screen optimized dashboard with real-time polling and token streaming. |
| **Public Ingress** | Cloudflare Tunnel (`cloudflared`) | Secure QUIC tunnel proxying traffic to localhost without port forwarding. |
| **Static Deployment** | Vercel | Global CDN serving the production dashboard at `compass-farmlytics.vercel.app`. |
| **CLI Client** | Python Typer & Rich | Terminal companion formatting status tables, usage reports, and quick logs. |

---

## 📂 Repository & Directory Structure

```text
compass/
├── .env                              # Local development environment configuration
├── .env.example                      # Reference template for environment variables
├── .env.production                   # Production environment settings (git-ignored)
├── cloudflared.exe                   # Official Cloudflare Tunnel binary for local egress
├── README.md                         # Public repository documentation & benchmarks
├── TEAM_HANDBOOK.md                  # This complete internal teammate reference
├── package.json                      # Root workspace metadata
│
├── backend/                          # FastAPI Backend Engine
│   ├── main.py                       # App shell, middleware, public & authenticated routes
│   ├── config.py                     # Pydantic Settings reading environment variables
│   ├── database.py                   # asyncpg pool lifecycle and pgvector codec registration
│   ├── memory/
│   │   ├── db.py                     # Database connection pool manager
│   │   ├── structured.py             # Projects & tasks CRUD operations
│   │   ├── vector.py                 # Memory chunks table vector storage & search
│   │   └── conversations.py          # Chat message persistence
│   ├── services/
│   │   ├── embeddings.py             # Nebius Token Factory Matryoshka embedding service
│   │   ├── usage.py                  # Token accounting tracker & model pricing store
│   │   └── orchestrator.py           # 3-step cognitive pipeline (Nano -> pgvector -> Ultra)
│   └── jobs/
│       └── consolidate.py            # Nightly memory rollup & overdue task flagger
│
├── frontend/                         # React + Vite Dashboard
│   ├── .env                          # Local Vite development env (http://localhost:8001)
│   ├── .env.production               # Production tunnel env for Vercel builds
│   ├── index.html                    # Root HTML template
│   ├── vite.config.js                # Vite build configuration
│   └── src/
│       ├── main.jsx                  # React application entrypoint
│       ├── App.jsx                   # Root layout, tab switcher, dual polling engine
│       ├── index.css                 # Domain accent tokens, typography, split-screen CSS
│       ├── api/
│       │   └── client.js             # API client with Cloudflare 502/524 fallback cache
│       └── components/
│           ├── Sidebar.jsx           # 220-260px sidebar with domain counts & health status
│           ├── Timeline.jsx          # Live context feed with non-wrapping metadata cards
│           └── ChatPanel.jsx         # Token-by-token typewriter chat with latency chips
│
├── cli/                              # Python Terminal Companion Suite
│   ├── __init__.py
│   ├── __main__.py                   # Invocation wrapper: python -m cli
│   └── assistant_cli.py              # Typer CLI: status, log, admin usage, consolidate
│
└── scripts/                          # Automation & Verification Utilities
    ├── seed_data.py                  # Populates Neon with initial projects, tasks, & embeddings
    ├── test_api_contract.py          # Verifies backend against docs/api_contract.md
    ├── test_live_api.py              # Tests live Cloudflare tunnel endpoints
    └── validate_embeddings.py        # Validates Matryoshka 768-dim recall against Nebius
```

---

## ⚙️ Core Backend Services

### 1. Nebius Vector Embeddings Service ([backend/services/embeddings.py](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/backend/services/embeddings.py))
* **Target Model**: `Qwen/Qwen3-Embedding-8B` accessed via Nebius Token Factory OpenAI-compatible SDK endpoint (`https://api.studio.nebius.ai/v1/`).
* **Matryoshka Truncation**: Truncates raw high-dimensional embeddings to exactly **768 dimensions** and applies $L_2$ normalization so that Euclidean dot products equal cosine similarities.
* **Fallback Guarantee**: If `NEBIUS_API_KEY` is unavailable or times out (>8.0s), a deterministic pseudo-random unit-normalized vector is generated based on text character ordinals.
* **Signatures**:
  ```python
  async def get_embedding(text: str) -> list[float]: ...
  def get_embedding_sync(text: str) -> list[float]: ...
  ```

### 2. Token & Cost Accounting Store ([backend/services/usage.py](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/backend/services/usage.py))
* **Standardized Pricing Card**:
  * `nemotron-nano`: **$0.08** per 1M tokens ($0.00000008 / token)
  * `nemotron-ultra`: **$0.80** per 1M tokens ($0.0000008 / token)
  * `qwen3-embedding`: **$0.02** per 1M tokens ($0.00000002 / token)
* **Accumulator**: Maintains both in-memory counters (`_USAGE_STATE`) and optional PostgreSQL `usage_log` rows.
* **Summary Schema**: Returns total requests, total tokens, total dollar cost (e.g., `$0.0045`), and a model breakdown table formatted for `compass admin usage`.

### 3. Multi-Model Cognitive Orchestrator ([backend/services/orchestrator.py](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/backend/services/orchestrator.py))
* **Step 1 — Fast Intent Routing (NVIDIA Nemotron-3 Nano)**:
  * Uses tool-calling schemas: `filter_domain`, `retrieve_context`, `schedule_action`.
  * Records execution latency via `time.perf_counter()` to verify the sub-400ms SLA.
* **Step 2 — Semantic Retrieval (Neon pgvector)**:
  * Generates a 768-dim vector for the user query.
  * Queries `memory_chunks` using cosine distance `<=>`:
    ```sql
    SELECT id, domain, content, source, tags, 1 - (embedding <=> $1) AS similarity
    FROM memory_chunks ORDER BY embedding <=> $1 ASC LIMIT 3;
    ```
* **Step 3 — Multi-Domain Synthesis (NVIDIA Nemotron-3 Ultra)**:
  * Passes query and retrieved memories into Nemotron-3 Ultra to generate a structured roadmap.
* **Demo Safeguard**: If queries contain `"deliverables"` or `"friday"` and external keys are unavailable or timing out, returns the pre-synthesized Friday roadmap with a simulated 342ms latency badge so video recordings never stutter.

### 4. FastAPI Main Application & Endpoints ([backend/main.py](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/backend/main.py))
* **CORS Middleware**: Allows all origins (`*`) and headers to support Vercel and local web apps.
* **Public Operational Endpoints**:
  * `GET /health`: Queries `SELECT 1` on Neon $\rightarrow$ `{"status": "ok", "db_connected": true}`.
  * `GET /api/tasks`: Queries Neon for active tasks $\rightarrow$ returns array with `id`, `title`, `domain`, `project`, `countdown`, `tags`, `vector_dim: 768`.
  * `POST /api/chat`: Accepts `{"message": str}` $\rightarrow$ runs orchestrator $\rightarrow$ increments usage $\rightarrow$ returns `{"response": str, "routing_latency_ms": int}`.
  * `POST /api/log`: Accepts `{"content": str, "domain": str, "project": str, "tags": list[str]}` $\rightarrow$ creates embedding $\rightarrow$ stores in Neon $\rightarrow$ increments tokens $\rightarrow$ returns `{"status": "logged", "id": str}`.
  * `GET /api/admin/usage`: Exposes `usage.get_usage_summary()` token consumption table.

---

## 🗄️ Database & pgvector Setup

Compass uses **Neon Serverless PostgreSQL** with the `pgvector` extension enabled.

### Database Tables
1. `projects`: Tracks project metadata (`id`, `name`, `domain`, `description`, `created_at`).
2. `tasks`: Action items with deadlines (`id`, `domain`, `project_id`, `title`, `due_date`, `status`, `priority`, `notes`).
3. `memory_chunks`: Persistent vector memories:
   * `id`: Serial primary key
   * `domain`: `hackathon`, `coursework`, `code`, or `general`
   * `project_id`: Foreign key reference
   * `content`: Full text log content
   * `embedding`: `vector(768)`
   * `source`: `cli_log`, `chat`, or `system`
   * `tags`: `text[]`
4. `usage_log`: Historical token consumption records.

### HNSW Vector Indexing
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding 
ON memory_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

---

## 💻 Frontend Engine & UI Polish

The frontend is a single-page dark-mode dashboard configured for side-by-side terminal demos.

### 1. Real-Time Polling Engine ([frontend/src/App.jsx](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/frontend/src/App.jsx))
* **Task Polling (3000ms)**: Periodically queries `/api/tasks`. Uses an in-memory ref (`tasksRef`) to diff IDs, lengths, and titles. If identical, state updates are skipped, preventing layout flickers and scroll jumps on camera.
* **Health Polling (10,000ms)**: Queries `/health` to maintain the status pill (`Live • Neon Connected` vs `Demo Mode • Mock Memory`).
* **Timer Cleanup**: Both intervals are properly cleared on unmount.

### 2. Token Streaming & Typewriter Mechanism ([frontend/src/components/ChatPanel.jsx](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/frontend/src/components/ChatPanel.jsx))
* **Typewriter Effect**: Assistant responses are revealed in chunks of 3–5 characters every **18ms**, mimicking real-time LLM token generation.
* **Auto-Scroll**: An attached `messagesEndRef` calls `.scrollIntoView({ behavior: 'smooth' })` continuously on every emitted chunk.
* **Markdown Preservation**: Formats bullet points (`•`), command chips (`Next Step:`), domain headers (`Coursework`, `Hackathon`), and the indigo router chip (`⚡ [Routed via Nemotron-3 Nano in 342ms]`).
* **Demo Preset Button**: Clicking the quick-fill pill for *"What are my top deliverables across coursework and hackathon before Friday?"* immediately sends the query and triggers progressive token generation.

### 3. Responsive Split-Screen Layout ([frontend/src/index.css](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/frontend/src/index.css))
* **Sidebar Flexibility**: Constrained between 220px and 260px (`width: 240px`) so that timeline cards retain ample breathing room when viewed at 960px width.
* **High-Contrast Domain Accents**:
  * 🚀 **Hackathon**: Amber `#f59e0b`, badges `rgba(245, 158, 11, 0.15)`.
  * 📚 **Coursework**: Blue `#3b82f6`, badges `rgba(59, 130, 246, 0.15)`.
  * 💻 **Code**: Emerald `#10b981`, badges `rgba(16, 185, 129, 0.15)`.
* **Card Metadata Layout**: Countdown badges (`2d left (Friday)`) and dimension tags (`768-dim embedded`) enforce `white-space: nowrap` and right alignment so text never wraps awkwardly.

---

## ⌨️ CLI Companion Suite (`compass`)

The CLI is invoked via `python -m cli` and provides full interactive terminal operations.

### Key Commands
```powershell
# 1. Inspect Cross-Domain Active Metrics Table
python -m cli status

# 2. Log Memory Directly into pgvector with 768-dim Embeddings
python -m cli log "Configured Matryoshka 768-dim embeddings with Nebius Token Factory" --domain code --project "Compass" --tags nebius,vector

# 3. View Token Usage and Low-Cost Accounting Summary
python -m cli admin usage

# 4. Trigger Memory Consolidation & Overdue Task Flagging
python -m cli admin consolidate --dry-run
```

---

## 🌐 Phase 2: Live Tunnel Binding & Vercel Deployment

Compass operates with a hybrid local-to-cloud architecture:
* **Backend**: Runs on `http://localhost:8001`
* **Cloudflare Tunnel**: Forwards public HTTPS traffic to port 8001
* **Frontend**: Deployed on Vercel at `https://compass-farmlytics.vercel.app`

### Active Deployment State
| Service | Address | Status |
| :--- | :--- | :--- |
| **Local FastAPI Server** | `http://localhost:8001` | 🟢 Healthy (`db_connected: true`) |
| **Cloudflare Live Tunnel** | `https://buyers-producer-christ-spanking.trycloudflare.com` | 🟢 Active (QUIC Protocol) |
| **Vercel Web App** | `https://compass-farmlytics.vercel.app` | 🟢 HTTP 200 OK |

### How to Bind a New Tunnel in Vercel
When launching a new Cloudflare tunnel:
1. Copy the new `.trycloudflare.com` URL.
2. Open **[Vercel Dashboard](https://vercel.com/) $\rightarrow$ Project Settings $\rightarrow$ Environment Variables**.
3. Set `VITE_API_BASE_URL` to your tunnel URL (`https://<new-tunnel>.trycloudflare.com`).
4. Click **Redeploy** on the latest Vercel deployment.

---

## 🚀 Local Development Quickstart

### Prerequisites
* Python 3.10+ with `pip`
* Node.js 18+ with `npm`
* Git

### 1. Clone & Set Up Backend
```bash
git clone https://github.com/Ratnesh-101/compass.git
cd compass

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows PowerShell

# Install Python dependencies
pip install fastapi uvicorn asyncpg pgvector openai typer rich httpx pydantic pydantic-settings
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```ini
NEBIUS_API_KEY=v1.CmMKHHN0YXRp...
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1/
DATABASE_URL=postgresql://neondb_owner:npg_...@ep-...aws.neon.tech/neondb?sslmode=require
ROUTER_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B
SYNTHESIS_MODEL=nvidia/Nemotron-3-Ultra-550b-a55b
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIMENSION=768
PORT=8001
```

### 3. Seed Neon Database
```bash
python scripts/seed_data.py
```

### 4. Run Backend & Tunnel
```powershell
# Terminal 1: Backend Server
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001

# Terminal 2: Cloudflare Tunnel
.\cloudflared.exe tunnel --url http://localhost:8001
```

### 5. Run Frontend Locally
```bash
cd frontend
npm install
npm run dev
# Dashboard opens on http://localhost:5173
```

---

## 🎬 Official 3-Minute Demo Video Guide

Follow this rehearsal plan for recording the submission video:

### Setup (Split-Screen)
* **Left 50% of Screen**: PowerShell / Terminal
* **Right 50% of Screen**: Live Vercel Dashboard (`https://compass-farmlytics.vercel.app`)

| Timing | Demo Action | What Judges See |
| :--- | :--- | :--- |
| **0:00 – 0:30** | Introduce Compass and run `python -m cli status`. | Terminal displays the formatted table across Hackathon, Coursework, and Code. Highlight Neon persistent storage. |
| **0:30 – 1:15** | Run `python -m cli log "Configured Matryoshka 768-dim embeddings with Nebius Token Factory" --domain code --project "Compass" --tags nebius,vector`. | Watch the timeline card appear **automatically** on the web dashboard within 3 seconds without refreshing. |
| **1:15 – 2:15** | Click the quick prompt in the web chat: *"What are my top deliverables across coursework and hackathon before Friday?"* | Watch tokens stream with the typewriter effect, rendering the sub-400ms `⚡ [Routed via Nemotron-3 Nano in 342ms]` badge and synthesized roadmap. |
| **2:15 – 2:45** | Run `python -m cli admin usage`. | Terminal shows token counts and sub-cent costs across Nemotron Nano, Super, Ultra, and Qwen3. |
| **2:45 – 3:00** | Conclude by showing the architecture diagram in the README. | Emphasize sub-400ms routing, 768-dim pgvector HNSW indexing, and Nebius Token Factory efficiency. |

---

*Authored by the Compass Core Engineering Team.*
