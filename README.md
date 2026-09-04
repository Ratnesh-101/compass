# Compass

Personal AI assistant with persistent memory — tracks hackathon deadlines, recalls code context across repos, and organizes coursework. Built on Nebius Token Factory with Nemotron models. Web chat + CLI, one shared brain.

---

## How Nebius & NVIDIA Power It

Compass leverages Nebius Token Factory for low-latency, enterprise-grade model inference across three dedicated tiers:

### 1. NVIDIA Open-Source Models (Core Hackathon Requirement)
* **Router & Dispatcher**: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
  - Evaluates all incoming user messages using native OpenAI-compatible function calling (`tools` + `tool_choice: "auto"`).
  - Dispatches zero-shot to structured task mutations, memory retrieval, or contextual conversation without requiring brittle JSON parsing fallbacks.
* **Skill Execution**: `nvidia/nemotron-3-super-120b-a12b`
  - Drives high-precision domain actions, reasoning over complex schedules, dependencies, and code contexts.
* **Cross-Domain Synthesis**: `nvidia/Nemotron-3-Ultra-550b-a55b`
  - Condenses multi-turn conversations into persistent long-term memory chunks and executes nightly memory consolidation jobs.

### 2. Other Token Factory Models Used
* **Vector Embeddings**: `Qwen/Qwen3-Embedding-8B`
  - Generates semantic embeddings for code, coursework, and memory chunks.
  - Utilizes **Matryoshka representation learning (`dimensions=768`)** to truncate native 4096-dim vectors into high-fidelity 768-dim embeddings, maintaining sub-0.21 cosine distance on target queries while remaining strictly within PostgreSQL `pgvector`'s 2,000-dimension HNSW indexing boundary.

