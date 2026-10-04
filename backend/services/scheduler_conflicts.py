"""
Compass — Dynamic Schedule Conflict Detection and Reactive Replanning.
Scans for time overlaps, dependency order violations, deadline violations, and replans slipped tasks.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.services.cognitive_conflicts import _ensure_utc

logger = logging.getLogger("compass.scheduler_conflicts")


def find_slipped_tasks(
    tasks: Sequence[Dict[str, Any]],
    current_time: Optional[datetime | str] = None,
) -> List[Dict[str, Any]]:
    """Detect tasks that were scheduled to end before current_time but are not marked 'done'."""
    now_utc = _ensure_utc(current_time) if current_time else datetime.now(timezone.utc)
    slipped: List[Dict[str, Any]] = []

    for t in tasks:
        status = str(t.get("status", "open")).lower().strip()
        if status in ("done", "completed", "closed"):
            continue

        sched_end = t.get("scheduled_end")
        if not sched_end:
            continue

        end_utc = _ensure_utc(sched_end)
        if end_utc < now_utc:
            slipped.append({
                **dict(t),
                "scheduled_end_utc": end_utc.isoformat(),
                "slip_minutes": max(0, int((now_utc - end_utc).total_seconds() // 60)),
            })

    return slipped


def replan_slipped_tasks(
    slipped_tasks: Sequence[Dict[str, Any]],
    all_tasks: Sequence[Dict[str, Any]],
    dependencies: Optional[Mapping[int, Sequence[int]]] = None,
    available_windows: Sequence[Any] = (),
    buffer_minutes: int = 15,
) -> Dict[str, Any]:
    """Re-scope and replan slipped tasks and all downstream dependents. Preserves unaffected tasks."""
    from backend.services.scheduler import allocate_task_slots

    if not slipped_tasks:
        return {
            "slipped_task_ids": [],
            "affected_task_ids": [],
            "rescheduled": [],
            "unassigned": [],
            "conflicts": [],
            "summary": "No slipped tasks to replan.",
        }

    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for k, v in dependencies.items():
            dep_map[int(k)] = [int(x) for x in v]

    for t in all_tasks:
        tid = t.get("id")
        if tid is not None and t.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in t["depends_on"]])

    downstream_map: Dict[int, List[int]] = {}
    for child, parents in dep_map.items():
        for parent in parents:
            downstream_map.setdefault(parent, []).append(child)

    slipped_ids = {int(t["id"]) for t in slipped_tasks if t.get("id") is not None}
    affected_ids = set(slipped_ids)
    queue = list(slipped_ids)
    while queue:
        curr = queue.pop(0)
        for child_id in downstream_map.get(curr, []):
            if child_id not in affected_ids:
                affected_ids.add(child_id)
                queue.append(child_id)

    task_by_id = {int(t["id"]): t for t in all_tasks if t.get("id") is not None}
    for st in slipped_tasks:
        if st.get("id") is not None:
            task_by_id[int(st["id"])] = st

    tasks_to_replan = [task_by_id[tid] for tid in affected_ids if tid in task_by_id]

    existing_scheduled: Dict[int, Dict[str, Any]] = {}
    for t in all_tasks:
        tid = t.get("id")
        if tid is not None and int(tid) not in affected_ids and t.get("scheduled_start") and t.get("scheduled_end"):
            existing_scheduled[int(tid)] = {
                "scheduled_start": _ensure_utc(t["scheduled_start"]),
                "scheduled_end": _ensure_utc(t["scheduled_end"]),
            }

    allocation = allocate_task_slots(
        tasks=tasks_to_replan,
        available_windows=available_windows,
        buffer_minutes=buffer_minutes,
        dependencies=dep_map,
        existing_scheduled_map=existing_scheduled,
    )

    downstream_count = max(0, len(affected_ids) - len(slipped_ids))
    return {
        "slipped_task_ids": sorted(list(slipped_ids)),
        "affected_task_ids": sorted(list(affected_ids)),
        "rescheduled": allocation["scheduled"],
        "unassigned": allocation["unassigned"],
        "conflicts": allocation["conflicts"],
        "summary": f"Replanned {len(allocation['scheduled'])} tasks ({len(slipped_ids)} slipped, {downstream_count} downstream dependents).",
    }


def detect_schedule_conflicts(
    scheduled_tasks: Sequence[Dict[str, Any]],
    external_events: Optional[Sequence[Dict[str, Any]]] = None,
    dependencies: Optional[Mapping[int, Sequence[int]]] = None,
    current_time: Optional[datetime | str] = None,
    buffer_minutes: int = 15,
) -> List[Dict[str, Any]]:
    """Scan scheduled tasks, dependencies, and external events for conflicts."""
    conflicts: List[Dict[str, Any]] = []
    buf_delta = timedelta(minutes=buffer_minutes)
    now_utc = _ensure_utc(current_time) if current_time else datetime.now(timezone.utc)

    task_map: Dict[int, Dict[str, Any]] = {}
    for st in scheduled_tasks:
        tid = st.get("id") or st.get("task_id")
        if tid is not None:
            task_map[int(tid)] = st

    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for k, v in dependencies.items():
            dep_map[int(k)] = [int(x) for x in v]
    for st in scheduled_tasks:
        tid = st.get("id") or st.get("task_id")
        if tid is not None and st.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in st["depends_on"]])

    # 1. Overlap detection
    items: List[Tuple[datetime, datetime, Dict[str, Any], str]] = []
    for st in scheduled_tasks:
        if st.get("scheduled_start") and st.get("scheduled_end"):
            start = _ensure_utc(st["scheduled_start"])
            end = _ensure_utc(st["scheduled_end"])
            items.append((start, end, st, "task"))

    if external_events:
        for ev in external_events:
            ev_start = ev.get("start") or ev.get("scheduled_start")
            ev_end = ev.get("end") or ev.get("scheduled_end")
            if ev_start is not None and ev_end is not None:
                try:
                    start = _ensure_utc(ev_start)
                    end = _ensure_utc(ev_end)
                    items.append((start, end, ev, "external"))
                except Exception:
                    continue

    items.sort(key=lambda x: x[0])

    for i in range(len(items)):
        start_a, end_a, data_a, type_a = items[i]
        for j in range(i + 1, len(items)):
            start_b, end_b, data_b, type_b = items[j]
            if start_b < end_a:
                conflicts.append({
                    "conflict_type": "overlap",
                    "event_a": {"type": type_a, "id": data_a.get("id") or data_a.get("task_id"), "title": data_a.get("title")},
                    "event_b": {"type": type_b, "id": data_b.get("id") or data_b.get("task_id"), "title": data_b.get("title")},
                    "overlap_window": {"start": start_b.isoformat(), "end": min(end_a, end_b).isoformat()},
                })
            else:
                break

    # 2. Dependency timing violations
    for child_id, prereq_ids in dep_map.items():
        child = task_map.get(child_id)
        if not child or not child.get("scheduled_start"):
            continue
        child_start = _ensure_utc(child["scheduled_start"])

        for pid in prereq_ids:
            parent = task_map.get(pid)
            if not parent:
                continue
            if not parent.get("scheduled_end"):
                conflicts.append({
                    "conflict_type": "dependency_violation",
                    "task_id": child_id,
                    "task_title": child.get("title"),
                    "prerequisite_id": pid,
                    "prerequisite_title": parent.get("title"),
                    "issue": f"Task '{child.get('title')}' is scheduled, but prerequisite '{parent.get('title')}' has no scheduled time.",
                })
                continue

            parent_end = _ensure_utc(parent["scheduled_end"])
            if child_start < (parent_end + buf_delta):
                conflicts.append({
                    "conflict_type": "dependency_violation",
                    "task_id": child_id,
                    "task_title": child.get("title"),
                    "prerequisite_id": pid,
                    "prerequisite_title": parent.get("title"),
                    "issue": f"Task '{child.get('title')}' starts at {child_start.isoformat()} before prerequisite '{parent.get('title')}' completes with buffer at {(parent_end + buf_delta).isoformat()}.",
                })

    # 3. Deadline violations
    for st in scheduled_tasks:
        if st.get("due_date") and st.get("scheduled_end"):
            sched_end = _ensure_utc(st["scheduled_end"])
            raw_due = st["due_date"]
            if isinstance(raw_due, str):
                d_obj = date.fromisoformat(raw_due[:10])
                due_limit = datetime.combine(d_obj, time(23, 59, 59), tzinfo=timezone.utc)
            elif isinstance(raw_due, date) and not isinstance(raw_due, datetime):
                due_limit = datetime.combine(raw_due, time(23, 59, 59), tzinfo=timezone.utc)
            else:
                due_limit = _ensure_utc(raw_due)

            if sched_end > due_limit:
                conflicts.append({
                    "conflict_type": "deadline_exceeded",
                    "task_id": st.get("id") or st.get("task_id"),
                    "title": st.get("title"),
                    "due_date": str(st["due_date"]),
                    "scheduled_end": sched_end.isoformat(),
                    "issue": f"Task '{st.get('title')}' finishes after its due date ({st.get('due_date')}).",
                })

    # 4. Slipped uncompleted tasks
    for st in scheduled_tasks:
        status = str(st.get("status", "open")).lower().strip()
        if status not in ("done", "completed", "closed") and st.get("scheduled_end"):
            sched_end = _ensure_utc(st["scheduled_end"])
            if sched_end < now_utc:
                conflicts.append({
                    "conflict_type": "slipped_deadline",
                    "task_id": st.get("id") or st.get("task_id"),
                    "title": st.get("title"),
                    "scheduled_end": sched_end.isoformat(),
                    "slip_minutes": int((now_utc - sched_end).total_seconds() // 60),
                    "issue": f"Task '{st.get('title')}' scheduled end was in the past ({sched_end.isoformat()}) but task remains {status}.",
                })

    return conflicts
