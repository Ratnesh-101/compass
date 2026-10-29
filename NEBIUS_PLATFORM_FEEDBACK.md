# ⚡ Nebius Platform & NVIDIA Model Feedback Report
> **Submission for the Most Valuable Feedback Award ($100 + NVIDIA Swag)**  
> **Project**: [Compass](https://github.com/Ratnesh-101/compass) — The AI Copilot That Remembers Every Hackathon, Repo, and Deadline  
> **Authors**: Ratnesh Singh, Nandani, Kunal  
> **Environment**: Production FastAPI + Neon Serverless PostgreSQL (`pgvector`) + Vite/React 19 Dashboard  
> **Evaluated Infrastructure**: Nebius Token Factory (`https://api.tokenfactory.nebius.com/v1/`) & NVIDIA Nemotron models  

---

## 1. Executive Summary

During the development and testing of **Compass**—an autonomous, multi-domain productivity agent with persistent semantic memory—our team ran automated tests and live agent sessions against the **Nebius Token Factory**. 

Our system relies on a **3-tier hierarchical model dispatch pipeline**:
1. **Tier 1 (Fast Intent Routing & Function Calling)**: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (~3B active parameters per token).
2. **Tier 2 (Deep Reasoning & Human-in-the-Loop ReAct Loop)**: `nvidia/nemotron-3-super-120b-a12b` (~12B active parameters per token).
3. **Tier 3 (Multi-Domain Strategic Roadmap Synthesis)**: `nvidia/Nemotron-3-Ultra-550b-a55b` (~55B active parameters per token).
4. **Dense Semantic Memory**: `Qwen/Qwen3-Embedding-8B` indexed with `pgvector` HNSW cosine similarity.

Below is our comprehensive developer feedback, divided into **Production Strengths** (what the Nebius team nailed), **Actionable Suggestions & Edge Cases** (with concrete code repros), and **Strategic Feature Requests** for agentic developers.

---

## 2. Production Strengths: What Nebius Got Right

### 2.1 Interactive Latency
- **Nemotron-3 Nano (30B A3B)** felt responsive in our multi-turn skill-dispatch flows. We did not run a controlled latency benchmark for this report; `scripts/measure_router_latency.py` measures router latency if you want numbers.
- In our intent router (`backend/router.py`), Nano correctly extracted tool arguments (`domain`, `due_date`, `priority`, `duration_minutes`) without requiring brittle regex fallbacks.

### 2.2 Drop-in OpenAI SDK Compatibility
- Nebius Token Factory adheres strictly to the OpenAI v1 REST specification. Switching Compass from standard providers to Nebius required changing only two configuration variables:
  ```python
  client = AsyncOpenAI(
      base_url="https://api.tokenfactory.nebius.com/v1/",
      api_key=os.environ.get("NEBIUS_API_KEY"),
  )
  ```
- Streaming Server-Sent Events (SSE) worked reliably with `client.chat.completions.create(stream=True)`.

### 2.3 Compelling MoE Unit Economics
- Because Nemotron uses fine-grained Mixture-of-Experts (MoE) routing, active parameter counts remain tiny relative to overall parameter capacity:
  - Nano 30B activates about 3B parameters per token ($0.06 input / $0.24 output per 1M tokens).
  - Super 120B activates only **12B parameters** per token ($0.30 input / $0.90 output per 1M tokens).
- Routing routine intent classification and tool invocation to Nano, and keeping Super and Ultra for the steps that need them, keeps per-turn cost low. Prices above are the ones configured in `backend/config.py`.

---

## 3. Actionable Feedback & Edge Cases Encountered

### 3.1 Embeddings Dimension Slicing (Matryoshka Representation Learning)
* **Context**: We use `Qwen/Qwen3-Embedding-8B` on Nebius for our dense memory store in Neon PostgreSQL (`pgvector`).
* **The Issue**: By default, `Qwen3-Embedding-8B` emits **4,096-dimensional vectors**. In standard PostgreSQL installations, `pgvector` HNSW indexes have an upper limit of **2,000 dimensions** (due to default Postgres index page sizes of 8 KB).
* **What we do**: `backend/services/embeddings.py` requests `dimensions=768` and then also slices the first 768 values and L2-normalizes in Python, so the index is safe whether or not the server truncates:
  ```python
  raw_vec = response.data[0].embedding
  sliced = raw_vec[:768]
  norm = math.sqrt(sum(x * x for x in sliced))
  normalized_768 = [x / (norm or 1e-12) for x in sliced]
  ```
* **Suggestion for Nebius**: Document whether the `dimensions` parameter (e.g. `{"input": text, "model": "Qwen/Qwen3-Embedding-8B", "dimensions": 768}`) is honored for this model and whether the returned vector is re-normalized. Since `Qwen3-Embedding-8B` supports Matryoshka-style truncation, server-side truncation would shrink the payload (768 of 4,096 values) and spare clients the slicing step.

---

### 3.2 Usage Accounting in Streaming Mode (`stream_options`)
* **Context**: Compass streams tokens via SSE (`backend/services/chat_stream.py` sets `stream_options={"include_usage": True}`) and records prompt tokens, completion tokens, and cost.
* **The Issue**: When requesting `stream=True`, OpenAI supports `stream_options: {"include_usage": true}` to append a final chunk containing the `usage` object:
  ```json
  {"id":"chatcmpl-...","choices":[],"usage":{"prompt_tokens":142,"completion_tokens":89,"total_tokens":231}}
  ```
  On Token Factory, passing `stream_options` sometimes returned no final `usage` chunk on certain models during our development, so we estimate tokens when it is missing. We have not re-measured which models are affected.
* **Suggestion for Nebius**: Ensure all generative models on Token Factory support the standard OpenAI `stream_options={"include_usage": True}` flag so agentic builders can track token budgets and billing in real-time during SSE streaming.

---

### 3.3 Multi-Tool Call Schema Serialization in Nemotron-3 Nano
* **Context**: When an agent user prompt contains multiple operations (e.g., *"Add a hackathon task for Sunday and verify the devpost deadline"*), the agent needs to invoke multiple tools.
* **The Issue**: When multiple tools are registered in the `tools` array, Nemotron-3 Nano occasionally emitted multiple concatenated JSON tool-call objects in a single message string rather than distinct entries in the `tool_calls` array:
  ```text
  // Emitted by model inside content:
  {"name": "add_task", "arguments": {...}}
  {"name": "verify_deadline", "arguments": {...}}
  ```
* **Our Workaround**: We saw this during development and have not re-verified it for this report; our router (`backend/router.py`) acts on the first tool call in the response.
* **Suggestion for Nebius**: Add fine-tuning / system-prompt alignment in the Token Factory proxy layer for Nemotron to strictly enforce standard OpenAI array schema:
  ```json
  "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "add_task", "arguments": "..."}},
    {"id": "call_2", "type": "function", "function": {"name": "verify_deadline", "arguments": "..."}}
  ]
  ```

---

### 3.4 Model Warmth / Cold-Start Telemetry Headers
* **Context**: Ultra-large models like `Nemotron-3-Ultra-550b` provide strong reasoning, but latency can spike if an instance has scaled down or is cold-starting.
* **Suggestion for Nebius**: Expose custom HTTP response headers (e.g., `x-nebius-worker-status: warm|cold`, `x-nebius-inference-latency-ms: 124`). This empowers agent frameworks to dynamically adjust client timeouts or failover gracefully to smaller models when cold starts occur.

---

## 4. Feature Wishlist for Agentic Builders

| Feature | Impact for Developers | Priority |
| :--- | :--- | :--- |
| **Native Matryoshka Slicing (`dimensions` param)** | Eliminates client-side L2 re-normalization for `pgvector` compatibility. | High |
| **Streaming `include_usage` Support** | Precise token telemetry without local tokenizer approximation. | High |
| **Private VPC Peering between Nebius Compute & Token Factory** | Sub-millisecond internal routing for high-frequency agent loops. | Medium |
| **Native Structured Outputs (`response_format: {"type": "json_schema"}`)** | Guaranteed schema compliance for autonomous agent loops. | High |
| **Built-in Prompt Caching** | Reduces costs for long agent system prompts with repetitive tool definitions. | Medium |

---

## 5. Conclusion & Verification

Nebius Token Factory with the NVIDIA Nemotron models gave us a simple, low-cost way to run tiered open-weights inference behind one OpenAI-compatible endpoint. By addressing the embedding dimension parameter and streaming usage options, Nebius would make Token Factory easier to use for production agentic apps.

Compass exposes aggregate usage telemetry via `GET /api/telemetry`.

*Thank you to the Nebius and NVIDIA teams for hosting the hackathon.*
