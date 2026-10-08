"""
Compass — Deterministic Dynamic Scheduling Engine.

Provides pure Python interval arithmetic for packing tasks into calendar time slots.
Guarantees 0% LLM hallucination in time calculations, working hour boundaries,
inter-task buffers, and deadline satisfaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import logging
import sys
from pathlib import Path

# Ensure project root is available when executed directly
_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.services.cognitive_conflicts import (
    _ensure_utc,
    check_proactive_cognitive_conflicts,
    estimate_task_effort_hours,
)
from backend.services.scheduler_conflicts import (
    detect_schedule_conflicts,
    find_slipped_tasks,
    replan_slipped_tasks,
)

logger = logging.getLogger("compass.scheduler")

PRIORITY_WEIGHTS: Dict[str, int] = {
    "urgent": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


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
    """Calculate free working-hour windows by subtracting busy intervals from daily working hours."""
    start_utc = _ensure_utc(search_start)
    end_utc = _ensure_utc(search_end)
    w_start = _parse_time_str(work_start_time)
    w_end = _parse_time_str(work_end_time)
    allowed_days = set(work_days if work_days is not None else [1, 2, 3, 4, 5])

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

    available: List[TimeWindow] = []
    current_day = start_utc.date()
    end_day = end_utc.date()

    while current_day <= end_day:
        if current_day.isoweekday() in allowed_days:
            day_work_start = datetime.combine(current_day, w_start, tzinfo=timezone.utc)
            day_work_end = datetime.combine(current_day, w_end, tzinfo=timezone.utc)

            effective_start = max(day_work_start, start_utc)
            effective_end = min(day_work_end, end_utc)

            if effective_end > effective_start:
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
    """
    if not tasks:
        return {
            "scheduled": [],
            "unassigned": [],
            "conflicts": [],
            "summary": "No tasks provided for scheduling.",
        }

    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for dep_k, dep_v in dependencies.items():
            dep_map[dep_k] = list(dep_v)
    for t in tasks:
        tid = t.get("id")
        if tid is not None and t.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in t["depends_on"]])

    scheduled_map: Dict[int, Dict[str, Any]] = {}
    if existing_scheduled_map:
        for sched_k, sched_data in existing_scheduled_map.items():
            scheduled_map[sched_k] = {
                "scheduled_start": _ensure_utc(sched_data["scheduled_start"]),
                "scheduled_end": _ensure_utc(sched_data["scheduled_end"]),
            }

    def sort_key(t: Dict[str, Any]) -> Tuple[int, datetime, int]:
        prio = str(t.get("priority", "medium")).lower()
        prio_rank = -PRIORITY_WEIGHTS.get(prio, 2)

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
    free_blocks: List[List[datetime]] = [[w.start, w.end] for w in available_windows]

    scheduled: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    buf_delta = timedelta(minutes=buffer_minutes)

    while remaining_tasks:
        ready_tasks = []
        for t in remaining_tasks:
            tid = t.get("id")
            prereqs = dep_map.get(int(tid), []) if tid is not None else []
            if all(p in scheduled_map for p in prereqs):
                ready_tasks.append(t)

        if not ready_tasks:
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

        task = min(ready_tasks, key=sort_key)
        remaining_tasks.remove(task)

        duration_min = int(task.get("duration_minutes") or 60)
        needed_delta = timedelta(minutes=duration_min)

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

            if due_limit and slot_end > due_limit:
                conflicts.append({
                    "task_id": task.get("id"),
                    "title": task.get("title"),
                    "due_date": str(task.get("due_date")),
                    "earliest_available": slot_start.isoformat(),
                    "issue": "Cannot be scheduled before deadline with current calendar load.",
                })
                break

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


__all__ = [
    "PRIORITY_WEIGHTS",
    "TimeWindow",
    "_ensure_utc",
    "_parse_time_str",
    "merge_overlapping_intervals",
    "get_available_windows",
    "allocate_task_slots",
    "find_slipped_tasks",
    "replan_slipped_tasks",
    "detect_schedule_conflicts",
    "estimate_task_effort_hours",
    "check_proactive_cognitive_conflicts",
]
