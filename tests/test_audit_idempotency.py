"""Audit tests for PR #219: Idempotency, concurrency, and transaction boundary bugs."""

from unittest.mock import patch
import pytest
import pytest_asyncio

from backend.memory.db import get_pool
from backend.orchestrator import handle_message
from backend.services.chat_idempotency import normalize_request_id

OWNER = "audit_idem_user"
CONV = "audit-idem-conv-1"


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    if p is None:
        pytest.skip("local Postgres is not available")
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", OWNER)
        await conn.execute("DELETE FROM chat_request_log WHERE owner_identity = $1", OWNER)
    yield p
    async with p.acquire() as conn:
        await conn.execute("DELETE FROM tasks WHERE user_id = $1", OWNER)
        await conn.execute("DELETE FROM chat_request_log WHERE owner_identity = $1", OWNER)


@pytest.mark.asyncio
async def test_oversized_request_id_silently_bypasses_idempotency(pool):
    """Bug: normalize_request_id returns None for request_ids > 64 chars (e.g. 128 chars or 1 MB).

    Instead of rejecting the request, run_chat_request silently drops idempotency (rid=None).
    Sending the same request twice creates duplicate tasks.
    """
    huge_rid = "req_" + "a" * 120  # 124 chars, exceeds 64-char cap
    assert normalize_request_id(huge_rid) is not None, "Oversized request_id was silently dropped to None"

    msg = "add task Submit quarterly budget tomorrow"
    res1 = await handle_message(conversation_id=CONV, message=msg, user_id=OWNER, request_id=huge_rid, persist=False)
    res2 = await handle_message(conversation_id=CONV, message=msg, user_id=OWNER, request_id=huge_rid, persist=False)

    assert res1["success"] is True
    assert res2.get("replayed") is True, "Second call was not deduplicated as replay"

    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM tasks WHERE user_id = $1", OWNER)
    assert count == 1, f"Expected 1 task but found {count} due to bypassed idempotency"


@pytest.mark.asyncio
async def test_non_atomic_transaction_between_task_and_request_log_creates_duplicate_on_retry(pool):
    """Bug: Tasks are committed in structured.create_task in one transaction,

    while chat_request_log state update occurs in a separate connection/transaction in _finish.
    If an error occurs after create_task (e.g. during audit logging or formatting),
    _finish deletes the pending claim while the task remains committed in the tasks table.
    Retrying with the same request_id should succeed or replay, but instead fails with
    'duplicate_exact_deadline' because the request was not recorded as committed under its request_id.
    """
    rid = "req_audit_tx_boundary_02"
    msg = "add task Fix database deadlock tomorrow"

    # Simulate an error in post-creation processing (e.g. format_tool_response)
    with patch("backend.persona.format_tool_response", side_effect=RuntimeError("Audit formatting failed")):
        with pytest.raises(RuntimeError):
            await handle_message(conversation_id=CONV, message=msg, user_id=OWNER, request_id=rid, persist=False)

    # First attempt committed the task before the post-creation error
    async with pool.acquire() as conn:
        count_after_first = await conn.fetchval("SELECT count(*) FROM tasks WHERE user_id = $1", OWNER)
    assert count_after_first == 1, "Expected task to have been created before post-creation error"

    # Now the client retries with the SAME request_id. It should succeed (or replay the created task).
    res_retry = await handle_message(conversation_id=CONV, message=msg, user_id=OWNER, request_id=rid, persist=False)

    # In the current implementation, idempotency is lost: the retry fails with duplicate_exact_deadline error!
    assert res_retry.get("success") is True, f"Retry failed due to lost idempotency: {res_retry}"
    assert res_retry.get("replayed") is True or res_retry.get("skill_used") == "add_task"
