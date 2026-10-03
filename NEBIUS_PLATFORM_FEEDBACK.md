# ⚡ Nebius Platform & NVIDIA Model Feedback Report
> **Submission for the Most Valuable Feedback Award ($100 + NVIDIA Swag)**  
> **Project**: [Compass](https://github.com/Ratnesh-101/compass) — The AI Copilot That Remembers Every Hackathon, Repo, and Deadline  
> **Authors**: Rhythm, Nandani, Kunal, Ratnesh Singh  
> **Environment**: Production FastAPI + Neon Serverless PostgreSQL (`pgvector`) + Vite/React 18 Dashboard  
> **Evaluated Infrastructure**: Nebius Token Factory (`https://api.studio.nebius.ai/v1`) & NVIDIA Nemotron Models on NVIDIA H100 SXM5 Tensor Core GPUs  

---

## 1. Executive Summary

During the development and testing of **Compass**—an autonomous, multi-domain productivity agent with persistent semantic memory—our team routed over **100,000 tokens** across hundreds of automated test executions and live agent sessions through the **Nebius Token Factory**. 

Our system relies on a **3-tier hierarchical model dispatch pipeline**:
1. **Tier 1 (Fast Intent Routing & Function Calling)**: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (~3B active parameters per token).
2. **Tier 2 (Deep Reasoning & Human-in-the-Loop ReAct Loop)**: `nvidia/nemotron-3-super-120b-a12b` (~12B active parameters per token).
3. **Tier 3 (Multi-Domain Strategic Roadmap Synthesis)**: `nvidia/Nemotron-3-Ultra-550b-a55b` (~55B active parameters per token).
4. **Dense Semantic Memory**: `Qwen/Qwen3-Embedding-8B` indexed with `pgvector` HNSW cosine similarity.

Below is our comprehensive developer feedback, divided into **Production Strengths** (what the Nebius team nailed), **Actionable Suggestions & Edge Cases** (with concrete code repros), and **Strategic Feature Requests** for agentic developers.

---

## 2. Production Strengths: What Nebius Got Right

### 2.1 Fast Interactive Latency on H100 SXM5 Infrastructure
- **Nemotron-3 Nano (30B A3B)** demonstrated fast and responsive interactive token generation across our multi-turn skill-dispatch flows.
- In our intent classification pipeline (`backend/agent.py`), Nano correctly extracted tool arguments (`domain`, `due_date`, `priority`, `duration_minutes`) without requiring brittle regex fallbacks.

### 2.2 Drop-in OpenAI SDK Compatibility
- Nebius Token Factory adheres strictly to the OpenAI v1 REST specification. Switching Compass from standard providers to Nebius required changing only two configuration variables:
  ```python
  client = AsyncOpenAI(
      base_url="https://api.studio.nebius.ai/v1",
      api_key=os.environ.get("NEBIUS_API_KEY"),
  )
  ```
- Streaming Server-Sent Events (SSE) worked reliably with `client.chat.completions.create(stream=True)`.

### 2.3 Compelling MoE Unit Economics
- Because Nemotron uses fine-grained Mixture-of-Experts (MoE) routing, active parameter counts remain tiny relative to overall parameter capacity:
  - Nano 30B activates only **3.2B parameters** per token ($0.06 input / $0.24 output per 1M tokens on Token Factory).
  - Super 120B activates only **12B parameters** per token ($0.30 input / $0.90 output per 1M tokens).
- Routing routine intent classification and tool invocation to Nano rather than general frontier models ($10.00 / $30.00 per 1M on standard GPT-4) dramatically reduces inference costs by orders of magnitude while preserving high reasoning fidelity.

---

## 3. Actionable Feedback & Edge Cases Encountered

### 3.1 Embeddings Dimension Slicing (Matryoshka Representation Learning)
* **Context**: We use `Qwen/Qwen3-Embedding-8B` on Nebius for our dense memory store in Neon PostgreSQL (`pgvector`).
* **The Issue**: By default, `Qwen3-Embedding-8B` emits **4,096-dimensional vectors**. In standard PostgreSQL installations, `pgvector` HNSW indexes have an upper limit of **2,000 dimensions** (due to default Postgres index page sizes of 8 KB).
* **Our Workaround**: We had to manually slice the first 768 dimensions and apply L2 normalization in Python:
  ```python
  raw_vec = response.data[0].embedding
  sliced = raw_vec[:768]
  norm = math.sqrt(sum(x * x for x in sliced))
  normalized_768 = [x / (norm or 1e-12) for x in sliced]
  ```
* **Suggestion for Nebius**: Support the standard `dimensions` parameter in the `/v1/embeddings` endpoint (e.g. `{"input": text, "model": "Qwen/Qwen3-Embedding-8B", "dimensions": 768}`). Since `Qwen3-Embedding-8B` was trained with Matryoshka Loss, having Nebius perform the truncation and re-normalization on the GPU before wire transfer would reduce network payload size by 81% and prevent client-side compute overhead.

---

### 3.2 Usage Accounting in Streaming Mode (`stream_options`)
* **Context**: To deliver a snappy ChatGPT-style user experience, Compass streams tokens via SSE. At the end of the stream, our telemetry engine records prompt tokens, completion tokens, and dollar cost into `token_usage_log`.
* **The Issue**: When requesting `stream=True`, OpenAI supports `stream_options: {"include_usage": true}` to append a final chunk containing the `usage` object:
  ```json
  {"id":"chatcmpl-...","choices":[],"usage":{"prompt_tokens":142,"completion_tokens":89,"total_tokens":231}}
  ```
  On Token Factory, passing `stream_options` occasionally returned empty chunks or omitted the final `usage` dictionary on certain models, forcing us to approximate completion tokens using local tokenizers.
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
* **Our Workaround**: We implemented robust bracket-matching JSON extraction in our fallback dispatcher (`backend/services/scheduler.py`).
* **Suggestion for Nebius**: Add fine-tuning / system-prompt alignment in the Token Factory proxy layer for Nemotron to strictly enforce standard OpenAI array schema:
  ```json
  "tool_calls": [
    {"id": "call_1", "type": "function", "function": {"name": "add_task", "arguments": "..."}},
    {"id": "call_2", "type": "function", "function": {"name": "verify_deadline", "arguments": "..."}}
  ]
  ```

---

### 3.4 Model Warmth / Cold-Start Telemetry Headers
* **Context**: Ultra-large models like `Nemotron-3-Ultra-550b` provide incredible reasoning, but latency can spike if an instance has scaled down or is cold-starting.
* **Suggestion for Nebius**: Expose custom HTTP response headers (e.g., `x-nebius-worker-status: warm|cold`, `x-nebius-inference-latency-ms: 124`, `x-nebius-gpu: H100-SXM5`). This empowers agent frameworks to dynamically adjust client timeouts or failover gracefully to smaller models when cold starts occur.

---

## 4. Feature Wishlist for Agentic Builders

| Feature | Impact for Developers | Priority |
| :--- | :--- | :--- |
| **Native Matryoshka Slicing (`dimensions` param)** | Eliminates client-side L2 re-normalization for `pgvector` compatibility. | High |
| **Streaming `include_usage` Support** | Precise token telemetry without local tokenizer approximation. | High |
| **Private VPC Peering between Nebius Compute & Token Factory** | Sub-millisecond internal routing for high-frequency agent loops. | Medium |
| **Native Structured Outputs (`response_format: {"type": "json_schema"}`)** | 100% deterministic schema compliance for autonomous agent loops. | High |
| **Built-in Prompt Caching** | Reduces costs for long agent system prompts with repetitive tool definitions. | Medium |

---

## 5. Conclusion & Verification

Nebius Token Factory combined with NVIDIA Nemotron architecture provides one of the fastest, most cost-effective open-weights inference platforms available today. By addressing the embedding dimension parameter and streaming usage options, Nebius can solidify its position as the premier platform for production-grade agentic AI.

We have integrated full live telemetry inside Compass under the **⚡ Nebius & NVIDIA Telemetry** inspector (accessible via the web dashboard at `https://compass-farmlytics.vercel.app` or via `GET /api/telemetry`), demonstrating these measurements in real time.

*Thank you to the Nebius and NVIDIA teams for hosting this incredible hackathon and providing world-class infrastructure!*
