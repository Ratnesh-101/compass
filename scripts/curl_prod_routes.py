import urllib.request
import urllib.error
import json

routes = [
    ("GET", "/tasks"),
    ("POST", "/tasks", {"title": "Test Task"}),
    ("DELETE", "/tasks/test-id-123"),
    ("POST", "/tasks/verify-deadlines", {}),
    ("POST", "/tasks/test-id-123/verify", {}),
    ("GET", "/projects"),
    ("GET", "/dashboard"),
    ("GET", "/memory/timeline"),
    ("POST", "/chat", {"message": "hello"}),
    ("GET", "/conversations/00000000-0000-0000-0000-000000000000/messages"),
    ("GET", "/api/agent/critique-stats"),
    ("POST", "/api/agent/trigger-nightly", {}),
    ("POST", "/api/specialist/dispatch", {"capability": "memory", "user_goal": "test"}),
    ("GET", "/api/telemetry"),
    ("GET", "/api/usage/summary"),
    ("POST", "/api/demo/seed", {}),
]

base_url = "https://compass-backend-qryu.onrender.com"

print(f"{'METHOD':<7} | {'ROUTE':<45} | {'STATUS':<6} | {'BODY (FIRST 80 CHARS)'}")
print("-" * 100)

for item in routes:
    method = item[0]
    path = item[1]
    data = json.dumps(item[2]).encode() if len(item) > 2 and item[2] is not None else None
    
    url = f"{base_url}{path}"
    headers = {"User-Agent": "ProbeScript/1.0"}
    if data:
        headers["Content-Type"] = "application/json"
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode(errors="ignore")
            print(f"{method:<7} | {path:<45} | {resp.status:<6} | {body[:80]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        print(f"{method:<7} | {path:<45} | {e.code:<6} | {body[:80]}")
    except Exception as e:
        print(f"{method:<7} | {path:<45} | {'ERR':<6} | {str(e)[:80]}")
