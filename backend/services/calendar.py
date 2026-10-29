"""
Compass — Calendar Synchronization Service.

Provides:
1. Google Calendar freebusy queries and event creation (with transparent mock/demo fallback).
2. RFC 5545 iCalendar (.ics) feed generator for zero-friction calendar subscriptions.
3. Database persistence for calendar connections and task-to-event linkages.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
import uuid
import logging

from backend.config import get_settings
from backend.services.scheduler import _ensure_utc, TimeWindow
from backend.services.calendar_ics import (  # noqa: F401  (re-exported for existing importers)
    _format_ics_dt,
    date_only_value,
    generate_ics_feed,
)

logger = logging.getLogger("compass.calendar")


# ---------------------------------------------------------------------------
# Calendar Connection Status & FreeBusy
# ---------------------------------------------------------------------------

async def get_calendar_connection_status(
    pool: Any = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve the current calendar connection status strictly for the specified user."""
    settings = get_settings()
    is_dev = settings.is_development()

    if not user_id:
        return {
            "connected": False,
            "provider": "google",
            "account_email": None,
            "connected_at": None,
            "last_synced_at": None,
            "mode": "demo" if is_dev else "live",
            "is_simulated": is_dev,
            "label": "Google Calendar: Not signed in (Demo Mode)" if is_dev else "Google Calendar: Not signed in",
            "note": "Sign in to connect your Google Calendar" if is_dev else "Sign in to connect your live Google Calendar via OAuth",
        }

    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT provider, account_email, access_token, connected_at, last_synced_at
                    FROM calendar_connections
                    WHERE (user_id = $1 OR account_email = $1) AND provider = 'google'
                    ORDER BY last_synced_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    user_id,
                )
                if row and row["access_token"]:
                    from backend.services.oauth import decrypt_token
                    decrypted = decrypt_token(row["access_token"])
                    is_mock = not decrypted or decrypted.startswith("mock_")
                    if is_mock and not is_dev:
                        return {
                            "connected": False,
                            "provider": "google",
                            "account_email": None,
                            "connected_at": None,
                            "last_synced_at": None,
                            "mode": "live",
                            "is_simulated": False,
                            "label": "Google Calendar: Not connected",
                            "note": "Live Google Calendar OAuth connection required in production.",
                        }
                    email = row["account_email"] or user_id or ""
                    return {
                        "connected": True,
                        "provider": row["provider"],
                        "account_email": email,
                        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
                        "last_synced_at": row["last_synced_at"].isoformat() if row["last_synced_at"] else None,
                        "mode": "live" if not is_mock else "demo",
                        "is_simulated": is_mock and is_dev,
                        "label": f"Google Calendar: {email} (Live OAuth Connected)" if not is_mock else f"Google Calendar: {email} (Quick Demo Mode — Live OAuth not connected)",
                        "note": "Live Google Calendar connected via OAuth" if not is_mock else "Simulated demo mode via Quick-Connect",
                    }
        except Exception as e:
            logger.warning(f"Could not read calendar_connections: {e}")

    return {
        "connected": False,
        "provider": "google",
        "account_email": user_id,
        "connected_at": None,
        "last_synced_at": None,
        "mode": "demo" if is_dev else "live",
        "is_simulated": is_dev,
        "label": f"Google Calendar: {user_id} (Demo Mode — not linked)" if is_dev else f"Google Calendar: {user_id} (Not linked)",
        "note": "Calendar not yet linked via Google OAuth",
    }


async def save_calendar_connection(
    pool: Any,
    user_id: str,
    account_email: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: int = 3600,
) -> bool:
    """Encrypt tokens and save connection to calendar_connections."""
    from backend.services.oauth import encrypt_token
    enc_access = encrypt_token(access_token)
    enc_refresh = encrypt_token(refresh_token) if refresh_token else None
    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO calendar_connections (user_id, provider, account_email, access_token, refresh_token, token_expiry, last_synced_at)
            VALUES ($1, 'google', $2, $3, $4, $5, now())
            ON CONFLICT (user_id, provider) DO UPDATE SET
                account_email = EXCLUDED.account_email,
                access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, calendar_connections.refresh_token),
                token_expiry = EXCLUDED.token_expiry,
                last_synced_at = now()
            """,
            user_id,
            account_email,
            enc_access,
            enc_refresh,
            expiry,
        )
    return True


async def disconnect_calendar_connection(pool: Any, user_id: str = "default_user") -> bool:
    """Clear calendar connection from database."""
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM calendar_connections WHERE user_id = $1 AND provider = 'google'",
            user_id,
        )
    return True


READONLY_WRITE_ERROR = (
    "Compass is connected read-only: Google refused to create events "
    "(missing write permission). Reconnect after enabling calendar write access."
)
NOT_CONNECTED_ERROR = "Google Calendar is not connected. Connect your Google account to create events."
FREEBUSY_AUTH_ERROR = "Google rejected the stored calendar access. Reconnect your Google account."


def _simulation_allowed() -> bool:
    """Simulated Google responses exist only in development and test, never in production."""
    return (get_settings().ENVIRONMENT or "").lower() in ("development", "test")


async def _fetch_google_busy(
    pool: Any, user_id: str, start_utc: datetime, end_utc: datetime
) -> tuple[List[Dict[str, Any]], Optional[str], bool]:
    """Read primary-calendar busy blocks. Returns (blocks, error_or_None, connected)."""
    import httpx

    token = await get_valid_access_token_for_user(pool, user_id)
    if not token:
        return [], None, False
    if token.startswith("mock_"):
        return [], None, True
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "timeMin": start_utc.isoformat(),
                    "timeMax": end_utc.isoformat(),
                    "items": [{"id": "primary"}],
                },
            )
    except Exception as e:
        logger.warning(f"Google freeBusy request failed: {e}")
        return [], "Could not reach Google Calendar.", False
    if resp.status_code in (401, 403):
        return [], FREEBUSY_AUTH_ERROR, False
    if resp.status_code != 200:
        return [], f"Google Calendar returned HTTP {resp.status_code} when reading your availability.", False
    primary_busy = resp.json().get("calendars", {}).get("primary", {}).get("busy", [])
    blocks = [
        {
            "id": f"gcal-live-{b.get('start')}",
            "title": "Google Calendar Commitment",
            "start": _ensure_utc(b.get("start")).isoformat(),
            "end": _ensure_utc(b.get("end")).isoformat(),
            "source": "google_calendar",
            "is_fixed": True,
        }
        for b in primary_busy
    ]
    logger.info(f"Loaded {len(blocks)} live Google Calendar busy blocks")
    return blocks, None, True


async def get_calendar_freebusy(
    start_dt: datetime | str,
    end_dt: datetime | str,
    pool: Any = None,
    user_id: str = "default_user",
    include_simulated: bool = True,
    task_user_id: Optional[str] = None,
    calendar_errors: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Query busy blocks within a date range.

    `task_user_id`, when set, restricts the Compass task blocks to that owner.
    `calendar_errors`, when given, collects human-readable reasons the live Google
    read failed so callers can show them instead of silently showing an empty week.

    Combines:
    1. Fixed/already scheduled tasks from PostgreSQL `tasks`.
    2. Live Google Calendar freeBusy query if OAuth is connected.
    3. If no live connection, gracefully uses simulated external commitments
       clearly labeled as demo/simulated.
    """
    start_utc = _ensure_utc(start_dt)
    end_utc = _ensure_utc(end_dt)

    busy_blocks: List[Dict[str, Any]] = []

    # 1. Fetch existing scheduled tasks from DB
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, title, domain, scheduled_start, scheduled_end, is_fixed
                    FROM tasks
                    WHERE deleted_at IS NULL
                      AND scheduled_start IS NOT NULL
                      AND scheduled_end IS NOT NULL
                      AND scheduled_start < $2
                      AND scheduled_end > $1
                      AND ($3::text IS NULL OR lower(user_id) = lower($3::text))
                    ORDER BY scheduled_start ASC
                    """,
                    start_utc,
                    end_utc,
                    task_user_id,
                )
                for r in rows:
                    busy_blocks.append({
                        "id": f"task-{r['id']}",
                        "task_id": r["id"],
                        "title": r["title"],
                        "domain": r["domain"],
                        "start": _ensure_utc(r["scheduled_start"]).isoformat(),
                        "end": _ensure_utc(r["scheduled_end"]).isoformat(),
                        "is_fixed": r["is_fixed"],
                        "source": "compass_task",
                    })
        except Exception as e:
            logger.warning(f"Error fetching scheduled tasks from DB: {e}")

    # 2. Live Google Calendar freeBusy (token is refreshed when needed; failures are reported)
    has_live_connection = False
    if pool is not None:
        live_blocks, fb_error, has_live_connection = await _fetch_google_busy(
            pool, user_id, start_utc, end_utc
        )
        busy_blocks.extend(live_blocks)
        if fb_error:
            logger.warning(f"Live Google Calendar freebusy query failed: {fb_error}")
            if calendar_errors is not None:
                calendar_errors.append(fb_error)

    # 3. Simulated Google Calendar events (honest fallback for hackathon demo & offline testing)
    # Strictly forbidden and disabled when ENVIRONMENT is unset or 'production' (requires development mode)
    settings = get_settings()
    if include_simulated and settings.is_development() and (not has_live_connection or len(busy_blocks) <= 1):
        curr = start_utc.date()
        end_d = end_utc.date()
        while curr <= end_d:
            # Standup: 10:00 - 10:30 UTC
            s_standup = datetime.combine(curr, time(10, 0, 0), tzinfo=timezone.utc)
            e_standup = datetime.combine(curr, time(10, 30, 0), tzinfo=timezone.utc)
            if s_standup >= start_utc and e_standup <= end_utc and curr.isoweekday() <= 5:
                busy_blocks.append({
                    "id": f"gcal-standup-{curr.isoformat()}",
                    "title": "Daily Team Standup (demo simulation)",
                    "start": s_standup.isoformat(),
                    "end": e_standup.isoformat(),
                    "source": "google_calendar_simulated",
                    "is_fixed": True,
                })

            # Lunch Break: 12:30 - 13:15 UTC
            s_lunch = datetime.combine(curr, time(12, 30, 0), tzinfo=timezone.utc)
            e_lunch = datetime.combine(curr, time(13, 15, 0), tzinfo=timezone.utc)
            if s_lunch >= start_utc and e_lunch <= end_utc:
                busy_blocks.append({
                    "id": f"gcal-lunch-{curr.isoformat()}",
                    "title": "Lunch Break (demo simulation)",
                    "start": s_lunch.isoformat(),
                    "end": e_lunch.isoformat(),
                    "source": "google_calendar_simulated",
                    "is_fixed": True,
                })

            # Architecture Sync: 15:30 - 16:30 UTC on Tuesdays & Thursdays
            if curr.isoweekday() in (2, 4):
                s_arch = datetime.combine(curr, time(15, 30, 0), tzinfo=timezone.utc)
                e_arch = datetime.combine(curr, time(16, 30, 0), tzinfo=timezone.utc)
                if s_arch >= start_utc and e_arch <= end_utc:
                    busy_blocks.append({
                        "id": f"gcal-arch-{curr.isoformat()}",
                        "title": "Sprint & Architecture Review (demo simulation)",
                        "start": s_arch.isoformat(),
                        "end": e_arch.isoformat(),
                        "source": "google_calendar_simulated",
                        "is_fixed": True,
                    })

            curr += timedelta(days=1)

    busy_blocks.sort(key=lambda x: x["start"])
    return busy_blocks


async def get_valid_access_token_for_user(
    pool: Any,
    user_id: str = "default_user",
) -> Optional[str]:
    """Retrieve decrypted valid access token for user, refreshing if expired."""
    if pool is None:
        return None
    try:
        from backend.services.oauth import decrypt_token, encrypt_token, refresh_google_access_token
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT access_token, refresh_token, token_expiry, account_email
                FROM calendar_connections
                WHERE (user_id = $1 OR account_email = $1) AND provider = 'google'
                ORDER BY last_synced_at DESC NULLS LAST
                LIMIT 1
                """,
                user_id,
            )
            if not row or not row["access_token"]:
                return None

            access_token = decrypt_token(row["access_token"])
            refresh_token = decrypt_token(row["refresh_token"]) if row["refresh_token"] else None
            expiry = row["token_expiry"]

            # If token expired or expiring within 5 minutes, refresh if refresh_token present
            now_utc = datetime.now(timezone.utc)
            if refresh_token and expiry and expiry <= (now_utc + timedelta(minutes=5)):
                refreshed = await refresh_google_access_token(refresh_token)
                if refreshed and refreshed.get("access_token"):
                    new_acc = refreshed["access_token"]
                    new_exp = now_utc + timedelta(seconds=refreshed.get("expires_in", 3600))
                    enc_acc = encrypt_token(new_acc)
                    await conn.execute(
                        """
                        UPDATE calendar_connections
                        SET access_token = $1, token_expiry = $2, last_synced_at = now()
                        WHERE (user_id = $3 OR account_email = $3) AND provider = 'google'
                        """,
                        enc_acc,
                        new_exp,
                        user_id,
                    )
                    return new_acc
            return access_token
    except Exception as e:
        logger.warning(f"Error fetching valid access token for {user_id}: {e}")
        return None


def _failed_event(error: str, http_status: Optional[int] = None) -> Dict[str, Any]:
    """A failed live create: no event id, never a fake one."""
    return {"id": None, "status": "failed", "htmlLink": None, "mode": "error", "error": error, "http_status": http_status}


async def create_google_calendar_event(
    access_token: str,
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    domain: str = "general",
    priority: str = "medium",
    calendar_id: str = "primary",
    all_day: bool = False,
) -> Dict[str, Any]:
    """Create an event on the user's Google Calendar via Google Calendar REST API.

    Returns mode "live" only when Google confirmed the creation. A refusal or network
    error returns mode "error" with an `error` text and id None. "simulated" is returned
    only in development/test for mock tokens (and the no-token case there).
    """
    import httpx

    if not access_token or access_token.startswith("mock_"):
        if not _simulation_allowed():
            return _failed_event(NOT_CONNECTED_ERROR)
        sim_id = f"gcal_sim_{uuid.uuid4().hex[:12]}"
        return {
            "id": sim_id,
            "status": "confirmed",
            "htmlLink": f"https://calendar.google.com/calendar/event?eid={sim_id}",
            "mode": "simulated",
        }

    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if all_day:
        start_field, end_field = {"date": start_iso[:10]}, {"date": end_iso[:10]}
    else:
        start_field, end_field = {"dateTime": start_iso}, {"dateTime": end_iso}
    body = {
        "summary": f"[Compass] {title}",
        "description": description or f"Scheduled automatically by Compass Autonomous AI Copilot\nDomain: {domain}\nPriority: {priority}",
        "start": start_field,
        "end": end_field,
        "reminders": {
            "useDefault": True,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=body)
    except Exception as e:
        logger.error(f"Error calling Google Calendar API: {e}")
        return _failed_event("Could not reach Google Calendar. Try again shortly.")

    if resp.status_code in (200, 201):
        data = resp.json()
        logger.info(f"Successfully created live Google Calendar event: {data.get('id')}")
        return {
            "id": data.get("id"),
            "status": "confirmed",
            "htmlLink": data.get("htmlLink"),
            "mode": "live",
        }
    logger.warning(f"Google Calendar create event API returned HTTP {resp.status_code}")
    if resp.status_code in (401, 403):
        return _failed_event(READONLY_WRITE_ERROR, resp.status_code)
    return _failed_event(f"Google Calendar rejected the event (HTTP {resp.status_code}).", resp.status_code)


async def link_calendar_event(
    task_id: int,
    start_dt: datetime | str | date,
    end_dt: datetime | str | date,
    title: str,
    pool: Any = None,
    calendar_id: str = "primary",
    user_id: str = "default_user",
    domain: str = "general",
    priority: str = "medium",
    notes: str = "",
    all_day: bool = False,
) -> Dict[str, Any]:
    """Create an event in Google Calendar and record it in calendar_event_links.

    `status` is "synced" (live event created), "simulated" (dev/test only),
    "not_connected" or "failed". The link row is written only for live events, so a
    refused or simulated create never looks like a synced event. `live_created`
    is True only when Google confirmed the creation.
    """
    if all_day:
        start_iso = (date_only_value(start_dt) or _ensure_utc(start_dt).date()).isoformat()
        end_iso = (date_only_value(end_dt) or _ensure_utc(end_dt).date()).isoformat()
    else:
        start_iso = _ensure_utc(start_dt).isoformat()
        end_iso = _ensure_utc(end_dt).isoformat()

    access_token = await get_valid_access_token_for_user(pool, user_id) if pool else None

    g_res = await create_google_calendar_event(
        access_token=access_token or "",
        title=title,
        start_iso=start_iso,
        end_iso=end_iso,
        description=f"Task Notes: {notes}\nDomain: {domain} | Priority: {priority}" if notes else f"Domain: {domain} | Priority: {priority}",
        domain=domain,
        priority=priority,
        calendar_id=calendar_id,
        all_day=all_day,
    )
    mode = g_res.get("mode", "error")
    google_event_id = g_res.get("id")
    live_created = mode == "live" and bool(google_event_id)

    if live_created and pool is not None:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO calendar_event_links (task_id, google_event_id, calendar_id, sync_status, last_synced_at)
                    VALUES ($1, $2, $3, 'synced', now())
                    ON CONFLICT (task_id, google_event_id)
                    DO UPDATE SET sync_status = 'synced', last_synced_at = now()
                    """,
                    task_id,
                    google_event_id,
                    calendar_id,
                )
        except Exception as e:
            logger.warning(f"Failed to record calendar_event_links for task {task_id}: {e}")

    if live_created:
        status = "synced"
    elif mode == "simulated":
        status = "simulated"
    elif g_res.get("error") == NOT_CONNECTED_ERROR:
        status = "not_connected"
    else:
        status = "failed"

    return {
        "status": status,
        "live_created": live_created,
        "task_id": task_id,
        "google_event_id": google_event_id,
        "calendar_id": calendar_id,
        "start": start_iso,
        "end": end_iso,
        "all_day": all_day,
        "title": title,
        "html_link": g_res.get("htmlLink"),
        "mode": mode,
        "error": g_res.get("error"),
    }


SYNCABLE_TASKS_SQL = """
    SELECT id, title, domain, priority, notes, duration_minutes, due_date, scheduled_start, scheduled_end
    FROM tasks
    WHERE user_id = $1
      AND deleted_at IS NULL
      AND COALESCE(status, 'open') NOT IN ('done', 'completed', 'cancelled')
      AND COALESCE(trusted_event_url, '') NOT LIKE $2
      AND (
        (scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL)
        OR due_date IS NOT NULL
      )
    ORDER BY COALESCE(scheduled_start, due_date) ASC
"""


def summarize_calendar_outcome(live_created: int, error_count: int, simulated: int, not_connected: int, first_error: Optional[str]) -> str:
    """Honest one-line outcome: 'Synced N tasks' only for events Google really created."""
    parts: List[str] = []
    if live_created:
        parts.append(f"Synced {live_created} task{'s' if live_created != 1 else ''} to your Google Calendar.")
    if error_count:
        parts.append(f"{error_count} could not be created. {first_error or ''}".strip())
    if simulated:
        parts.append(f"Simulated {simulated} task{'s' if simulated != 1 else ''} (demo mode, nothing was sent to Google).")
    if not_connected and not live_created and not error_count:
        parts.append(f"{NOT_CONNECTED_ERROR} Use the .ics export to import your schedule instead.")
    return " ".join(parts) or "Nothing to sync: no open scheduled tasks or deadlines."


def tally_link_results(results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts and first error across link_calendar_event results."""
    failed = [r for r in results if r.get("status") == "failed"]
    return {
        "live_created": sum(1 for r in results if r.get("live_created")),
        "error_count": len(failed),
        "simulated_count": sum(1 for r in results if r.get("status") == "simulated"),
        "not_connected_count": sum(1 for r in results if r.get("status") == "not_connected"),
        "calendar_error": next((r["error"] for r in failed if r.get("error")), None),
    }


async def sync_all_tasks_to_google_calendar(
    pool: Any,
    user_id: str = "default_user",
) -> Dict[str, Any]:
    """Create Google Calendar events for the user's open real tasks (demo and finished rows excluded).

    Tasks with a scheduled slot become timed events; tasks with only a due date become
    all-day events on that date.
    """
    from backend.services.task_scope import DEMO_URL_PREFIX

    if pool is None:
        return {"success": False, "count": 0, "message": "Database not connected"}

    if not user_id:
        return {"success": True, "count": 0, "message": "No user ID provided"}

    async with pool.acquire() as conn:
        tasks = await conn.fetch(SYNCABLE_TASKS_SQL, user_id, f"{DEMO_URL_PREFIX}%")

    access_token = await get_valid_access_token_for_user(pool, user_id)
    token_is_live = bool(access_token and not access_token.startswith("mock_"))

    synced_events: List[Dict[str, Any]] = []
    for t in tasks:
        start_dt = t.get("scheduled_start")
        end_dt = t.get("scheduled_end")
        all_day = not start_dt or not end_dt
        if all_day:
            due = date_only_value(t.get("due_date"))
            if due is None:
                continue
            start_dt, end_dt = due, due + timedelta(days=1)

        res = await link_calendar_event(
            task_id=t["id"],
            start_dt=start_dt,
            end_dt=end_dt,
            title=t["title"],
            pool=pool,
            user_id=user_id,
            domain=t["domain"],
            priority=t["priority"],
            notes=t["notes"] or "",
            all_day=all_day,
        )
        synced_events.append(res)

    tally = tally_link_results(synced_events)

    if tally["live_created"]:
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE calendar_connections
                    SET last_synced_at = now()
                    WHERE (user_id = $1 OR account_email = $1) AND provider = 'google'
                    """,
                    user_id,
                )
        except Exception as e:
            logger.warning(f"Could not update last_synced_at: {e}")

    return {
        "success": tally["error_count"] == 0,
        "count": len(synced_events),
        "live_created": tally["live_created"],
        "live_count": tally["live_created"],
        "simulated_count": tally["simulated_count"],
        "error_count": tally["error_count"],
        "calendar_error": tally["calendar_error"],
        "is_live": token_is_live and tally["live_created"] > 0,
        "message": summarize_calendar_outcome(
            tally["live_created"], tally["error_count"], tally["simulated_count"],
            tally["not_connected_count"], tally["calendar_error"],
        ),
        "events": synced_events,
        "user_id": user_id,
    }
