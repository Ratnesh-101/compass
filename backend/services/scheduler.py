"""
Compass — Deterministic Dynamic Scheduling Engine.

Provides pure Python interval arithmetic for packing tasks into calendar time slots.
Guarantees 0% LLM hallucination in time calculations, working hour boundaries,
inter-task buffers, and deadline satisfaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import logging
import re

logger = logging.getLogger("compass.scheduler")

PRIORITY_WEIGHTS: Dict[str, int] = {
    "urgent": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _ensure_utc(dt: datetime | str | date | Dict[str, Any]) -> datetime:
    """Normalize input datetime to UTC timezone-aware datetime."""
    if isinstance(dt, dict):
        raw = dt.get("dateTime") or dt.get("date") or dt.get("start") or dt.get("end")
        if raw is not None:
            return _ensure_utc(raw)
        raise ValueError(f"Cannot extract datetime from dict: {dt}")
    if isinstance(dt, str):
        # Handle ISO strings
        clean_str = dt.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(clean_str)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            # Fallback to date parsing
            d = date.fromisoformat(clean_str[:10])
            return datetime.combine(d, time.min, tzinfo=timezone.utc)
    elif isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime.combine(dt, time.min, tzinfo=timezone.utc)
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError(f"Cannot convert {type(dt)} to UTC datetime")


def _parse_time_str(t_val: str | time) -> time:
    """Parse HH:MM:SS or HH:MM string to datetime.time."""
    if isinstance(t_val, time):
        return t_val
    parts = str(t_val).split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return time(hour=h, minute=m, second=s)


@dataclass
class TimeWindow:
    """A contiguous interval of available or busy time."""
    start: datetime
    end: datetime
    label: Optional[str] = None
    is_busy: bool = False

    def __post_init__(self) -> None:
        self.start = _ensure_utc(self.start)
        self.end = _ensure_utc(self.end)
        if self.end < self.start:
            raise ValueError(f"Window end ({self.end}) cannot precede start ({self.start})")

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def merge_overlapping_intervals(intervals: Sequence[TimeWindow]) -> List[TimeWindow]:
    """Merge overlapping or contiguous busy intervals."""
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda w: w.start)
    merged: List[TimeWindow] = [sorted_intervals[0]]

    for current in sorted_intervals[1:]:
        prev = merged[-1]
        if current.start <= prev.end:
            # Overlap or contiguous -> extend previous
            merged[-1] = TimeWindow(
                start=prev.start,
                end=max(prev.end, current.end),
                label=prev.label or current.label,
                is_busy=prev.is_busy or current.is_busy,
            )
        else:
            merged.append(current)

    return merged


def get_available_windows(
    busy_intervals: Sequence[TimeWindow | Dict[str, Any]],
    search_start: datetime | str,
    search_end: datetime | str,
    work_start_time: str | time = "09:00:00",
    work_end_time: str | time = "18:00:00",
    work_days: Optional[Sequence[int]] = None,
    buffer_minutes: int = 15,
) -> List[TimeWindow]:
    """Calculate free working-hour windows by subtracting busy intervals from daily working hours.

    Args:
        busy_intervals: External events or existing fixed tasks.
        search_start: Start of scheduling horizon.
        search_end: End of scheduling horizon.
        work_start_time: Daily start of working hours (default 09:00).
        work_end_time: Daily end of working hours (default 18:00).
        work_days: Allowed weekdays (1=Mon, 7=Sun). Default Monday-Friday [1,2,3,4,5].
        buffer_minutes: Safety buffer around busy events (default 15m).

    Returns:
        List of available TimeWindow intervals within working hours.
    """
    start_utc = _ensure_utc(search_start)
    end_utc = _ensure_utc(search_end)
    w_start = _parse_time_str(work_start_time)
    w_end = _parse_time_str(work_end_time)
    allowed_days = set(work_days if work_days is not None else [1, 2, 3, 4, 5])

    # Convert raw dicts or objects into TimeWindow instances with buffer expansion
    normalized_busy: List[TimeWindow] = []
    buf_td = timedelta(minutes=buffer_minutes)

    for item in busy_intervals:
        if isinstance(item, TimeWindow):
            b_start = item.start - buf_td
            b_end = item.end + buf_td
            label = item.label
        elif isinstance(item, dict):
            raw_start = item.get("start") or item.get("scheduled_start")
            raw_end = item.get("end") or item.get("scheduled_end")
            if raw_start is None or raw_end is None:
                continue
            b_start = _ensure_utc(raw_start) - buf_td
            b_end = _ensure_utc(raw_end) + buf_td
            label = item.get("title") or item.get("label")
        else:
            continue

        if b_end > b_start:
            normalized_busy.append(TimeWindow(start=b_start, end=b_end, label=label, is_busy=True))

    merged_busy = merge_overlapping_intervals(normalized_busy)

    # Walk day-by-day across search horizon
    available: List[TimeWindow] = []
    current_day = start_utc.date()
    end_day = end_utc.date()

    while current_day <= end_day:
        if current_day.isoweekday() in allowed_days:
            day_work_start = datetime.combine(current_day, w_start, tzinfo=timezone.utc)
            day_work_end = datetime.combine(current_day, w_end, tzinfo=timezone.utc)

            # Clip to search horizon
            effective_start = max(day_work_start, start_utc)
            effective_end = min(day_work_end, end_utc)

            if effective_end > effective_start:
                # Subtract busy blocks from [effective_start, effective_end]
                cursor = effective_start
                for busy in merged_busy:
                    if busy.end <= cursor:
                        continue
                    if busy.start >= effective_end:
                        break

                    if busy.start > cursor:
                        free_end = min(busy.start, effective_end)
                        if free_end > cursor:
                            available.append(TimeWindow(start=cursor, end=free_end, is_busy=False))
                    cursor = max(cursor, busy.end)

                if cursor < effective_end:
                    available.append(TimeWindow(start=cursor, end=effective_end, is_busy=False))

        current_day += timedelta(days=1)

    # Filter out windows shorter than buffer/15 mins
    return [w for w in available if w.duration_minutes >= max(15, buffer_minutes)]


def allocate_task_slots(
    tasks: Sequence[Dict[str, Any]],
    available_windows: Sequence[TimeWindow],
    buffer_minutes: int = 15,
    strategy: str = "priority_first",
    dependencies: Optional[Mapping[int, Sequence[int]]] = None,
    existing_scheduled_map: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Deterministically allocate tasks into available time windows.

    Tasks are prioritized by:
      1. Topological dependency prerequisites (parents must finish before children start)
      2. Priority weight (urgent > high > medium > low)
      3. Due date (earlier deadlines first)
      4. Duration (fitting tasks efficiently)

    Ensures:
      - No overlapping allocations.
      - Each task is placed after all prerequisite tasks have completed + buffer.
      - Each task is placed within its deadline (`scheduled_end <= due_date 23:59:59 UTC`).
      - Preserves `buffer_minutes` between consecutive scheduled slots.
      - Returns both scheduled slots and any unassigned tasks with rationale.
    """
    if not tasks:
        return {
            "scheduled": [],
            "unassigned": [],
            "conflicts": [],
            "summary": "No tasks provided for scheduling.",
        }

    # Normalize dependencies map
    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for dep_k, dep_v in dependencies.items():
            dep_map[dep_k] = list(dep_v)
    for t in tasks:
        tid = t.get("id")
        if tid is not None and t.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in t["depends_on"]])

    # Map of already scheduled tasks (from previous state or prior batches)
    scheduled_map: Dict[int, Dict[str, Any]] = {}
    if existing_scheduled_map:
        for sched_k, sched_data in existing_scheduled_map.items():
            scheduled_map[sched_k] = {
                "scheduled_start": _ensure_utc(sched_data["scheduled_start"]),
                "scheduled_end": _ensure_utc(sched_data["scheduled_end"]),
            }

    # Sort key for tasks that are ready
    def sort_key(t: Dict[str, Any]) -> Tuple[int, datetime, int]:
        prio = str(t.get("priority", "medium")).lower()
        prio_rank = -PRIORITY_WEIGHTS.get(prio, 2)  # Higher priority comes first

        due = t.get("due_date")
        if due:
            if isinstance(due, (datetime, date)):
                due_dt = _ensure_utc(due)
            else:
                due_dt = _ensure_utc(str(due))
        else:
            due_dt = datetime.max.replace(tzinfo=timezone.utc)

        duration = int(t.get("duration_minutes") or 60)
        return (prio_rank, due_dt, duration)

    remaining_tasks = list(tasks)
    # Make mutable list of free windows: list of [start, end]
    free_blocks: List[List[datetime]] = [[w.start, w.end] for w in available_windows]

    scheduled: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    buf_delta = timedelta(minutes=buffer_minutes)

    while remaining_tasks:
        # Find all ready tasks (all prerequisites in scheduled_map)
        ready_tasks = []
        for t in remaining_tasks:
            tid = t.get("id")
            prereqs = dep_map.get(int(tid), []) if tid is not None else []
            if all(p in scheduled_map for p in prereqs):
                ready_tasks.append(t)

        if not ready_tasks:
            # Deadlock or unfulfilled prerequisite among remaining tasks
            for t in remaining_tasks:
                unassigned.append({
                    "task_id": t.get("id"),
                    "title": t.get("title"),
                    "priority": t.get("priority", "medium"),
                    "duration_minutes": int(t.get("duration_minutes") or 60),
                    "due_date": str(t.get("due_date")) if t.get("due_date") else None,
                    "reason": "Prerequisite dependencies not satisfied or could not be scheduled.",
                })
            break

        # Pick the highest priority ready task
        task = min(ready_tasks, key=sort_key)
        remaining_tasks.remove(task)

        duration_min = int(task.get("duration_minutes") or 60)
        needed_delta = timedelta(minutes=duration_min)

        # Parse due date deadline if present
        due_limit: Optional[datetime] = None
        if task.get("due_date"):
            raw_due = task["due_date"]
            if isinstance(raw_due, str):
                d_obj = date.fromisoformat(raw_due[:10])
                due_limit = datetime.combine(d_obj, time(23, 59, 59), tzinfo=timezone.utc)
            elif isinstance(raw_due, date) and not isinstance(raw_due, datetime):
                due_limit = datetime.combine(raw_due, time(23, 59, 59), tzinfo=timezone.utc)
            elif isinstance(raw_due, datetime):
                due_limit = _ensure_utc(raw_due)

        # Determine earliest allowed start based on prerequisites
        tid = task.get("id")
        prereqs = dep_map.get(int(tid), []) if tid is not None else []
        if prereqs:
            earliest_allowed_start = max(scheduled_map[p]["scheduled_end"] + buf_delta for p in prereqs)
        else:
            earliest_allowed_start = datetime.min.replace(tzinfo=timezone.utc)

        placed = False
        for i, block in enumerate(free_blocks):
            b_start, b_end = block[0], block[1]
            slot_start = max(b_start, earliest_allowed_start)
            slot_end = slot_start + needed_delta

            if slot_end > b_end:
                continue

            # Check if placement violates due date
            if due_limit and slot_end > due_limit:
                conflicts.append({
                    "task_id": task.get("id"),
                    "title": task.get("title"),
                    "due_date": str(task.get("due_date")),
                    "earliest_available": slot_start.isoformat(),
                    "issue": "Cannot be scheduled before deadline with current calendar load.",
                })
                break

            # Slot fits! Record assignment
            scheduled.append({
                "task_id": task.get("id"),
                "title": task.get("title"),
                "domain": task.get("domain", "general"),
                "priority": task.get("priority", "medium"),
                "duration_minutes": duration_min,
                "scheduled_start": slot_start.isoformat(),
                "scheduled_end": slot_end.isoformat(),
            })

            if tid is not None:
                scheduled_map[int(tid)] = {
                    "scheduled_start": slot_start,
                    "scheduled_end": slot_end,
                }

            # Update free blocks: split before and after
            new_pieces: List[List[datetime]] = []
            if slot_start > b_start and (slot_start - b_start).total_seconds() >= max(15, buffer_minutes) * 60:
                new_pieces.append([b_start, slot_start])

            after_start = slot_end + buf_delta
            if after_start < b_end and (b_end - after_start).total_seconds() >= max(15, buffer_minutes) * 60:
                new_pieces.append([after_start, b_end])

            free_blocks[i:i + 1] = new_pieces
            placed = True
            break

        if not placed and not any(c.get("task_id") == task.get("id") for c in conflicts):
            unassigned.append({
                "task_id": task.get("id"),
                "title": task.get("title"),
                "priority": task.get("priority", "medium"),
                "duration_minutes": duration_min,
                "due_date": str(task.get("due_date")) if task.get("due_date") else None,
                "reason": "Insufficient free time windows within working hours or before deadline.",
            })

    summary_text = (
        f"Scheduled {len(scheduled)} tasks successfully ({len(unassigned)} unassigned, "
        f"{len(conflicts)} deadline conflicts)."
    )

    return {
        "scheduled": scheduled,
        "unassigned": unassigned,
        "conflicts": conflicts,
        "summary": summary_text,
    }


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
    available_windows: Sequence[TimeWindow] = (),
    buffer_minutes: int = 15,
) -> Dict[str, Any]:
    """Re-scope and replan slipped tasks and all downstream dependents.

    Preserves all unaffected tasks untouched.
    """
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

    # Build downstream map: parent -> list of children
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

    # Preserved tasks that remain scheduled and fixed in place
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
    """Scan scheduled tasks, dependencies, and external events for:
    1. Direct time overlaps (task-to-task or task-to-external).
    2. Dependency order/timing violations (task starts before prerequisite finishes + buffer).
    3. Deadline violations (task scheduled after due_date).
    4. Slipped deadlines (uncompleted task scheduled in the past).
    """
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


_PRIORITY_DEFAULT_HOURS: Dict[str, float] = {
    "urgent": 4.0,
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}

_DOMAIN_EFFORT_MULTIPLIERS: Dict[str, float] = {
    "hackathon": 1.25,
    "code": 1.1,
    "coursework": 1.0,
    "general": 0.8,
}


def estimate_task_effort_hours(task: Dict[str, Any]) -> float:
    """Extract or estimate effort in hours for a task.

    Checks:
    1. Explicit duration_minutes field if present and > 0.
    2. Explicit text hints in title or notes (e.g. '36-hour', '8 hrs', '4h', '90 min').
    3. Heuristic fallback based on priority and domain.
    """
    # 1. Direct duration_minutes
    dur_min = task.get("duration_minutes")
    if dur_min is not None:
        try:
            val = float(dur_min)
            if val > 0:
                return round(val / 60.0, 2)
        except (ValueError, TypeError):
            pass

    # 2. Textual hints in title or notes (capped length and linear regex to avoid ReDoS)
    text_corpus = f"{task.get('title', '')} {task.get('notes', '')} {task.get('description', '')}"[:500]
    if text_corpus.strip():
        # Normalize hyphens so '36-hour' becomes '36 hour'
        normalized_corpus = text_corpus.replace("-", " ")
        # Match hours: e.g. "36 hour", "36 hours", "8 hrs", "2.5h"
        m_hr = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b', normalized_corpus, re.IGNORECASE)
        if m_hr:
            try:
                hrs = float(m_hr.group(1))
                if 0.25 <= hrs <= 100.0:
                    return round(hrs, 2)
            except ValueError:
                pass

        # Match minutes: e.g. "90 min", "45 minutes"
        m_min = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:minutes?|mins?)\b', normalized_corpus, re.IGNORECASE)
        if m_min:
            try:
                mins = float(m_min.group(1))
                if mins > 0:
                    return round(mins / 60.0, 2)
            except ValueError:
                pass

    # 3. Fallback heuristic
    priority = str(task.get("priority", "medium")).lower().strip()
    domain = str(task.get("domain", "general")).lower().strip()
    base_hrs = _PRIORITY_DEFAULT_HOURS.get(priority, 2.0)
    mult = _DOMAIN_EFFORT_MULTIPLIERS.get(domain, 1.0)
    return round(base_hrs * mult, 2)


def check_proactive_cognitive_conflicts(
    proposed_task: Dict[str, Any],
    existing_tasks: Sequence[Dict[str, Any]],
    external_events: Optional[Sequence[Dict[str, Any]]] = None,
    current_time: Optional[datetime | str] = None,
    daily_capacity_hours: float = 8.0,
    weekend_capacity_hours: float = 16.0,
) -> Optional[Dict[str, Any]]:
    """Proactively detect cross-domain collisions, capacity overcommit, and deadline clashes.

    Evaluates:
    1. Cross-Domain Collisions: High-priority commitments in other domains (e.g. hackathon sprint vs coursework lab/exam).
    2. Capacity Limits: Arithmetic check of proposed workload against daily or weekend focus limits.
    3. Actionable Arbitration: Generates concrete recommendations (e.g. shift prep to Thursday) instead of passive logging.

    Returns None if no conflict, or a detailed diagnostic dictionary.
    """
    now_utc = _ensure_utc(current_time) if current_time else datetime.now(timezone.utc)
    proposed_title = str(proposed_task.get("title", "Untitled Task")).strip()
    proposed_domain = str(proposed_task.get("domain", "general")).lower().strip()
    proposed_hours = estimate_task_effort_hours(proposed_task)

    # 1. Determine target date anchor
    target_d: Optional[date] = None
    raw_due = proposed_task.get("due_date")
    if raw_due:
        try:
            target_d = date.fromisoformat(str(raw_due)[:10])
        except Exception:
            target_d = None

    if not target_d and proposed_task.get("scheduled_start"):
        try:
            target_d = _ensure_utc(proposed_task["scheduled_start"]).date()
        except Exception:
            target_d = None

    # Check text for temporal cues like "weekend" if no explicit date given
    title_lower = proposed_title.lower()
    is_weekend_cue = "weekend" in title_lower or "saturday" in title_lower or "sunday" in title_lower
    if not target_d and is_weekend_cue:
        # Find next Saturday from now
        days_ahead = (5 - now_utc.weekday()) % 7
        if days_ahead == 0 and now_utc.weekday() != 5:
            days_ahead = 7
        target_d = (now_utc + timedelta(days=days_ahead)).date()

    if not target_d:
        # If no target date, only trigger if workload is massive (> 16 hours)
        if proposed_hours < 16.0:
            return None
        # Anchor to upcoming weekend
        days_ahead = (5 - now_utc.weekday()) % 7
        target_d = (now_utc + timedelta(days=days_ahead)).date()

    # 2. Scope dates (is it weekend or weekday?)
    is_weekend = target_d.weekday() in (5, 6) or is_weekend_cue
    if is_weekend:
        # Weekend scope: Saturday & Sunday
        if target_d.weekday() == 6:  # Sunday
            sat_d = target_d - timedelta(days=1)
            sun_d = target_d
        elif target_d.weekday() == 5:  # Saturday
            sat_d = target_d
            sun_d = target_d + timedelta(days=1)
        else:
            sat_d = target_d
            sun_d = target_d + timedelta(days=1)
        scope_dates = {sat_d, sun_d}
        capacity_limit = weekend_capacity_hours * 2.0  # e.g. 32.0 hours
    else:
        scope_dates = {target_d}
        capacity_limit = daily_capacity_hours  # e.g. 8.0 hours

    # 3. Find concurrent tasks in active scope
    cross_domain_conflicts: List[Dict[str, Any]] = []
    same_domain_tasks: List[Dict[str, Any]] = []
    cross_domain_hours = 0.0
    same_domain_hours = 0.0

    for t in existing_tasks:
        # Skip finished tasks or self
        st = str(t.get("status", "open")).lower().strip()
        if st in ("done", "completed", "closed"):
            continue
        if proposed_task.get("id") and t.get("id") == proposed_task.get("id"):
            continue

        # Extract date of existing task
        t_due = t.get("due_date")
        t_date: Optional[date] = None
        if t_due:
            try:
                t_date = date.fromisoformat(str(t_due)[:10])
            except Exception:
                pass
        if not t_date and t.get("scheduled_start"):
            try:
                t_date = _ensure_utc(t["scheduled_start"]).date()
            except Exception:
                pass

        # Check if matches scope
        if t_date and t_date in scope_dates:
            t_hrs = estimate_task_effort_hours(t)
            t_domain = str(t.get("domain", "general")).lower().strip()

            if t_domain != proposed_domain:
                cross_domain_conflicts.append({
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "domain": t_domain,
                    "due_date": str(t_due) if t_due else t_date.isoformat(),
                    "priority": t.get("priority", "medium"),
                    "estimated_hours": t_hrs,
                })
                cross_domain_hours += t_hrs
            else:
                same_domain_tasks.append(t)
                same_domain_hours += t_hrs

    # 4. External calendar commitments in scope
    external_busy_hours = 0.0
    if external_events:
        for ev in external_events:
            ev_start = ev.get("start") or ev.get("scheduled_start")
            ev_end = ev.get("end") or ev.get("scheduled_end")
            if ev_start and ev_end:
                try:
                    s_dt = _ensure_utc(ev_start)
                    e_dt = _ensure_utc(ev_end)
                    if s_dt.date() in scope_dates or e_dt.date() in scope_dates:
                        dur_hrs = max(0.0, (e_dt - s_dt).total_seconds() / 3600.0)
                        external_busy_hours += dur_hrs
                except Exception:
                    continue

    # 5. Arithmetic capacity evaluation
    total_demand = round(proposed_hours + cross_domain_hours + same_domain_hours + external_busy_hours, 1)
    is_overcommitted = total_demand > capacity_limit
    has_cross_domain_clash = len(cross_domain_conflicts) > 0

    # If neither overcommitted nor conflicting across domains, clean pass
    if not is_overcommitted and not (has_cross_domain_clash and proposed_hours >= 4.0):
        return None

    overcommit_hrs = max(0.0, round(total_demand - capacity_limit, 1))
    overcommit_pct = int(round((total_demand / max(1.0, capacity_limit)) * 100))

    # 6. Formulate actionable arbitration advice
    timeframe_str = "weekend" if is_weekend else f"day ({target_d.strftime('%a, %b %d')})"
    alert_lines = [
        "⚡ Cognitive Conflict Alert:",
    ]

    if cross_domain_conflicts:
        conflict_summaries = [
            f"'{c['title']}' [{c['domain'].upper()}] (due {c['due_date']}, est. {c['estimated_hours']:.1f}h)"
            for c in cross_domain_conflicts[:3]
        ]
        alert_lines.append(
            f"• Cross-Domain Collision: You have {len(cross_domain_conflicts)} active commitment(s) in other domains: {'; '.join(conflict_summaries)}."
        )

    alert_lines.append(
        f"• Capacity Math: Total demand is {total_demand}h against {capacity_limit:.0f}h available {timeframe_str} capacity ({overcommit_pct}% load, +{overcommit_hrs}h overcommit)."
    )

    # Concrete arbitration proposal
    suggested_action = ""
    if cross_domain_conflicts:
        primary_conflict = cross_domain_conflicts[0]
        shifted_target = target_d - timedelta(days=2 if not is_weekend else 2)
        suggested_action = (
            f"Propose shifting '{primary_conflict['title']}' prep to {shifted_target.strftime('%A, %b %d')} "
            f"to protect focus bandwidth for '{proposed_title}'."
        )
        alert_lines.append(f"• Suggested Arbitration: {suggested_action}")
    else:
        suggested_action = (
            f"Propose splitting '{proposed_title}' ({proposed_hours}h) into staged milestones or deferring non-urgent backlog."
        )
        alert_lines.append(f"• Suggested Arbitration: {suggested_action}")

    alert_message = "\n".join(alert_lines)

    return {
        "has_conflict": True,
        "conflict_type": "cross_domain_capacity_overload" if (is_overcommitted and has_cross_domain_clash) else ("cross_domain_collision" if has_cross_domain_clash else "capacity_overload"),
        "target_date": target_d.isoformat(),
        "is_weekend": is_weekend,
        "timeframe": timeframe_str,
        "proposed_task": {
            "title": proposed_title,
            "domain": proposed_domain,
            "estimated_hours": proposed_hours,
        },
        "conflicting_cross_domain_tasks": cross_domain_conflicts,
        "total_demand_hours": total_demand,
        "capacity_limit_hours": capacity_limit,
        "overcommit_hours": overcommit_hrs,
        "overcommit_pct": overcommit_pct,
        "suggested_action": suggested_action,
        "alert_message": alert_message,
    }


