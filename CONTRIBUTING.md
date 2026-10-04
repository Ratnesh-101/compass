# Contributing to Compass

Welcome to **Compass**! This document provides guidelines and setup instructions for teammates and external contributors.

---

## 1. Project Overview

Compass is a persistent-memory AI copilot connecting tasks, hackathon deadlines, coursework, code context, and conversations into one agent-driven workspace with deterministic feasibility and human confirmation gates.

Key architectural documentation:
- **System Architecture**: [docs/architecture.md](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/docs/architecture.md)
- **Deployment & Runbook**: [docs/deployment.md](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/docs/deployment.md)
- **Security & Threat Model**: [docs/security.md](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/docs/security.md)
- **API Contract**: [docs/api_contract.md](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/docs/api_contract.md)
- **Testing Strategy**: [docs/testing.md](file:///c:/Users/Ratnesh%20Singh/OneDrive/Desktop/compass/docs/testing.md)

---

## 2. Prerequisites

- **Python**: 3.12 or newer
- **Node.js**: 20.x or newer with `npm`
- **Database**: PostgreSQL 16 with `pgvector` extension (or a free [Neon](https://neon.tech/) Serverless Postgres branch)
- **Optional API Keys**:
  - `NEBIUS_API_KEY`: For live Nebius Token Factory inference (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `Qwen/Qwen3-Embedding-8B`).
  - `TAVILY_API_KEY`: For live Tavily web intelligence search and URL ingestion.

---

## 3. Local Development Setup

### A. Clone & Virtual Environment

```bash
git clone https://github.com/Ratnesh-101/compass.git
cd compass

# Create and activate virtual environment
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# Install backend and test dependencies
pip install --upgrade pip
pip install -r backend/requirements.txt
pip install -r requirements-test.txt

# Install the Compass CLI in editable mode
pip install -e ./cli
```

### B. Environment Configuration

Copy the example configuration to `.env`:

```bash
cp .env.example .env
```

Key environment variables:
```ini
ENVIRONMENT=development
DATABASE_URL=postgresql://user:pass@localhost:5432/compass
AUTH_TOKEN=dev-token
PORT=8000

# AI Provider Keys (Optional for basic development and mock runs)
NEBIUS_API_KEY=
TAVILY_API_KEY=
```

### C. Initialize & Seed Database

If running against a fresh PostgreSQL instance with pgvector:
```bash
# Apply schema (tables, HNSW index, auto-migrations)
python -c "import asyncio; from backend.memory.db import init_pool; asyncio.run(init_pool())"

# Seed initial baseline projects, tasks, and memory chunks
python scripts/seed_data.py
```

### D. Run the Backend Server

```bash
uvicorn backend.main:app --reload --port 8000
```
- Health endpoint: `http://localhost:8000/health`
- OpenAPI docs: `http://localhost:8000/docs`

### E. Run the Frontend Dashboard

```bash
cd frontend
npm install
npm run dev
```
The Vite development server runs on `http://localhost:5173` with proxying configured to `http://localhost:8000`.

---

## 4. Running the CLI

With the virtual environment active and `./cli` installed:

```bash
# View active tasks and status summary
compass status

# Ask the copilot a question
compass ask "What are my upcoming hackathon deliverables?"

# Run the ReAct agent goal planner
compass agent "Plan my schedule for this afternoon"

# Log a technical snippet into vector memory
compass log "Configured 768-dim embeddings with Nebius Token Factory" --domain code --project "Compass" --tags nebius,vector

# View token accounting and model usage summary
compass admin usage
```

---

## 5. Testing & Validation

All pull requests must pass continuous integration checks before merge.

### A. Run Pytest Suite

```bash
# Run unit and integration tests (requires TEST_DATABASE_URL or uses SQLite fallback)
pytest tests -v
```

### B. Linting with Ruff

```bash
ruff check backend cli tests scripts
```

### C. Source File Size Audit

Compass enforces a strict architectural file-size policy to preserve modularity:
- **Preferred maximum**: $\le 500$ lines per source file
- **Absolute maximum**: $\le 700$ lines per source file
- Any file exceeding 700 lines will **fail** CI.

Run the file size checker locally before committing:
```bash
python scripts/check_file_sizes.py
```

### D. Frontend Build Validation

```bash
cd frontend
npm run build
```

---

## 6. Coding Standards & Guidelines

1. **State Safety**: Never perform direct database mutations from background routines or agents without passing through the confirmation gate (`MUTATING_TOOLS` and `POST /api/agent/confirm`).
2. **Deterministic Arithmetic**: Never prompt LLMs to calculate schedule math or capacity sums. Use deterministic algorithms (`backend/services/scheduler.py`, `backend/agents/feasibility.py`).
3. **Web Intelligence Quarantining**: Always isolate external web content inside `<untrusted_web_content>` XML fences with prompt-injection sanitization.
4. **File Size Limit**: If a module approaches 500 lines, extract domain-specific logic, schemas, or helper services into dedicated submodules.
5. **Secrets Hygiene**: Never commit API keys, connection strings, or production credentials. Use `.env` and fail-closed secret validators (`backend/config.py`).
