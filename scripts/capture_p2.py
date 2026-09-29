import json
import httpx
import io
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://compass-backend-qryu.onrender.com"
RUN_URL = f"{BASE_URL}/api/agent/run"

def test_turn1():
    goal = "Reschedule my coursework tasks to finish the hackathon demo today"
    print(f"Submitting goal: {goal}")
    with httpx.Client(timeout=180.0) as client:
        with client.stream("POST", RUN_URL, json={"goal": goal, "wait_for_confirmation": False}) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        t = ev.get("type")
                        tool = ev.get("tool_name") or ev.get("tool")
                        print(f"Step type={t}, tool={tool}")
                        if t == "confirm_request":
                            print("\n*** FULL CONFIRM_REQUEST ***")
                            print(json.dumps(ev, indent=2))
                            print("****************************\n")
                        elif t == "tool_call":
                            print(f"   args: {json.dumps(ev.get('args'))}")
                        elif t == "synthesize":
                            print(f"   synthesize: {ev.get('content')[:200]}")
                    except Exception as e:
                        pass

if __name__ == "__main__":
    test_turn1()
