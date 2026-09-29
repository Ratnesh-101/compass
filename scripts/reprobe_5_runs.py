import io
import httpx
import json
import time
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://compass-backend-qryu.onrender.com/api/agent/run"
HEALTH_URL = "https://compass-backend-qryu.onrender.com/health"
GOAL = "What is the official submission deadline date for the Nebius x NVIDIA AI Hackathon on Devpost?"

def get_live_health():
    with httpx.Client(timeout=30.0) as client:
        r = client.get(HEALTH_URL)
        return r.json()

def run_probe(run_idx: int):
    print(f"\n--- Starting Probe Run {run_idx} ---", flush=True)
    events = []
    
    with httpx.Client(timeout=180.0) as client:
        with client.stream("POST", URL, json={"goal": GOAL}) as response:
            for line in response.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw_data = line[5:].strip()
                    try:
                        parsed = json.loads(raw_data)
                        events.append(parsed)
                    except Exception:
                        pass

    run_id = None
    step_types = []
    tools_used = []
    final_answer = ""
    web_escalation_used = False
    tavily_abstain_first = False

    for ev in events:
        st_type = ev.get("type")
        if st_type:
            step_types.append(st_type)
        if not run_id and ev.get("run_id"):
            run_id = ev.get("run_id")
        if ev.get("tool"):
            t_name = ev.get("tool")
            if t_name not in tools_used:
                tools_used.append(t_name)
        if st_type == "synthesize":
            final_answer = ev.get("content", "")
            meta = ev.get("metadata") or {}
            if meta.get("web_escalation_used"):
                web_escalation_used = True
        if st_type == "done":
            meta = ev.get("metadata") or {}
            rc = meta.get("report_card") or {}
            if "tavily_abstain_first" in rc:
                tavily_abstain_first = rc["tavily_abstain_first"]
            elif "tavily_abstain_first" in meta:
                tavily_abstain_first = meta["tavily_abstain_first"]
        if st_type == "escalate":
            web_escalation_used = True

    return {
        "run_idx": run_idx,
        "run_id": run_id,
        "tavily_abstain_first": tavily_abstain_first,
        "step_types": step_types,
        "tools_used": tools_used,
        "web_escalation_used": web_escalation_used,
        "final_answer": final_answer,
    }

if __name__ == "__main__":
    health = get_live_health()
    print("LIVE HEALTH:")
    print(json.dumps(health))
    print(f"Live Commit: {health.get('commit')}")

    results = []
    for i in range(1, 6):
        res = run_probe(i)
        results.append(res)
        print(f"Run {i}")
        print(f"run_id: {res['run_id']} tavily_abstain_first: {str(res['tavily_abstain_first']).lower()} ordered step types: {', '.join(res['step_types'])} tools_used: {res['tools_used']} web_escalation_used: {res['web_escalation_used']} final answer: {res['final_answer']}\n", flush=True)
        time.sleep(2)
