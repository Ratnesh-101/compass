# Compass — 3-Minute Demo Video Script

* **Target Duration**: 3:00 minutes
* **Audience**: Hackathon judges, software engineers, dev community
* **Goal**: Prove real-time multi-domain capture, sub-400ms routing with Nemotron Nano, lossless 768-dim vector memory, and cross-domain synthesis.

---

## Shot-by-Shot Sequence

| Timestamp | Surface | Action & Screen Content | Key Narrative & Audio Script |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:45** | **Terminal (CLI)** | 1. Run `compass status` showing active multi-domain counts (Hackathon 🚀, Coursework 📚, Code 💻).<br/>2. Run `compass log "Configured Matryoshka 768-dim embeddings with Nebius Token Factory" --domain code --project "Compass" --tags nebius,vector`. | *"As developers, researchers, and students, we constantly suffer from context switching fatigue. We jump from hackathons to university coursework to scattered repos, and standard LLMs forget everything between sessions. Meet Compass: your persistent personal AI assistant, powered by Nebius Token Factory and NVIDIA Nemotron models. One shared brain, accessible from your terminal or browser."* |
| **0:45 – 1:45** | **Browser (UI)** | 1. Open `http://localhost:5173`.<br/>2. Inspect sidebar metrics updating dynamically.<br/>3. Navigate to **Timeline** view showing the newly logged vector chunk from the CLI alongside countdown badges. | *"Everything you log in the terminal is instantly synchronized to your web dashboard. Notice the visual domain isolation: amber for high-stakes hackathons, blue for coursework deadlines, and green for code context. In the background, Nebius Token Factory embedded our snippet using Qwen3-Embedding at 768 dimensions, stored natively in Neon Serverless PostgreSQL with an HNSW index."* |
| **1:45 – 2:30** | **Browser (Chat)** | 1. Open Chat panel.<br/>2. Type: *"What are my top deliverables across coursework and hackathon before Friday?"*<br/>3. Watch response stream with parsed tasks, domain badges, and next steps. | *"When you ask a complex question, NVIDIA Nemotron-3 Nano handles routing in under 400ms using native OpenAI function calling. It dispatches to our specialized skills, pulls from structured memory and pgvector, and escalates to Nemotron-3 Ultra to synthesize a cohesive daily roadmap across all domains."* |
| **2:30 – 3:00** | **Terminal / UI** | 1. Switch to terminal: run `compass admin usage`.<br/>2. Show model breakdown table with total cost under a few cents.<br/>3. Display Mermaid architecture diagram from `README.md`. | *"Finally, full transparency: running `compass admin usage` breaks down our actual Token Factory cost across Nano, Super, and Ultra. By leveraging Matryoshka 768-dimension truncation, we stay within pgvector's HNSW index ceiling while getting 100% Top-1 recall. Compass gives you persistent cognitive memory without the latency or cost overhead."* |

---

## Recording Checklist
- [ ] Backend running: `uvicorn backend.main:app --port 8000` (or `docker compose up`)
- [ ] Frontend running: `npm run dev` in `frontend/` (accessible at `http://localhost:5173`)
- [ ] Database seeded: `python scripts/seed_data.py`
- [ ] Terminal window formatted cleanly with high-contrast font
- [ ] Audio normalized with clear microphone input
