import os
import json
import time
import urllib.request
import dotenv

dotenv.load_dotenv()
api_key = os.environ.get("NEBIUS_API_KEY", "")
base_url = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1").rstrip("/")

models_to_test = [
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
]

tools = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Create a new deadline or task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the task"},
                    "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD"},
                    "domain": {"type": "string", "enum": ["hackathon", "coursework", "code", "general"]}
                },
                "required": ["title"]
            }
        }
    }
]

print("======================================================================")
print("TOOL-CALLING SMOKE TEST PER ROUTED MODEL")
print("======================================================================")

for model_id in models_to_test:
    print(f"\n--- Testing Model: {model_id} ---")
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You are Compass. Use the provided tools when requested."},
            {"role": "user", "content": "Please add a task titled 'Submit Hackathon Project' due 2026-10-30 in domain hackathon."}
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req) as resp:
            dur = time.time() - t0
            raw = json.loads(resp.read().decode())
            choice = raw["choices"][0]
            message = choice["message"]
            tool_calls = message.get("tool_calls") or []
            print(f"Status: HTTP {resp.status} OK | Latency: {dur:.2f}s")
            print(f"Tool calls emitted: {len(tool_calls)}")
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    print(f"  Tool Name: {fn.get('name')}")
                    print(f"  Arguments: {fn.get('arguments')}")
            else:
                print(f"  Response text (no tool call): {message.get('content')[:150]}")
    except urllib.error.HTTPError as e:
        dur = time.time() - t0
        print(f"Status: HTTP {e.code} | Latency: {dur:.2f}s | Error: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"Error: {e}")
