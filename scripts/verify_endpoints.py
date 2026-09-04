import urllib.request
import json

base_url = "http://localhost:8001"

# 1. Health
with urllib.request.urlopen(f"{base_url}/health") as res:
    health = json.loads(res.read().decode())
    print(f"1. GET /health: status={health.get('status')}, db_connected={health.get('db_connected')}")

# 2. Tasks
with urllib.request.urlopen(f"{base_url}/api/tasks") as res:
    tasks = json.loads(res.read().decode())
    print(f"2. GET /api/tasks: {len(tasks)} tasks returned. Sample: {tasks[0]['title']} [{tasks[0]['countdown']}]")

# 3. Chat
chat_body = json.dumps({"message": "What are my deliverables before Friday?"}).encode()
req_chat = urllib.request.Request(f"{base_url}/api/chat", data=chat_body, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req_chat) as res:
    chat = json.loads(res.read().decode())
    print(f"3. POST /api/chat: latency={chat.get('routing_latency_ms')}ms, skill={chat.get('skill_used')}")

# 4. Log
log_body = json.dumps({
    "summary": "Verified Nebius 768-dim embeddings with HNSW pgvector",
    "domain": "code",
    "project": "Compass",
    "tags": "nebius,vector,test"
}).encode()
req_log = urllib.request.Request(
    f"{base_url}/api/log",
    data=log_body,
    headers={"Content-Type": "application/json", "Authorization": "Bearer dev-token"}
)
with urllib.request.urlopen(req_log) as res:
    log_res = json.loads(res.read().decode())
    print(f"4. POST /api/log: status={log_res.get('status')}, message={log_res.get('message')}")
