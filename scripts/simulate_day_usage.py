"""
Simulate a realistic day of actual multi-domain usage against the live Compass backend.
"""
import os
import sys
import time
import httpx

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

BACKEND_URL = os.getenv("COMPASS_API_URL", "https://compass-backend-qryu.onrender.com")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "dev-token")
HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}

def run_simulation():
    print(f"Connecting to live backend: {BACKEND_URL}")
    client = httpx.Client(base_url=BACKEND_URL, headers=HEADERS, timeout=90.0)

    # 1. Health check
    resp = client.get("/health")
    print(f"Health check: {resp.status_code} -> {resp.json()}")

    # 2. Log Code Context (3 logs -> Qwen3 embeddings via /api/log)
    logs_to_add = [
        {"content": "Configured pgvector HNSW index with vector_cosine_ops and 768-dim Matryoshka truncation on memory_chunks table", "project": "compass", "tags": "database,pgvector"},
        {"content": "Added FastAPI streaming endpoint with text/event-stream for real-time SSE token delivery to the frontend", "project": "compass", "tags": "fastapi,streaming"},
        {"content": "Implemented exponential backoff retry decorator in backend/services/nebius.py for RateLimitError handling", "project": "compass", "tags": "resilience,python"},
    ]
    for i, log in enumerate(logs_to_add, 1):
        print(f"\n[Log Context {i}] {log['content'][:60]}...")
        r = client.post("/api/log", json=log)
        print(f"  Status: {r.status_code}, Response: {r.text[:100]}")
        time.sleep(1.5)

    # 3. Interactive Chat Calls (Task adds, Task queries, Coursework queries, Code queries, Ultra synthesis, Chat fallbacks)
    chat_calls = [
        # Task additions via Router
        ("Task Add 1 (Hackathon)", "Add a new hackathon task: Finalize demo video and benchmark slide deck due 2026-09-09 with high priority"),
        ("Task Add 2 (Coursework)", "Add a coursework task: Complete CS 61C Logisim ALU design lab due 2026-09-12"),
        ("Task Add 3 (Code)", "Add a code task: Optimize database connection pool settings in config.py due 2026-09-15"),
        
        # Task Queries
        ("Task Query 1", "What tasks are currently open across all my projects?"),
        ("Task Query 2", "What are my upcoming hackathon deliverables and deadlines?"),
        
        # Coursework Queries
        ("Coursework Query 1", "Check my open coursework tasks and labs for CS 61C"),
        ("Coursework Query 2", "What coursework assignments and project deliverables are pending?"),
        
        # Code Context Queries (Nemotron-3 Super synthesis)
        ("Code Query 1 (Super)", "Search our code memory for how we handle Matryoshka embedding dimensions and pgvector indexing"),
        ("Code Query 2 (Super)", "Look up our code notes on how SSE streaming is implemented in the FastAPI backend"),
        
        # Cross-Domain Executive Synthesis (Nemotron-3 Ultra synthesis)
        ("Executive Synthesis (Ultra)", "Summarize my day and give me an executive daily standup briefing across all my hackathon, coursework, and coding projects."),
        
        # Casual / General Chat Fallbacks
        ("General Chat 1", "Good morning Compass! What capabilities do you have?"),
        ("General Chat 2", "Thanks for the help! Can you give me tips on balancing hackathons with university coursework?"),
    ]

    for label, prompt in chat_calls:
        print(f"\n[Chat: {label}]")
        print(f"  Prompt: '{prompt}'")
        try:
            r = client.post("/api/chat", json={"message": prompt})
            if r.status_code == 200:
                data = r.json()
                skill = data.get("skill_called")
                resp_snippet = data.get("response", "")[:150].replace("\n", " ")
                print(f"  Skill Called: {skill}")
                print(f"  Response: {resp_snippet}...")
            else:
                print(f"  Failed: {r.status_code} - {r.text}")
        except Exception as e:
            print(f"  Error: {e}")
        time.sleep(2.0)

    print("\n--- Simulation Complete ---")

if __name__ == "__main__":
    run_simulation()
