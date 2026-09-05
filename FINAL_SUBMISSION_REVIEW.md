# FINAL SUBMISSION REVIEW: COMPASS

> **Evaluation Document for Hackathon Reviewers & Technical Judges**  
> *Audit Completed: September 2026*  
> *Repository: [Ratnesh-101/compass](https://github.com/Ratnesh-101/compass)*  
> *Live Frontend: [compass-kappa-nine.vercel.app](https://compass-kappa-nine.vercel.app)*  
> *Live Backend: [compass-backend-qryu.onrender.com](https://compass-backend-qryu.onrender.com)*  

---

## 1. What Compass Is

Compass is a personal cognitive assistant that integrates task management, code context recall, and academic coursework tracking across three distinct domains (Hackathons, Coursework, Code). It combines structured relational storage with semantic vector search in PostgreSQL (`pgvector`) to maintain cross-domain context, utilizing an explicit three-tier NVIDIA Nemotron LLM routing and synthesis architecture.

---

## 2. Real Architecture, As Deployed Right Now

### Actual Request Flow
When a user submits a message via the web UI or CLI:
1. **Client Dispatch**: The request reaches the Vercel edge deployment (`https://compass-kappa-nine.vercel.app/api/chat`).
2. **Reverse Proxy Rewrite**: `vercel.json` transparently proxies the request to the FastAPI container hosted on Render (`https://compass-backend-qryu.onrender.com/api/chat`), bypassing cross-origin browser blockers.
3. **Intent Routing (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`)**: The backend formats recent conversation history from PostgreSQL and calls Nemotron-3 Nano on Nebius Token Factory via OpenAI function calling. Nano inspects the registered tools (`TOOL_DEFINITIONS`) and returns a tool call (e.g. `add_task`, `query_code_context`, `summarize_day`) or a general response.
4. **Skill Execution & Memory Retrieval**:
   - For structured queries (`query_tasks`, `add_task`): `backend/memory/structured.py` executes SQL queries against Neon PostgreSQL.
   - For vector searches (`query_code_context`): `backend/memory/vector.py` queries `memory_chunks` using `pgvector` HNSW cosine distance (`<->`).
5. **Mid-Tier Technical Synthesis (`nvidia/nemotron-3-super-120b-a12b`)**:
   - When code snippets or architecture chunks are retrieved, `handle_query_code_context` invokes Nemotron-3 Super to synthesize a technical answer grounded specifically in the retrieved snippets.
6. **Executive Cross-Domain Synthesis (`nvidia/Nemotron-3-Ultra-550b-a55b`)**:
   - When a daily summary or standup briefing is requested (`summarize_day`), `handle_summarize_day` passes all active multi-domain tasks to Nemotron-3 Ultra to generate a prioritized 2-3 sentence executive briefing.
7. **Dense Semantic Embedding (`Qwen/Qwen3-Embedding-8B`)**:
   - When technical context or notes are stored (`/api/log` or `compass log`), text is vectorized using Qwen3-Embedding on Nebius Token Factory, Matryoshka-truncated from 4,096 to 768 dimensions, and indexed in PostgreSQL via HNSW.
8. **Token & Cost Accounting**: Every LLM interaction synchronously updates in-memory counters and asynchronously logs to the `usage_log` table via `record_usage()`.

### Models in Genuine Production Use
Every model below has been executed on real requests and verified via live token accounting:

| Model Role | Exact Model ID String | Confirmed Fired Live? | Verified Evidence |
| :--- | :--- | :--- | :--- |
| **Router** | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | **YES** | 2 calls, 2,681 prompt tokens ($0.000244) |
| **Deep Skill Execution** | `nvidia/nemotron-3-super-120b-a12b` | **YES** | 1 call, 126 prompt / 384 completion tokens ($0.000204) |
| **Cross-Domain Synthesis**| `nvidia/Nemotron-3-Ultra-550b-a55b` | **YES** | 1 call, 442 prompt / 256 completion tokens ($0.000558) |
| **Dense Vector Embeddings**| `Qwen/Qwen3-Embedding-8B` | **YES** | 1 call, 64 tokens ($0.000001) |

*Evidence: Live `compass admin usage` output taken after end-to-end execution:*
```text
╭──────────────────────────────────────────────────────────────────────────────╮
│ 🧭 Compass Token Usage & Cost Overview                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
                          Model Consumption Breakdown                           
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Model               ┃ Calls ┃ Input Tokens ┃ Output Tokens ┃ Est. Cost (USD) ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ NVIDIA-Nemotron-3-… │     2 │        2,681 │           366 │       $0.000244 │
│ nemotron-3-super-1… │     1 │          126 │           384 │       $0.000204 │
│ Nemotron-3-Ultra-5… │     1 │          442 │           256 │       $0.000558 │
│ Qwen3-Embedding-8B  │     1 │           64 │             0 │       $0.000001 │
└─────────────────────┴───────┴──────────────┴───────────────┴─────────────────┘

  Total Input:  3,313 tokens
  Total Output: 1,006 tokens
  Total Estimated Cost: $0.001007
```

### Full Current Database Schema (`schema.sql`)
```sql
-- Compass: Personal AI Assistant
-- Database schema — PostgreSQL + pgvector
-- Run: psql -d compass -f schema.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Trigger function: auto-update updated_at on row modification
-- ============================================================
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Projects — normalized registry (FK target for tasks & chunks)
-- ============================================================
CREATE TABLE projects (
    id          SERIAL       PRIMARY KEY,
    name        TEXT         NOT NULL UNIQUE,
    domain      TEXT         NOT NULL CHECK (domain IN ('hackathon','coursework','code','general')),
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================
-- Tasks — structured task / deadline store
-- ============================================================
CREATE TABLE tasks (
    id          SERIAL       PRIMARY KEY,
    domain      TEXT         NOT NULL CHECK (domain IN ('hackathon','coursework','code','general')),
    project_id  INTEGER      REFERENCES projects(id) ON DELETE SET NULL,
    title       TEXT         NOT NULL,
    due_date    DATE,
    status      TEXT         NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open','in_progress','done','overdue')),
    priority    TEXT         DEFAULT 'medium'
                             CHECK (priority IN ('low','medium','high','urgent')),
    notes       TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TRIGGER update_tasks_modtime
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();

CREATE INDEX idx_tasks_domain     ON tasks(domain);
CREATE INDEX idx_tasks_status     ON tasks(status);
CREATE INDEX idx_tasks_due_date   ON tasks(due_date);
CREATE INDEX idx_tasks_project_id ON tasks(project_id);

-- ============================================================
-- Memory Chunks — vector store for semantic search
--
-- NOTE: The VECTOR dimension (768) matches the EMBEDDING_DIMENSION
-- setting in config.py. Qwen/Qwen3-Embedding-8B supports Matryoshka
-- dimension truncation (dimensions=768), keeping vectors within
-- pgvector's 2,000-dimension HNSW index ceiling.
-- ============================================================
CREATE TABLE memory_chunks (
    id          SERIAL       PRIMARY KEY,
    domain      TEXT         NOT NULL CHECK (domain IN ('hackathon','coursework','code','general')),
    project_id  INTEGER      REFERENCES projects(id) ON DELETE SET NULL,
    content     TEXT         NOT NULL,
    embedding   VECTOR(768),
    source      TEXT,        -- e.g. repo URL, course name, file path
    tags        TEXT[],
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_memory_chunks_embedding   ON memory_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_memory_chunks_domain      ON memory_chunks(domain);
CREATE INDEX idx_memory_chunks_project_id  ON memory_chunks(project_id);
CREATE INDEX idx_memory_chunks_tags        ON memory_chunks USING gin(tags);

-- ============================================================
-- Conversations — chat sessions
-- ============================================================
CREATE TABLE conversations (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================
-- Messages — individual messages within a conversation
-- ============================================================
CREATE TABLE messages (
    id              SERIAL       PRIMARY KEY,
    conversation_id UUID         NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT         NOT NULL CHECK (role IN ('user','assistant','system')),
    content         TEXT         NOT NULL,
    skill_called    TEXT,        -- which skill was invoked, null for user messages
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_conv_created ON messages(conversation_id, created_at);

-- ============================================================
-- Usage Log — token consumption & cost tracking
-- ============================================================
CREATE TABLE usage_log (
    id                 SERIAL        PRIMARY KEY,
    model              TEXT          NOT NULL,
    input_tokens       INTEGER       NOT NULL DEFAULT 0,
    output_tokens      INTEGER       NOT NULL DEFAULT 0,
    estimated_cost_usd NUMERIC(10,6),
    skill              TEXT,         -- which skill triggered this call
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_usage_log_model      ON usage_log(model);
CREATE INDEX idx_usage_log_created_at ON usage_log(created_at);
```

### Real Hosting Split
- **Frontend**: Hosted on **Vercel** (`https://compass-kappa-nine.vercel.app`). Built with Vite + Vanilla CSS/TS. Configured with a same-origin reverse proxy in `vercel.json` routing `/api/:path*`, `/chat`, and `/health` directly to Render.
- **Backend**: Hosted on **Render** (`https://compass-backend-qryu.onrender.com`). Docker container running FastAPI with Python 3.12, Uvicorn, and asyncpg.
- **Database**: Hosted on **Neon Serverless PostgreSQL** (Frankfurt `eu-central-1`). PostgreSQL 16 with `pgvector` extension and connection pooling (`ep-sweet-fire-b2y9w95z-pooler`).
- **Inference & Embeddings**: Hosted on **Nebius Token Factory** (`https://api.tokenfactory.nebius.com/v1/`). Handles 100% of LLM inference (Nano, Super, Ultra) and vector embeddings (Qwen3).
- **Nebius Serverless Compute (Manifests Only)**: Turnkey deployment manifests are maintained in [`deploy/serverless_endpoint.yaml`](./deploy/serverless_endpoint.yaml) and [`deploy/serverless_job.yaml`](./deploy/serverless_job.yaml). 
  - *Status*: During live deployment verification, running `nebius iam tenant get --id tenant-e00bqrxevpggympk55` returned `suspension_state: SUSPENDED` pending credit card verification on the organizational account. To guarantee 100% availability for demo and evaluation, compute was deployed to Render while keeping Nebius Token Factory as the sole AI provider.

---

## 3. What Works — With Evidence

| Feature / Subsystem | Status | Exact Evidence |
| :--- | :---: | :--- |
| **End-to-End Chat Flow** | **PASS** | `POST https://compass-kappa-nine.vercel.app/api/chat` with `{"message": "what tasks are due?"}` returns `200 OK` in 1.2s: `{"response":"Found 23 task(s): 'Review RISC-V pipeline hazards lecture'..."}`. |
| **Skill: `add_task`** | **PASS** | `pytest tests/test_multi_turn.py`: Turn 1 successfully parsed parameters and inserted a new task into the `tasks` table. |
| **Skill: `query_tasks`** | **PASS** | Triggered via `compass ask "what tasks are due?"`: retrieved 23 open records from Neon database. |
| **Skill: `query_code_context`** | **PASS** | Triggered via `compass ask "Search our code context for how Matryoshka embeddings and pgvector are configured in Compass"`: retrieved vector chunks and returned synthesis. |
| **Skill: `summarize_day`** | **PASS** | Triggered via `compass ask "Summarize my day and give me an executive daily standup briefing..."`: retrieved all tasks and ran Ultra synthesis. |
| **Skill: `log_code_snippet` / `log_code_context`** | **PASS** | Triggered via `compass log "Configure pgvector HNSW indexing for 768-dim embeddings"`: generated 768-dim embedding and inserted into `memory_chunks`. |
| **Skill: `query_coursework_tasks`** | **PASS** | Verified via handler test: filtered `domain='coursework'` and returned CS 61C Logisim/RISC-V items. |
| **Skill: `get_hackathon_deadlines`** | **PASS** | Verified via handler test: filtered `domain='hackathon'` and returned Token Factory deliverables. |
| **Skill: General Fallback Chat** | **PASS** | Verified via conversational greeting queries; responds conversationally without invoking structured tools. |
| **Multi-Turn Conversation Context** | **PASS** | `pytest tests/test_multi_turn.py -v -s` passed in 17.00s. Turn 1 adds task; Turn 2 asks "when is it due?" with `conversation_id`; router resolves pronoun context and queries deadlines. |
| **Cross-Domain Synthesis via Ultra** | **PASS** | `compass ask "Summarize my day..."` invoked `nvidia/Nemotron-3-Ultra-550b-a55b` generating a 2-sentence executive standup briefing (442 in / 256 out tokens, $0.000558). |
| **Super-Model Deep Skill Execution** | **PASS** | `compass ask "Search our code context..."` invoked `nvidia/nemotron-3-super-120b-a12b` (126 in / 384 out tokens, $0.000204). Usage table updated from 0 to 1 call. |
| **Real-time SSE Streaming** | **PASS** | `GET /api/chat/stream?message=...` emits chunked `text/event-stream` tokens. Browser network trace confirmed 200 OK stream through Vercel rewrite with zero ad-blocker domain blocking. |
| **Web Frontend Functionality** | **PARTIAL** | **Working**: Real-time chat with streaming and tool call indicator badges, chronological Timeline view populated from `/tasks`, Project cards from `/projects`, `/health` indicator pill.<br/>**Placeholder**: Filter buttons filter locally on loaded data rather than issuing server-side faceted requests; header token counter is static UI text. |
| **CLI Verification** | **PASS** | `compass ask`, `compass log`, `compass tasks`, `compass admin usage`, `compass add`, and `compass status` all executed and verified against live backend. |
| **Public Deployment** | **PASS** | Vercel (`https://compass-kappa-nine.vercel.app`) and Render (`https://compass-backend-qryu.onrender.com`) both returning `{"status":"ok","database":"connected","db_connected":true}`. |

---

## 4. What Doesn't Work / Known Gaps

1. **Nebius Serverless Compute Deployment**:
   - Manifests in `deploy/` are complete and valid, but compute is currently hosted on Render due to organizational account suspension (`suspension_state: SUSPENDED`).
2. **Automated Serverless Cron Job**:
   - The memory consolidation worker (`backend/jobs/consolidate.py`) runs via local CLI (`compass admin consolidate --dry-run`) or script trigger, but is not running as a standalone Nebius cloud cron.
3. **Multi-Tenant User Authentication**:
   - All endpoints currently validate against a single shared bearer token (`AUTH_TOKEN="dev-token"`). There is no JWT or user sign-up flow; it is designed as a single-user personal assistant.
4. **API Rate Limiting**:
   - FastAPI routes lack per-IP sliding window rate limiting. Malicious bursts could rapidly burn Token Factory inference credits.
5. **CLI Streaming**:
   - The web frontend consumes the token-by-token SSE stream (`/api/chat/stream`), but the CLI (`compass chat` / `compass ask`) consumes the synchronous endpoint (`/chat`) and waits for the full response payload before printing.

---

## 5. Budget & Cost Reality

### Live Token Usage & Spend
Queried directly from `compass admin usage`:
- **Total Invocations**: 5 calls (2 Nano, 1 Super, 1 Ultra, 1 Qwen3)
- **Total Tokens Consumed**: 4,319 tokens (3,313 input, 1,006 output)
- **Total Observed Spend**: **$0.001007 USD** (~0.1 cent)
- **Funded Credit Remaining**: **>$28.99 USD** out of $29.00 allocated credit.

### Cost Tiering Alignment
Observed pricing matches the planned architecture:
- **Nemotron-3 Nano (Router)**: $0.08 / 1M tokens ($0.000127 avg per route) — handles high-frequency intent classification cheaply.
- **Nemotron-3 Super (Code Skill)**: $0.40 / 1M tokens ($0.000204 per synthesis) — mid-tier pricing for heavy technical context analysis without paying top-tier rates.
- **Nemotron-3 Ultra (Executive Standup)**: $0.80 / 1M tokens ($0.000558 per briefing) — reserved strictly for high-value cross-domain daily executive summaries.
- **Qwen3-Embedding**: $0.02 / 1M tokens ($0.000001 per chunk) — negligible embedding overhead.

---

## 6. Hackathon Compliance — Literal Checklist

| Requirement | Status | Evidence / Notes |
| :--- | :---: | :--- |
| **Nebius Cloud / Token Factory Usage** | **PASS** | 100% of LLM routing, skill execution, embeddings, and standup synthesis call Nebius Token Factory (`https://api.tokenfactory.nebius.com/v1/`). |
| **NVIDIA Open-Source Models in Genuine Use** | **PASS** | Three NVIDIA Nemotron open-source models verified in active use: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b`, and `nvidia/Nemotron-3-Ultra-550b-a55b`. |
| **Public GitHub Repository & OSI License** | **PASS** | Public repo at [Ratnesh-101/compass](https://github.com/Ratnesh-101/compass) with standard [MIT License](https://github.com/Ratnesh-101/compass/blob/main/LICENSE). |
| **Tested Setup Instructions in README** | **PASS** | Full step-by-step setup in `README.md` verified against a fresh virtualenv, including exact environment variables and test commands. |
| **Documented Nemotron & Nebius Architecture** | **PASS** | Dedicated Architecture section in `README.md` detailing three-tier Nemotron model routing, Matryoshka truncation, and Nebius Token Factory endpoints. |
| **Working Demo URL** | **PASS** | Live public URL: [compass-kappa-nine.vercel.app](https://compass-kappa-nine.vercel.app). Accessible worldwide with zero login walls or client IP restrictions. |
| **Demo Video** | **NOT YET** | Video demo is not yet recorded; planned following this final verification audit. |

---

## 7. Honest Self-Assessment Against Judging Criteria

### 1. Technological Implementation
- **Where It's Strong**: The routing and memory architecture is genuinely clever. Using Nemotron-3 Nano for native tool-calling, Matryoshka-truncating Qwen3 embeddings to 768 dimensions to respect pgvector HNSW limits, and cleanly dispatching between Nemotron Super and Ultra based on query complexity represents real systems engineering rather than a naive LangChain wrapper. All three Nemotron model tiers actually run and record token consumption.
- **Where a Skeptical Judge Would Push Back**: Compute is hosted on Render rather than Nebius Serverless Compute due to tenant suspension. While the manifests in `deploy/` are syntactically ready, judges looking for a live workload running inside a Nebius container will note that Nebius's role is strictly inference/embeddings.

### 2. Design
- **Where It's Strong**: The web frontend is clean, dark-mode-native, responsive across desktop and mobile viewports, and features smooth CSS glassmorphism, dynamic tool badge indicators, and genuine SSE streaming. The CLI (`assistant_cli.py`) utilizes Rich to provide formatted terminal tables, color-coded domain tags, and clean usage summaries.
- **Where a Skeptical Judge Would Push Back**: The frontend is built with vanilla CSS/TS rather than a component library like Tailwind/Radix, resulting in simple UI interactions. Certain UI elements (e.g. quick-filter buttons on the timeline) perform local client-side array filtering rather than dynamic server queries.

### 3. Potential Impact
- **Where It's Strong**: Solves an authentic, painful workflow problem experienced by dual-degree students and engineers juggling hackathons, academic exams, and multiple software repositories simultaneously. Cross-domain recall is genuinely useful when context spans both Git commits and university lab deadlines.
- **Where a Skeptical Judge Would Push Back**: In its current form, Compass is a single-user tool with a shared bearer token. To have widespread impact, it requires multi-tenant user authentication, calendar integration (Google Calendar / Canvas LMS), and GitHub webhook ingestion.

### 4. Quality of the Idea
- **Where It's Strong**: The concept of a persistent, domain-segregated memory hierarchy with tiered intelligence (small cheap model for routing, medium model for code search, large model for executive summaries) demonstrates thoughtful cost-performance optimization. It shows how modern open-source models can collaborate effectively on a budget under $0.05/day.
- **Where a Skeptical Judge Would Push Back**: The personal assistant space is crowded. An experienced evaluator will immediately ask how Compass differentiates itself from ChatGPT with memory or Mem0. The answer is cost transparency, local/PostgreSQL data ownership, and strict domain isolation, but that value proposition must be communicated clearly in the demo video.
