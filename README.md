# <img src="frontend/public/logo.png" alt="Compass logo" width="28" height="28" valign="middle" /> Compass

> **Your one AI that remembers every hackathon, repo, and deadline — so you don't have to.**

[![MIT License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.142%2B-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![Vite 8](https://img.shields.io/badge/Vite-8-646CFF.svg?logo=vite&logoColor=white)](https://vitejs.dev/)
[![CI](https://github.com/Ratnesh-101/compass/actions/workflows/ci.yml/badge.svg)](https://github.com/Ratnesh-101/compass/actions/workflows/ci.yml)
[![NVIDIA Nemotron-3](https://img.shields.io/badge/NVIDIA-Nemotron--3-76B900.svg?logo=nvidia&logoColor=white)](https://build.nvidia.com/)
[![Neon pgvector](https://img.shields.io/badge/Neon-pgvector%20HNSW-336791.svg?logo=postgresql&logoColor=white)](https://neon.tech/)
[![Tavily](https://img.shields.io/badge/Tavily-Web%20Intelligence-4A90E2.svg)](https://tavily.com/)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-compass--farmlytics.vercel.app-success.svg?logo=vercel&logoColor=white)](https://compass-farmlytics.vercel.app)

Compass is a persistent-memory AI copilot that bridges your tasks, hackathon deadlines, coursework, code context, and career pipeline into one unified, agent-driven workspace. Instead of serving as a stateless chat prompt, Compass reasons across all your work domains, queries live web sources, validates candidate eligibility, tailors verifiable resumes, and halts at strict human confirmation gates before mutating data or submitting applications.

## 🌟 Winning Intelligence Features

Compass goes beyond simple AI integration to provide a high-fidelity career engine:

- **Strict Eligibility Mapping:** Rigorously matches candidate skills, education, and graduation timelines against job requirements with deterministic rule-based explainability.
- **Actionable Gap Analysis:** Transforms "Ineligible" results into a growth roadmap, identifying specific missing qualifications and suggesting real-world bridge actions.
- **Company Intelligence Briefs:** Researches target employers via Tavily with 24-hour caching and dedicated sub-budgets to generate "War Room" briefs highlighting technical pain points.
- **ATS Parsing Simulation (Estimate):** Simulates machine-parsing of resumes to estimate potential keyword gaps and formatting concerns.
- **Predictive Hiring Radar:** Leverages historical cycle data to forecast upcoming internship windows for top-tier companies.

**[🌐 Live Web Application](https://compass-farmlytics.vercel.app)** · **[🔌 API Health Endpoint](https://compass-backend-qryu-vcfv.onrender.com/health)** · **[🎥 Demo Video Walkthrough Script](docs/demo_script.md)**

> **Note for Judges**: Please evaluate using the live deployment at [compass-farmlytics.vercel.app](https://compass-farmlytics.vercel.app) with the live backend at [compass-backend-qryu-vcfv.onrender.com](https://compass-backend-qryu-vcfv.onrender.com). The live environment runs with full Nebius, Neon, and Tavily integrations. Local setup requires configured API keys and PostgreSQL with pgvector.

---

## Why Compass?

Modern developers and students work across fragmented environments that do not communicate with each other:

| Environment | What It Handles | What It Misses |
| :--- | :--- | :--- |
| **Standard LLM Chat** | Ephemeral question answering | Zero persistence; forgotten context on every new session |
| **Notion / Linear** | Static task lists & tickets | Incapable of reasoning across domains, estimating cognitive feasibility, or executing multi-step agent actions |
| **Google Calendar** | Hourly time slots | Unaware of code context, technical backlog, or real task complexity |
| **Job Boards / ATS** | Public listings & applications | Detached from candidate verified skills, factual projects, and academic eligibility |

**Compass connects these contexts through persistent memory, model routing, and an autonomous agent.** When you ask *"What should I focus on tonight given my hackathon submission on Friday and my pending coursework?"*, Compass queries your structured database, retrieves relevant code and coursework notes via semantic search tools, calculates calendar feasibility, and produces an actionable plan — asking for your approval before modifying any record.

---

## System Architecture

Compass pairs a high-performance FastAPI backend with a React 19 frontend, persistent Neon PostgreSQL database with `pgvector`, a cost-optimized 3-tier model hierarchy on Nebius Token Factory, and Tavily real-time web intelligence:

```mermaid
graph TD
    User["User (React 19 Web App / Typer Terminal CLI)"] -->|Vercel Edge HMAC Proxy| Router["FastAPI Backend (Nebius Nemotron-3 Nano 30B Router)"]
    
    Router -->|Conversational Tasks| ReAct["Autonomous ReAct Agent Loop"]
    Router -->|Domain Specialists| Specialists["Specialist Team (Coursework, Research, Calendar, Memory)"]
    Router -->|Career Copilot| Career["Career Copilot Engine (Radar, Resume Studio, Application Center)"]

    ReAct -->|Multi-Step Reasoning| Super["Nemotron-3 Super 120B"]
    ReAct -->|Deep Web Research| Tavily["Tavily Async Intelligence (Search, Extract, Authority Check)"]
    ReAct -->|Capacity Arithmetic| Feasibility["Deterministic Feasibility Engine"]
    
    ReAct -->|State Mutation| ConfirmGate{"Human Confirmation Gate"}
    ConfirmGate -->|User Rejects| Abort["Cancel Mutation & Preserve State"]
    ConfirmGate -->|User Approves| DBWrite[("Neon Cloud PostgreSQL 16 + pgvector HNSW")]
    
    Career -->|Deterministic Rules| Eligibility["Eligibility & Cycle Prediction Engine"]
    Career -->|Factual Audit| Validator["Resume Factual Integrity Auditor"]
    Career -->|Explicit User Approval| Submissions["Submission Adapters (Manual Handoff / ATS / Browser-Assisted)"]
    
    DBWrite --> AuditLog["Immutable Audit Log & 1-Click Rollback (/api/agent/undo)"]
    DBWrite --> VectorStore["768-dim Dense Vectors (Qwen3-Embedding-8B)"]
```

### End-to-End Request Flow
1. **Request Intake & Verification**: The user interacts through the web workspace or CLI. Requests forwarded via Vercel edge reverse proxy are verified using HMAC edge signatures (`x-compass-edge-sig`) before backend processing.
2. **Intent Routing**: Nemotron-3 Nano 30B classifies user intent and extracts validated tool parameters using native OpenAI function schemas.
3. **Contextual Retrieval**: Structured database records (tasks, schedules, candidate profile, applications) and semantically matched memory chunks (code snippets, coursework notes, ingested web research) are retrieved through dedicated code and research tools.
4. **Agent Reasoning & Grounded Research**: The ReAct agent executes reasoning steps. If external data is needed or the model emits an epistemic `[ABSTAIN]`, Tavily performs authoritative search with prompt-injection sanitization.
5. **Confirmation & Factual Integrity Gates**: Any state mutation (adding/editing tasks, applying triage plans, preparing application batches) halts at a human confirmation gate. For career applications, submissions require an explicit cryptographic approval token with legal attestations.
6. **Execution & Reversible Logging**: Approved mutations write to Neon PostgreSQL and record a snapshot in `agent_audit_log`, enabling one-click undo and complete auditability.

---

## Core Capabilities

### 1. 🤖 Autonomous ReAct Agent & Confirmation Gates
- **Multi-Step Execution**: Runs bounded ReAct reasoning loops that plan, call tools, inspect responses, and synthesize answers using real backend state.
- **Human-in-the-Loop Safeguards**: State-mutating tools (`add_task`, `edit_task`, `delete_task`, `apply_triage_plan`, `commit_schedule`, `ingest_url`) halt execution and present color-coded action proposals for explicit user approval.
- **Audit & Undo Engine**: Every mutation is logged with previous and next state snapshots, allowing immediate rollback via `/api/agent/undo` or the UI.
- **Specialist Multi-Agent Team**: Dedicated specialist agents (`coursework`, `research`, `calendar`, `memory`, and `auto-dispatcher`) for focused, in-depth analysis.

### 2. 🧠 Persistent Cross-Domain Memory
- **Unified Knowledge Stores**: Combines relational task data, project milestones, conversation history, and technical code context.
- **Semantic Vector Memory**: Notes, code decisions, and external documentation are chunked, embedded into 768-dimensional dense vectors using `Qwen3-Embedding-8B`, and indexed with HNSW indexes in Neon `pgvector`.
- **Session Continuity**: Multi-turn chat persistence supporting pinned conversations, custom renaming, guest-to-account migration, and public shareable links.

### 3. 🌐 Web Intelligence & Deep Research (Tavily)
- **Epistemic Abstention (`search_web`)**: When internal memory lacks verified facts, the agent emits `[ABSTAIN]`, triggering targeted Tavily searches instead of hallucinating.
- **Indirect Prompt Injection Fencing**: Retrieved web content is enclosed in `<untrusted_web_content>` boundaries and parsed with toolless JSON extractors to prevent adversarial webpage instructions from hijacking the agent.
- **Confirm-Gated Web Ingestion (`ingest_url`)**: Authoritative web documentation can be scraped, chunked, embedded, and added to vector memory — only after explicit user confirmation.
- **Proactive Staleness & Deadline Verification (`verify_deadline`)**: Cross-references stored hackathon or project deadlines against live contest websites to detect schedule drift without corrupting database state.

### 4. 📊 Feasibility Engine & Dynamic Scheduling
- **Deterministic Capacity Arithmetic**: Analyzes demand hours versus effective availability across a configurable safety margin (e.g. 80% nominal capacity) without delegating arithmetic to LLM guesswork.
- **Automated Triage Generation**: When work is mathematically infeasible, produces a triage proposal categorizing tasks into *Keep*, *Defer*, or *Drop*.
- **Google Calendar Sync**: Bidirectional slot allocation, ICS feed generation, and conflict detection between technical sprints and academic meetings.

### 5. 🎯 Career Copilot (5th Navigation Tab)
A comprehensive system for internship discovery, verified eligibility analysis, truthful resume tailoring, and controlled application submission:

#### A. Internship Radar (`/career` → Radar)
- **Multi-Source Sourced Opportunities**: Curates verified openings across AI/ML, Software Engineering, Backend, Systems, and Data Science.
- **Deterministic Eligibility Classification**: Rigorously evaluates candidate university degree, academic year (e.g., 2nd or 3rd-year B.Tech), expected graduation year, country, and work authorization against published job requirements. Produces explainable outcomes: `ELIGIBLE`, `POTENTIAL_MATCH`, `INELIGIBLE`, or `INSUFFICIENT_INFORMATION`.
- **Hiring Cycle Forecasting**: Distinguishes **Open Confirmed**, **Upcoming Confirmed**, and **Predicted** recruitment cycles based on empirical historical data, preventing statistical forecasts from masquerading as open applications.

#### B. Resume Studio (`/career` → Resume Studio)
- **Master Resume Repository**: Central single-source-of-truth candidate profile capturing verified education, skills, technical projects, work experience, certifications, and achievements.
- **Truthful Role Tailoring**: Emphasizes and reorders existing verified skills and relevant projects to match job descriptions. **Strict rule:** Never manufactures qualifications, invents projects, or inflates credentials. Genuine skill gaps are surfaced explicitly.
- **Factual Integrity Report Card**: Tailored drafts are compared against the master profile. Any claim, skill, or project not found in verified candidate data is flagged as an `unsupported_claim`, failing validation and blocking the resume from being marked application-ready.
- **Printable ATS Export**: Generates clean, accessible, and ATS-compliant HTML/PDF-ready export documents.

#### C. Application Center (`/career` → Application Center)
- **Pipeline Tracking**: End-to-end lifecycle management from `SAVED` to `READY_FOR_REVIEW`, `READY_FOR_APPROVAL`, `SUBMITTED`, `INTERVIEW`, and `OFFER_RECEIVED`.
- **Structured Answer Prefill**: Frequently requested application responses (degree, university, graduation year, work authorization declarations) are populated strictly from verified candidate profile data with provenance.
- **Frozen Batch Review & Explicit User Approval Gate**:
  - Applications are snapshotted into immutable batches for unified candidate review.
  - Submissions are hard-blocked at the backend unless the candidate explicitly verifies: (1) factual accuracy attestation, (2) work-authorization confirmation, and (3) legal declarations acceptance.
  - Generates verifiable approval tokens.
- **Modular Submission Adapters**:
  - `ManualHandoffAdapter`: Produces a complete one-click application kit (pre-filled answers, tailored resume, direct official portal URL, step-by-step checklist) for standard job boards and custom portals.
  - `AtsEndpointAdapter`: Declarative capabilities for Greenhouse and Lever job board APIs (with automated fallback to manual handoff when applicant enterprise API keys are absent).
  - `BrowserAssistedAdapter`: Pre-fills verified application fields while keeping final submission execution in user hands.

---

## AI Model Architecture & Routing

Compass routes requests across a 3-tier model hierarchy on **Nebius Token Factory**, optimizing for latency, reasoning depth, and cost efficiency:

| Model ID | Role | Responsibilities | When Invoked |
| :--- | :--- | :--- | :--- |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | **Intent Router & Parameter Extractor** | Lightweight routing, skill parameter parsing, and greeting triage | Every incoming user turn |
| `nvidia/nemotron-3-super-120b-a12b` | **Skill Reasoning & Plan Critic** | ReAct agent steps, specialist agent execution, and structured reasoning | Multi-step agent workflows & specialist queries |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | **Cross-Domain Strategic Synthesis** | Complex multi-domain summaries and trade-off evaluations | `summarize_across_domains` tool |
| `Qwen/Qwen3-Embedding-8B` | **Dense Vector Embeddings** | 768-dimensional dense embeddings for semantic search | Code context, notes, and ingested web documents |

### Token Economics
By resolving over 85% of standard interactions via Nemotron-3 Nano and direct PostgreSQL queries, Compass eliminates unnecessary large-model invocations. Multi-step reasoning is escalated to Super 120B only when required, and Ultra 550B is reserved strictly for high-context cross-domain synthesis.

---

## Technology Stack

| Layer | Technologies | Role in System |
| :--- | :--- | :--- |
| **Frontend UI** | React 19 (`^19.3.0`), Vite 8 (`^8.3.3`), Lucide Icons, Vanilla CSS | Responsive client with dark/light themes, real-time SSE streaming, and mobile navigation |
| **Edge Reverse Proxy** | Vercel Edge Middleware (`@vercel/edge`) | Same-origin API rewrites and HMAC request signature enforcement |
| **Backend API** | FastAPI (`>=0.142.2`), Python 3.12+, Uvicorn, Pydantic 2 | Asynchronous REST API, ReAct agent loop, and WebSocket/SSE streaming endpoints |
| **Database** | PostgreSQL 16, `pgvector`, HNSW Indexing on **Neon Cloud** | Relational state storage, vector semantic search, and audit trail tables |
| **Model Hosting** | **Nebius Token Factory** | OpenAI-compatible inference endpoints for Nemotron-3 and Qwen embedding models |
| **Web Research** | **Tavily Async API** (`tavily-python`) | Authoritative domain searching, full-page extraction, and deadline staleness detection |
| **Terminal Client** | Python Typer (`cli/assistant_cli.py`), Rich | Interactive terminal REPL, task logging, and CLI agent control |
| **Security & Auth** | Python `cryptography`, HMAC-SHA256, JWT | OAuth token encryption, session hashing, guest session minting, and SSRF filtering |

---

## Project Structure

```
compass/
├── backend/
│   ├── main.py                  # FastAPI application entrypoint & lifespan management
│   ├── config.py                # Environment settings & production secret validation
│   ├── router.py                # Nemotron-3 Nano intent router & OpenAI function dispatcher
│   ├── agent.py                 # Multi-step ReAct agent loop & confirmation gating
│   ├── models_career.py         # Career Copilot schemas (resumes, applications, batches)
│   ├── models_radar.py          # Internship Radar schemas (opportunities, eligibility, cycles)
│   ├── agents/
│   │   ├── specialist.py        # Specialist multi-agent system (Coursework, Research, Calendar, Memory)
│   │   └── feasibility.py       # Deterministic capacity & triage calculation engine
│   ├── memory/
│   │   ├── db.py                # Database pool lifecycle & schema migrations
│   │   ├── career.py            # Career Copilot persistence with non-blocking in-memory fallbacks
│   │   ├── radar.py             # Opportunity index, watchlist, and candidate profile storage
│   │   ├── structured.py        # Relational task, project, and session SQL operations
│   │   └── vector.py            # pgvector HNSW similarity search
│   ├── routers/
│   │   ├── career.py            # Resume Studio & Application Center API endpoints
│   │   ├── radar.py             # Internship Radar search, filters, & watchlist endpoints
│   │   ├── tasks.py             # Structured task CRUD & domain filtering
│   │   ├── chat.py              # Conversational chat & SSE streaming
│   │   └── calendar.py          # Google Calendar sync & ICS export
│   ├── services/
│   │   ├── career_resume.py     # Truthful resume tailoring & strict factual integrity auditor
│   │   ├── career_submission.py # Submission adapter router, explicit approval gate, & manual handoff kit
│   │   ├── radar_eligibility.py # Deterministic eligibility evaluation engine
│   │   ├── radar_prediction.py  # Historical hiring cycle forecasting
│   │   ├── radar_verifier.py   # HTTP & Tavily live verification with prompt-injection fencing
│   │   └── tavily_pipeline.py   # Deep research pipeline, query decomposition, & evidence ledger
│   └── skills/                  # Registered tool schemas and execution handlers
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── CareerCopilot.jsx     # Master coordinator for Radar, Resumes, Applications, & Profile
│   │   │   ├── InternshipRadar.jsx   # Opportunity search, multi-facet filters, & prediction badges
│   │   │   ├── career/
│   │   │   │   ├── ResumeStudio.jsx      # Master editor, factual audit report cards, & ATS HTML export
│   │   │   │   └── ApplicationCenter.jsx # Pipeline tracker, batch approval modal, & handoff kits
│   │   │   ├── Dashboard.jsx         # System overview & telemetry stats
│   │   │   ├── Timeline.jsx          # Multi-domain chronologically sorted task feed
│   │   │   ├── CalendarView.jsx      # Schedule & calendar availability interface
│   │   │   └── CompassPanel.jsx      # AI Assistant chat & agent planner traces
│   │   ├── api/
│   │   │   ├── careerApi.js          # Client SDK for Career Copilot endpoints
│   │   │   ├── radarApi.js           # Client SDK for Internship Radar endpoints
│   │   │   └── client.js             # General API client for tasks, memory, and chat
│   │   └── App.jsx                   # Root layout, navigation, and mobile drawer handling
│   ├── package.json
│   └── vite.config.js
├── cli/
│   └── assistant_cli.py         # Typer + Rich terminal client
├── tests/                       # 472 automated tests across 50 test suites
│   ├── test_career_copilot.py   # Resume validation, batch gates, & career endpoints
│   ├── test_internship_radar.py # Eligibility rules, cycle forecasting, & radar endpoints
│   ├── test_security_hardening.py# SSRF defenses, HMAC signatures, & IDOR boundaries
│   └── test_demo_flow.py        # End-to-end task, timeline, and persona workflows
├── docs/                        # In-depth architectural & deployment documentation
├── verification/                # Verified browser UI execution screenshots
├── run_local.bat                # Windows one-click local dev launcher
├── run_local.sh                 # Linux / macOS local dev launcher
└── docker-compose.yml           # Full stack local containerization
```

---

## Quick Start

### Prerequisites
- **Python 3.12+**
- **Node.js 18+** and `npm`
- **PostgreSQL 16** with `pgvector` extension (or a free cloud database from [Neon](https://neon.tech))
- **Nebius Token Factory API Key** ([nebius.com](https://nebius.com/))
- **Tavily API Key** ([tavily.com](https://tavily.com/)) *(Optional — web search tools gracefully abstain if omitted)*

### 1. Clone & Configure Environment
```bash
git clone https://github.com/Ratnesh-101/compass.git
cd compass

# Copy environment template
cp .env.example .env
```
Edit `.env` to configure your `NEBIUS_API_KEY`, `AUTH_TOKEN`, and `DATABASE_URL`.

### 2. Install Backend & CLI
```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install backend dependencies
pip install -r backend/requirements.txt

# Install terminal CLI in editable mode
pip install -e ./cli
```

### 3. Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

### 4. Run Locally

**Option A — Automated Launch Scripts:**
```bash
# Windows
run_local.bat

# Linux / macOS
chmod +x run_local.sh && ./run_local.sh

# Docker Compose (Backend + Frontend + local PostgreSQL with pgvector)
docker compose up
```

**Option B — Manual Launch (Separate Terminals):**
```bash
# Terminal 1: Backend API (port 8000)
python -m uvicorn backend.main:app --port 8000 --reload

# Terminal 2: Frontend Client (port 5173)
cd frontend
npm run dev
```

Visit **[http://localhost:5173](http://localhost:5173)** in your browser. All visitors receive an isolated anonymous guest session with no initial login required.

### 5. Using the Terminal CLI
```bash
# Check dashboard overview & pending tasks
compass status

# Ask a grounded question
compass ask "What hackathon milestones are due within the next 48 hours?"

# Add a task with domain tag and due date
compass add "Finalize transformer benchmark" --domain code --due 2026-10-30 --priority high

# Log code context into vector memory
compass log "Integrated 768-dim Qwen dense embeddings into Neon pgvector" --domain code

# Run the autonomous planning agent
compass agent "Propose a triage schedule for coursework and hackathons"
```

---

## Environment Variables Reference

| Variable | Required? | Scope | Purpose | Example / Guidance |
| :--- | :---: | :---: | :--- | :--- |
| `ENVIRONMENT` | No | Backend | Runtime mode: `development`, `test`, or `production` (default). Set to `development` locally | `development` |
| `NEBIUS_API_KEY` | **Yes** | Backend | Authenticates inference requests to Nebius Token Factory | `your_nebius_api_key_here` |
| `AUTH_TOKEN` | **Yes** | Backend | Master administrative bearer token | `generate_secure_random_token_here` |
| `DATABASE_URL` | **Yes** | Backend | Neon PostgreSQL connection URI with SSL mode | `postgresql://user:pass@host/db?sslmode=require` |
| `NEBIUS_BASE_URL` | No | Backend | Nebius Token Factory base API endpoint | `https://api.tokenfactory.nebius.com/v1/` |
| `ROUTER_MODEL` | No | Backend | Model identifier for intent routing | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| `SKILL_MODEL` | No | Backend | Model identifier for ReAct & specialist reasoning | `nvidia/nemotron-3-super-120b-a12b` |
| `SYNTHESIS_MODEL` | No | Backend | Model identifier for multi-domain synthesis | `nvidia/Nemotron-3-Ultra-550b-a55b` |
| `EMBEDDING_MODEL` | No | Backend | Model identifier for dense vector embeddings | `Qwen/Qwen3-Embedding-8B` |
| `EMBEDDING_DIMENSION` | No | Backend | Dimensionality of embeddings in pgvector table | `768` |
| `TAVILY_API_KEY` | Optional | Backend | API key for Tavily live web intelligence | `tvly-your_key_here` |
| `TAVILY_ENABLED` | Optional | Backend | Master flag to toggle Tavily search tools | `true` or `false` |
| `EDGE_HMAC_SECRET` | Production | Both | Shared HMAC secret between Vercel edge proxy and Render | Generate via `openssl rand -hex 32` |
| `TOKEN_ENCRYPTION_KEY` | Production | Backend | 32-byte key for AES encryption of stored OAuth secrets | Generate via `openssl rand -hex 32` |
| `GUEST_SIGNING_SECRET` | Production | Backend | Cryptographic secret for signing guest session JWTs | Generate via `openssl rand -hex 32` |
| `GOOGLE_CLIENT_ID` | Optional | Backend | Google OAuth Client ID for Calendar integration | `your_client_id.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET`| Optional | Backend | Google OAuth Client Secret for Calendar integration | `your_client_secret_here` |

> 🔒 **Security Notice:** All API keys and secrets belong exclusively in backend environment configuration. Secrets are never exposed to the Vite browser bundle.

---

## Conversational Career Workflows

Compass's ReAct agent natively orchestrates Career Copilot operations from natural language within the `/compass` assistant chat:

```
User: "Find open AI/ML internships in India that accept 2nd or 3rd-year B.Tech students."
Compass: Calls `query_internship_radar` with category='ai_ml', country='India', academic_year=2.
         Returns confirmed openings, verified deadlines, and explains eligibility matches.

User: "Tailor my resume for the Anthropic ML Research Intern role."
Compass: Calls `tailor_resume` with opportunity_id=101.
         Reorders verified candidate skills and projects to match job requirements.
         Flags any unverified requirements as skill gaps without fabricating claims.
         Produces a structured validation report and ATS-ready export link.

User: "Prepare applications for my top three saved internships."
Compass: Calls `prepare_application` for each listing.
         Prefills university, degree, and work-authorization declarations from verified profile data.
         Attaches tailored resume versions and transitions applications to READY_FOR_REVIEW.

User: "Submit the approved application batch."
Compass: Calls `submit_approved_application_batch`.
         Verifies explicit user approval token and attestations.
         Executes verified manual handoff packages or API submissions and reports confirmation results.
```

---

## Testing & Quality Assurance

Compass features **472 automated tests** across 50 dedicated test suites covering unit logic, integration paths, security hardening, and end-to-end user workflows:

```bash
# Run the complete test suite
pytest -v

# Run Career Copilot & Internship Radar tests (fast, ~3.5s)
pytest tests/test_career_copilot.py tests/test_internship_radar.py -v

# Run Security Hardening tests (SSRF, HMAC signatures, IDOR isolation)
pytest tests/test_security_hardening.py -v

# Run Tavily Deep Research & Epistemic Abstention tests
pytest tests/test_tavily.py tests/test_tavily_deep.py tests/test_tavily_abstain.py -v

# Run End-to-End Demo Workflows & Model Check tests
pytest tests/test_demo_flow.py tests/test_model_check.py -v
```

### Frontend Compilation Check
```bash
cd frontend
npm run build
```
*Compiles all 1,953 application modules cleanly with Vite in under 1 second.*

---

## 🧭 Compass CLI

Compass includes a full-featured terminal CLI (`compass`) for interacting with tasks, memory, chat, triage, and administrative maintenance directly from your terminal.

### Installation & Packaging
```bash
pip install -e cli/
compass --version
# Compass CLI 0.1.0
```

### Authentication & Guest Isolation
- **`compass login`**: Obtains an isolated cryptographic guest session via `POST /api/guest/session` or saves an existing session token (`--token <token>`). Tokens are stored in `~/.compass/credentials.json` with owner-only filesystem permissions (Windows ACL / POSIX 0600) and masked when displayed.
- **Default Base URL**: `http://localhost:8000`. Configure a custom endpoint via `compass login --url <url>` or `compass config --url <url>`. When connected to a remote production host, a visible `Connected to <host>` banner is displayed.
- **Admin Commands**: Commands under `compass admin ...` require the master `AUTH_TOKEN`, passed explicitly via `--token` or the `AUTH_TOKEN` environment variable. Master tokens are never stored to disk by default.

### Key Commands
```bash
# Obtain guest session
compass login

# Task Management (isolated per caller identity)
compass tasks                              # List current tasks
compass add "Fix CLI formatting" --domain code # Add a task with domain & priority

# Memory & Status
compass status                             # Full terminal dashboard across domains
compass log "Memory summary" --domain code # Log vector memory chunk (768-dim)
compass projects                           # List tracked projects

# Conversational & Agent Workflows
compass ask "What deadlines do I have?"    # One-shot question with live token streaming
compass chat                               # Interactive REPL with clean Ctrl+C handling (code 130)
compass triage --days 5 --hours 4          # Interactive feasibility triage session
compass agent "Plan sprint tasks"          # ReAct agent loop with confirmation gates

# Admin Maintenance (requires master AUTH_TOKEN)
compass admin usage --token <AUTH_TOKEN>   # Token consumption & cost breakdown
compass admin-undo --run-id <run_id>       # Revert last state mutation
```

---

## Production Deployment

Compass is deployed using continuous integration and deployment pipelines targeting provider-native cloud environments:

- **Frontend (Vercel)**: Deployed as a high-performance single-page application at [compass-farmlytics.vercel.app](https://compass-farmlytics.vercel.app). Employs edge middleware to sign forwarded client IP headers with `EDGE_HMAC_SECRET` and proxies `/api/*` traffic to the backend.
- **Backend API (Render)**: Deployed as a Dockerized web service on Render with health checks at `/health`. Enforces strict production fail-closed security for database connections and API secret validation.
- **Database (Neon Cloud)**: Serverless PostgreSQL 16 with `pgvector` extension and automated schema migrations managed in `backend/memory/db.py`.

For comprehensive deployment topologies, zero-downtime database migration procedures, and rollback runbooks, see **[docs/deployment.md](docs/deployment.md)**.

---

## Security Model & User Controls

1. **Human Confirmation Gates**: State-mutating actions halt and request explicit user confirmation before touching the database.
2. **Strict Factual Resume Integrity**: Resume Studio enforces factual consistency against the candidate's master profile. It will never invent jobs, fabricate skills, or forge numerical achievements.
3. **Explicit Batch Submission Gating**: No external application can be submitted without an immutable batch snapshot, verified candidate attestations, and a cryptographically generated approval token.
4. **SSRF & Network Fencing**: Internal IP ranges (e.g. `127.0.0.1`, `169.254.169.254`, `10.0.0.0/8`, IPv6 local loopbacks) and unsafe URL protocols are blocked from web scraping tools.
5. **Multi-Tenant User Isolation**: Every database query and cache lookup enforces strict `user_id` scoping to prevent Insecure Direct Object References (IDOR).
6. **Graceful Degradation**: If external APIs or database pools experience transient downtime, non-blocking in-memory layers maintain core application availability without hanging.
7. **Environment Mode & Impersonation Prevention**: `ENVIRONMENT` must be explicitly set to `development` for local testing. In `production` or when unset, unauthenticated header impersonation (`x-user-id`) is rejected with HTTP 403, and unverified stale cookies (`compass_user_id`) return HTTP 401 with `Set-Cookie` expiration headers.
8. **Demo Persona Seeding Gate**: The 1-click Judge Persona seeding endpoint (`/api/demo/seed`) is strictly guarded. In `production` environments, seeding is disabled by default and rejected with HTTP 403 unless explicitly enabled with `ENABLE_DEMO_SEEDING=true`.

---

## Known Limitations

- **ATS Enterprise Key Requirement**: Public job board integrations (e.g., Greenhouse, Lever) permit open listing discovery and detail ingestion. Direct programmatic application submission requires enterprise employer API keys; for candidate submissions, Compass safely generates complete one-click manual handoff packages.
- **Anti-Bot & CAPTCHA Boundaries**: Compass respects destination access restrictions and anti-bot protections. Portals utilizing interactive CAPTCHAs are handled via browser-assisted form pre-fill rather than fragile automated bypasses.
- **Predictive Cycle Estimation**: Upcoming hiring cycle projections are statistical estimates derived from historical announcement dates and are explicitly labeled as predictions rather than confirmed openings.

---

## Documentation Index

- **[Architecture & Memory Schema](docs/architecture.md)** — Deep dive into request routing, vector memory, and database schemas
- **[Deployment & Production Runbooks](docs/deployment.md)** — CI/CD architecture, edge HMAC configurations, and rollback guides
- **[Security Architecture & Threat Model](docs/security.md)** — SSRF defenses, audit logs, and IDOR isolation policies
- **[Testing & Test Suite Breakdown](docs/testing.md)** — Test runner configurations and suite coverage
- **[API Contract & Specifications](docs/api_contract.md)** — OpenAPI endpoint specifications
- **[Walkthrough & Demo Script](docs/demo_script.md)** — Step-by-step video recording guide
- **[Contributing Guidelines](CONTRIBUTING.md)** — Local development setup and coding standards
- **[Nebius Platform Feedback](NEBIUS_PLATFORM_FEEDBACK.md)** — In-depth developer experience feedback and benchmarks
- **[Hackathon Submission Kit](SUBMISSION_KIT.md)** — Submission details, Tavily integration justification, and benchmark logs

---

## Hackathon Submission

**Track**: Best Apps and Agents — Nebius × NVIDIA Global AI Hackathon 2026

**Special Category Highlights**:
- *Best Use of Tavily ($3,000)* — Grounded epistemic abstention, multi-query evidence ledger, deadline staleness verification, and prompt-injection fencing.
- *Most Valuable Feedback Award* — Exhaustive developer experience feedback and model performance benchmarks documented in [NEBIUS_PLATFORM_FEEDBACK.md](NEBIUS_PLATFORM_FEEDBACK.md).

---

## Team

| Member | Role | Primary Contributions |
| :--- | :--- | :--- |
| **Rhythm** | Backend Architecture | Database schemas, SQL migrations, Nebius Token Factory model integration |
| **Nandani** | Frontend Engineering | Web dashboard, real-time context streaming UI, and conversational chat interfaces |
| **Kunal** | Frontend Design | Timeline feed styling, mobile responsiveness, and shared design tokens |
| **Ratnesh Singh** | Full-Stack & System Integration | Career Copilot implementation, deployment engineering (Render, Vercel, Neon), ReAct agent, and terminal CLI |

---

## License

This project is licensed under the [MIT License](LICENSE).
