import json
import httpx
import io
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://compass-backend-qryu.onrender.com"
RUN_URL = f"{BASE_URL}/api/agent/run"

goals = [
    ("a", "Can I finish everything across all my domains today?"),
    ("b", "Can I finish all my hackathon and coursework deliverables in 1 hour per day this week?"),
    ("c", "What's my full workload look like if I only have 2 hours today?"),
]

for label, goal in goals:
    print(f"\n==================================================")
    print(f"Goal {label}: '{goal}'")
    print(f"==================================================")
    with httpx.Client(timeout=180.0) as client:
        with client.stream("POST", RUN_URL, json={"goal": goal}) as resp:
            tool_call_step = None
            observe_step = None
            synthesize_step = None
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    try:
                        ev = json.loads(line[5:])
                        t = ev.get("type")
                        tool = ev.get("tool") or ev.get("tool_name")
                        if t == "tool_call" and tool == "assess_feasibility":
                            tool_call_step = ev
                            print(f"[TOOL_CALL] assess_feasibility args: {json.dumps(ev.get('args'))}")
                        elif t == "observe" and tool == "assess_feasibility":
                            observe_step = ev
                            print(f"[OBSERVE] assess_feasibility:")
                            print(ev.get("content"))
                        elif t == "synthesize":
                            synthesize_step = ev
                            print(f"[SYNTHESIZE]:\n{ev.get('content')}")
                    except Exception as e:
                        pass
