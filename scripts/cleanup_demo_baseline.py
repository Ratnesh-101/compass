"""
Compass — Baseline Demo Data Cleanup Script.

Safely purges ephemeral test runs and synthetic tasks created on or after 2026-09-20,
leaving the 14 baseline tasks, 11 memory chunks, and 5 demo conversations intact.

Safety Guarantees:
  - Defaults to --dry-run (READ-ONLY).
  - Prints the target host before any action.
  - Refuses to write unless explicitly passed --i-mean-prod AND --confirm-host <exact_host>.
  - Uses an atomic transaction and validates remaining counts (14 / 11 / 5) before committing.
  - Leaves usage_log completely untouched.
"""

import argparse
import asyncio
import os
import sys
from urllib.parse import urlparse
import asyncpg
from dotenv import load_dotenv

load_dotenv()

sys.stdout.reconfigure(encoding="utf-8")

KEEP_CONVERSATION_IDS = [
    "85854a45-2e6e-4667-9787-db154e19d9fb",
    "64077081-611a-4e09-8ea0-60b2b429608c",
    "0a981ac5-eacc-4b29-8f8c-09f86e8a1d85",
    "b77ad1e2-7cf3-4eb2-a547-d9a91770bb0e",
    "4ecbabfd-1a29-4db3-8e2f-70fea0dae906",
]

TARGET_TASKS_COUNT = 14
TARGET_CHUNKS_COUNT = 11
TARGET_CONVS_COUNT = 5


def parse_args():
    parser = argparse.ArgumentParser(description="Compass Demo Baseline Cleanup")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL (defaults to env DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate cleanup without modifying any data (default: True unless --i-mean-prod)",
    )
    parser.add_argument(
        "--i-mean-prod",
        action="store_true",
        default=False,
        help="Explicit flag required to execute mutations",
    )
    parser.add_argument(
        "--confirm-host",
        type=str,
        default="",
        help="Must match the target database host exactly to execute mutations",
    )
    return parser.parse_args()


async def run_cleanup(db_url: str, dry_run: bool, i_mean_prod: bool, confirm_host: str):
    if not db_url:
        print("ERROR: No database URL provided via --db-url or env DATABASE_URL.", file=sys.stderr)
        sys.exit(1)

    parsed = urlparse(db_url)
    target_host = parsed.hostname or "unknown-host"

    print("=" * 70)
    print(f"TARGET DATABASE HOST: {target_host}")
    print(f"MODE:                 {'DRY-RUN (READ-ONLY)' if dry_run else 'LIVE MUTATING EXECUTION'}")
    print("=" * 70)

    # Production safety guard
    if not dry_run:
        if not i_mean_prod:
            print("ABORTED: Live mutation refused without --i-mean-prod flag.", file=sys.stderr)
            sys.exit(1)
        if confirm_host.strip() != target_host.strip():
            print(
                f"ABORTED: Host confirmation mismatch.\n"
                f"  Expected: {target_host}\n"
                f"  Provided: {confirm_host}\n"
                f"Must pass --confirm-host {target_host} exactly to confirm write operations.",
                file=sys.stderr,
            )
            sys.exit(1)

    conn = await asyncpg.connect(db_url)

    if dry_run:
        print("\n[DRY RUN] Inspecting doomed records...")

        # 1. Doomed tasks
        doomed_tasks = await conn.fetch("""
            SELECT id, title, domain, status, priority, created_at
            FROM tasks
            WHERE created_at >= '2026-09-20 00:00:00+00'
            ORDER BY id ASC
        """)
        print(f"\nDoomed tasks (count = {len(doomed_tasks)}):")
        for t in doomed_tasks:
            print(f"  id={t['id']} | title={t['title']!r} | created_at={t['created_at'].isoformat()}")

        # 2. Doomed memory chunks
        doomed_chunks = await conn.fetch("""
            SELECT id, domain, source, left(content, 60) as preview, created_at
            FROM memory_chunks
            WHERE created_at >= '2026-09-20 00:00:00+00'
            ORDER BY id ASC
        """)
        print(f"\nDoomed memory chunks (count = {len(doomed_chunks)}):")
        for c in doomed_chunks:
            print(f"  id={c['id']} | domain={c['domain']} | preview={c['preview']!r} | created_at={c['created_at'].isoformat()}")

        # 3. Doomed conversations
        doomed_convs = await conn.fetch("""
            SELECT c.id, c.started_at, count(m.id) as msg_count
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            WHERE c.id != ALL($1::uuid[])
            GROUP BY c.id, c.started_at
            ORDER BY c.started_at ASC
        """, KEEP_CONVERSATION_IDS)
        print(f"\nDoomed conversations (count = {len(doomed_convs)}):")
        for conv in doomed_convs:
            first_msg = await conn.fetchval("""
                SELECT content FROM messages WHERE conversation_id = $1 ORDER BY created_at ASC LIMIT 1
            """, conv['id'])
            preview = (first_msg[:60].replace('\n', ' ') if first_msg else '[EMPTY]')
            print(f"  id={conv['id']} | msgs={conv['msg_count']} | first_msg={preview!r} | started_at={conv['started_at'].isoformat()}")

        # 4. Doomed agent_runs and agent_audit_log
        doomed_task_ids = [t['id'] for t in doomed_tasks]
        audit_count = await conn.fetchval("""
            SELECT count(*) FROM agent_audit_log
            WHERE created_at >= '2026-09-20 00:00:00+00'
               OR affected_id = ANY($1::int[])
        """, doomed_task_ids)
        runs_count = await conn.fetchval("""
            SELECT count(*) FROM agent_runs
            WHERE created_at >= '2026-09-20 00:00:00+00'
        """)
        print(f"\nDoomed agent_audit_log rows: {audit_count}")
        print(f"Doomed agent_runs rows:      {runs_count}")

        # 5. calendar_event_links check
        links = await conn.fetch("""
            SELECT l.id, l.task_id, t.title, l.google_event_id
            FROM calendar_event_links l
            JOIN tasks t ON l.task_id = t.id
            WHERE t.created_at >= '2026-09-20 00:00:00+00'
        """)
        print(f"\ncalendar_event_links for doomed tasks: {len(links)}")
        for link_item in links:
            print(f"  link_id={link_item['id']} | task_id={link_item['task_id']} | title={link_item['title']!r} | google_event_id={link_item['google_event_id']}")

        # 6. Projected survivor counts
        curr_tasks = await conn.fetchval("SELECT count(*) FROM tasks")
        curr_chunks = await conn.fetchval("SELECT count(*) FROM memory_chunks")
        curr_convs = await conn.fetchval("SELECT count(*) FROM conversations")
        proj_tasks = curr_tasks - len(doomed_tasks)
        proj_chunks = curr_chunks - len(doomed_chunks)
        proj_convs = curr_convs - len(doomed_convs)
        print(f"\nProjected survivors: tasks={proj_tasks}, memory_chunks={proj_chunks}, conversations={proj_convs}")
        print(f"Target survivors:    tasks={TARGET_TASKS_COUNT}, memory_chunks={TARGET_CHUNKS_COUNT}, conversations={TARGET_CONVS_COUNT}")

        await conn.close()
        return

    # LIVE EXECUTION
    tr = conn.transaction()
    await tr.start()
    try:
        # Pre-check calendar links
        links = await conn.fetch("""
            SELECT l.id, l.task_id, t.title, l.google_event_id
            FROM calendar_event_links l
            JOIN tasks t ON l.task_id = t.id
            WHERE t.created_at >= '2026-09-20 00:00:00+00'
        """)
        print(f"Found {len(links)} calendar_event_links for doomed tasks.")

        # Delete tasks
        deleted_tasks = await conn.fetch("""
            DELETE FROM tasks
            WHERE created_at >= '2026-09-20 00:00:00+00'
            RETURNING id, title
        """)
        deleted_task_ids = [t['id'] for t in deleted_tasks]
        print(f"Deleted {len(deleted_tasks)} tasks.")

        # Delete memory chunks
        deleted_chunks = await conn.fetch("""
            DELETE FROM memory_chunks
            WHERE created_at >= '2026-09-20 00:00:00+00'
            RETURNING id
        """)
        print(f"Deleted {len(deleted_chunks)} memory chunks.")

        # Delete agent logs
        del_audit = await conn.fetch("""
            DELETE FROM agent_audit_log
            WHERE created_at >= '2026-09-20 00:00:00+00'
               OR affected_id = ANY($1::int[])
            RETURNING id
        """, deleted_task_ids)
        print(f"Deleted {len(del_audit)} agent_audit_log entries.")

        del_runs = await conn.fetch("""
            DELETE FROM agent_runs
            WHERE created_at >= '2026-09-20 00:00:00+00'
            RETURNING id
        """)
        print(f"Deleted {len(del_runs)} agent_runs entries.")

        # Delete conversations
        del_convs = await conn.fetch("""
            DELETE FROM conversations
            WHERE id != ALL($1::uuid[])
            RETURNING id
        """, KEEP_CONVERSATION_IDS)
        print(f"Deleted {len(del_convs)} conversations.")

        # Final count check
        final_tasks = await conn.fetchval("SELECT count(*) FROM tasks")
        final_chunks = await conn.fetchval("SELECT count(*) FROM memory_chunks")
        final_convs = await conn.fetchval("SELECT count(*) FROM conversations")

        print(f"Final counts: tasks={final_tasks}, memory_chunks={final_chunks}, conversations={final_convs}")
        if (
            final_tasks == TARGET_TASKS_COUNT
            and final_chunks == TARGET_CHUNKS_COUNT
            and final_convs == TARGET_CONVS_COUNT
        ):
            await tr.commit()
            print("COMMIT SUCCESSFUL: Target baseline restored.")
        else:
            await tr.rollback()
            print(f"ROLLBACK: Counts did not match {TARGET_TASKS_COUNT}/{TARGET_CHUNKS_COUNT}/{TARGET_CONVS_COUNT}.")

    except Exception as e:
        await tr.rollback()
        print(f"ERROR: Rollback triggered: {e}", file=sys.stderr)
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    args = parse_args()
    is_dry = not args.i_mean_prod or args.dry_run
    asyncio.run(run_cleanup(args.db_url, is_dry, args.i_mean_prod, args.confirm_host))
