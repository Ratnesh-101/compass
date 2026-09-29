import json
import httpx
import time
import io
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://compass-backend-qryu.onrender.com"
HEALTH_URL = f"{BASE_URL}/health"
RUN_URL = f"{BASE_URL}/api/agent/run"
TASKS_URL = f"{BASE_URL}/api/tasks"

def get_health():
    with httpx.Client(timeout=30.0) as client:
        return client.get(HEALTH_URL).json()

def get_tasks_count():
    with httpx.Client(timeout=30.0) as client:
        return len(client.get(TASKS_URL).json())

def run_pillar2():
    print("=" * 60)
    print("PILLAR 2 LIVE TRACE: CONFIRM-GATE & RE-PLAN")
    print("=" * 60)
    
    count_before = get_tasks_count()
    print(f"DB tasks count BEFORE Pillar 2: {count_before}")
    
    goal = "Reschedule my coursework tasks to finish the hackathon demo today"
    events_turn1 = []
    
    print(f"\n[Turn 1] Submitting goal: '{goal}'")
    with httpx.Client(timeout=180.0) as client:
        with client.stream("POST", RUN_URL, json={"goal": goal, "wait_for_confirmation": False}) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        events_turn1.append(ev)
                    except Exception:
                        pass
                        
    print(f"Turn 1 received {len(events_turn1)} SSE steps:")
    run_id = None
    confirm_ev = None
    mutating_tool_args = None
    
    for ev in events_turn1:
        st_num = ev.get("step_number")
        st_type = ev.get("type")
        tool = ev.get("tool_name") or ev.get("tool")
        content = str(ev.get("content", ""))
        content_preview = content[:120] if content else ""
        print(f"  Step {st_num} [{st_type}] tool={tool}: {content_preview}")
        
        if not run_id and ev.get("run_id"):
            run_id = ev.get("run_id")
        if st_type == "confirm_request":
            confirm_ev = ev
            mutating_tool_args = ev.get("tool_args")
            print(f"    >>> CONFIRM_REQUEST DETECTED!")
            print(f"    >>> Tool: {ev.get('tool_name')}")
            print(f"    >>> Tool Args: {json.dumps(mutating_tool_args, indent=6)}")

    count_after_turn1 = get_tasks_count()
    print(f"\nDB tasks count AFTER Turn 1 confirm_request: {count_after_turn1}")
    print(f"Zero DB writes confirmed: {count_before == count_after_turn1}")
    
    # Turn 2: Rejection with feedback
    feedback = "Do not postpone Lab 3 submission — Two-stage pipelined CPU in Logisim"
    print(f"\n[Turn 2] Submitting rejection for run_id={run_id} with feedback: '{feedback}'")
    events_turn2 = []
    with httpx.Client(timeout=180.0) as client:
        payload = {
            "goal": goal,
            "run_id": run_id,
            "action": "reject",
            "feedback": feedback,
        }
        with client.stream("POST", RUN_URL, json=payload) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        events_turn2.append(ev)
                    except Exception:
                        pass
                        
    print(f"Turn 2 received {len(events_turn2)} SSE steps:")
    for ev in events_turn2:
        st_num = ev.get("step_number")
        st_type = ev.get("type")
        tool = ev.get("tool_name") or ev.get("tool")
        content = str(ev.get("content", ""))
        content_preview = content[:120] if content else ""
        print(f"  Step {st_num} [{st_type}] tool={tool}: {content_preview}")
        if ev.get("metadata") and ev["metadata"].get("replan_diff"):
            print(f"    >>> Replan diff: {json.dumps(ev['metadata']['replan_diff'])}")

    count_final = get_tasks_count()
    print(f"\nDB tasks count AFTER Turn 2 replan sequence: {count_final}")
    print(f"DB tasks table unchanged: {count_final == count_before} (count: {count_final})")
    
    return {
        "count_before": count_before,
        "count_after_turn1": count_after_turn1,
        "count_final": count_final,
        "run_id": run_id,
        "events_turn1": events_turn1,
        "confirm_ev": confirm_ev,
        "events_turn2": events_turn2,
    }

def run_pillar3():
    print("\n" + "=" * 60)
    print("PILLAR 3 LIVE TRACE: FEASIBILITY REVIEW")
    print("=" * 60)
    
    goal = "Can I finish all 6 hackathon deliverables in 2 hours per day this week?"
    print(f"Submitting goal: '{goal}'")
    
    events = []
    with httpx.Client(timeout=180.0) as client:
        with client.stream("POST", RUN_URL, json={"goal": goal}) as resp:
            for line in resp.iter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        ev = json.loads(raw)
                        events.append(ev)
                    except Exception:
                        pass
                        
    print(f"Received {len(events)} SSE steps:")
    assess_tool_call = None
    assess_observe = None
    synthesize_step = None
    
    for ev in events:
        st_num = ev.get("step_number")
        st_type = ev.get("type")
        tool = ev.get("tool_name") or ev.get("tool")
        content = str(ev.get("content", ""))
        print(f"  Step {st_num} [{st_type}] tool={tool}: {content[:100]}")
        
        if st_type == "tool_call" and tool == "assess_feasibility":
            assess_tool_call = ev
        if st_type == "observe" and tool == "assess_feasibility":
            assess_observe = ev
        if st_type == "synthesize":
            synthesize_step = ev
            
    print("\n--- RAW ASSESS_FEASIBILITY TOOL CALL ---")
    print(json.dumps(assess_tool_call, indent=2))
    
    print("\n--- RAW ASSESS_FEASIBILITY OBSERVE / RETURNED NUMBERS ---")
    if assess_observe:
        print("Content / Summary:")
        print(assess_observe.get("content"))
        if assess_observe.get("metadata"):
            print("Metadata:")
            print(json.dumps(assess_observe.get("metadata"), indent=2))
            
    print("\n--- FINAL SYNTHESIZED ANSWER ---")
    if synthesize_step:
        print(synthesize_step.get("content"))
        
    return {
        "events": events,
        "assess_tool_call": assess_tool_call,
        "assess_observe": assess_observe,
        "synthesize_step": synthesize_step,
    }

if __name__ == "__main__":
    health = get_health()
    print("LIVE HEALTH:")
    print(json.dumps(health, indent=2))
    
    p2_res = run_pillar2()
    p3_res = run_pillar3()
