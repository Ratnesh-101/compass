"""Every SSE 'done' event carrying card data must serialise datetimes (pending-action cards carry expires_at)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "backend" / "services" / "chat_stream.py"


def test_every_done_event_dump_uses_default_str():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    offenders = [
        i + 1
        for i, ln in enumerate(lines)
        if "'type': 'done'" in ln and "'data'" in ln and "json.dumps(" in ln and "default=str" not in ln
    ]
    assert not offenders, f"done events without default=str at lines {offenders}"


def test_pending_action_payload_with_datetime_serialises_with_default_str():
    payload = {
        "type": "done",
        "data": {"pending_action": {"id": 7, "expires_at": datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)}},
    }
    text = json.dumps(payload, default=str)
    assert "2026-11-27" in text
