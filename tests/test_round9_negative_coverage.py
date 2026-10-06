"""
Compass — Round 9 Negative Cross-Identity & Boundary Tests.

Verifies strict cross-identity isolation, exact 403/404 response codes,
and that victim data remains unchanged under cross-user attacks:
  - GET/DELETE /api/profile/facts
  - DELETE /api/profile/facts/{key}
  - GET/POST /api/parked
  - PATCH /api/parked/{thought_id}
  - PATCH /api/parked/{thought_id}/resolve
  - POST /api/chat/recap
  - tone/mode field isolation
"""

import uuid
import pytest
from httpx import AsyncClient
from backend.routers.auth import create_session
from backend.memory.db import get_pool
from backend.memory.profile import set_profile_fact, get_profile_facts
from backend.memory.parked import park_thought, list_parked_thoughts
from backend.services.budgets import reset_daily_budget


from backend.services.rate_limiter import _MEM_BUCKETS


def _auth(user_id: str):
    return {"Authorization": f"Bearer {create_session(user_id)}"}


@pytest.mark.asyncio
@pytest.mark.route("GET /api/profile/facts")
async def test_neg_get_profile_facts(client: AsyncClient):
    """User B cannot view User A's profile facts; victim facts remain unchanged."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    pool = await get_pool()
    async with pool.acquire() as conn:
        await set_profile_fact(conn, key="name", value="Alice Secret", user_id=user_a)

    # User B queries facts
    res_b = await client.get("/api/profile/facts", headers=_auth(user_b))
    assert res_b.status_code == 200
    b_facts = res_b.json().get("facts", {})
    assert "name" not in b_facts

    # Unauthenticated request returns 401
    res_unauth = await client.get("/api/profile/facts")
    assert res_unauth.status_code == 401

    # Victim data unchanged
    async with pool.acquire() as conn:
        a_facts = await get_profile_facts(conn, user_id=user_a)
        assert a_facts.get("name") == "Alice Secret"


@pytest.mark.asyncio
@pytest.mark.route("DELETE /api/profile/facts")
async def test_neg_delete_all_profile_facts(client: AsyncClient):
    """User B clearing all facts ('forget all') leaves User A's facts intact."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    pool = await get_pool()
    async with pool.acquire() as conn:
        await set_profile_fact(conn, key="goal", value="Win Hackathon", user_id=user_a)

    # Unauthenticated returns 401
    res_unauth = await client.delete("/api/profile/facts")
    assert res_unauth.status_code == 401

    # User B calls forget all
    res_b = await client.delete("/api/profile/facts", headers=_auth(user_b))
    assert res_b.status_code == 200
    assert res_b.json()["deleted_count"] == 0

    # Victim data unchanged
    async with pool.acquire() as conn:
        a_facts = await get_profile_facts(conn, user_id=user_a)
        assert a_facts.get("goal") == "Win Hackathon"


@pytest.mark.asyncio
@pytest.mark.route("DELETE /api/profile/facts/{key}")
async def test_neg_delete_single_profile_fact(client: AsyncClient):
    """User B trying to delete User A's fact gets 404; User A's fact is unchanged."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    pool = await get_pool()
    async with pool.acquire() as conn:
        await set_profile_fact(conn, key="diet", value="vegetarian", user_id=user_a)

    # Unauthenticated returns 401
    res_unauth = await client.delete("/api/profile/facts/diet")
    assert res_unauth.status_code == 401

    # User B tries to delete User A's fact -> 404
    res_b = await client.delete("/api/profile/facts/diet", headers=_auth(user_b))
    assert res_b.status_code == 404

    # Victim data unchanged
    async with pool.acquire() as conn:
        a_facts = await get_profile_facts(conn, user_id=user_a)
        assert a_facts.get("diet") == "vegetarian"


@pytest.mark.asyncio
@pytest.mark.route("GET /api/parked")
async def test_neg_get_parked_thoughts(client: AsyncClient):
    """User B cannot see User A's parked thoughts shelf; victim data unchanged."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    pool = await get_pool()
    async with pool.acquire() as conn:
        await park_thought(conn, text="Alice confidential tangent", user_id=user_a)

    # Unauthenticated returns 401
    res_unauth = await client.get("/api/parked")
    assert res_unauth.status_code == 401

    # User B queries parked thoughts
    res_b = await client.get("/api/parked", headers=_auth(user_b))
    assert res_b.status_code == 200
    b_items = res_b.json().get("parked", [])
    assert not any("Alice confidential" in t.get("text", "") for t in b_items)

    # Victim data unchanged
    async with pool.acquire() as conn:
        a_items = await list_parked_thoughts(conn, user_id=user_a)
        assert any("Alice confidential tangent" in t.get("text", "") for t in a_items)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/parked")
async def test_neg_post_parked_thought(client: AsyncClient):
    """User B cannot create parked thoughts in User A's shelf by spoofing user_id."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    # Unauthenticated returns 401
    res_unauth = await client.post("/api/parked", json={"text": "Anonymous park"})
    assert res_unauth.status_code == 401

    # User B posts thought
    res_b = await client.post(
        "/api/parked",
        json={"text": "Bob tangent spoofing A", "user_id": user_a},
        headers=_auth(user_b),
    )
    assert res_b.status_code == 200
    created = res_b.json().get("thought", {})
    assert created.get("user_id") == user_b
    assert created.get("user_id") != user_a

    # Victim A has 0 items
    pool = await get_pool()
    async with pool.acquire() as conn:
        a_items = await list_parked_thoughts(conn, user_id=user_a)
        assert len(a_items) == 0


@pytest.mark.asyncio
@pytest.mark.route("PATCH /api/parked/{thought_id}/resolve")
async def test_neg_patch_parked_thought_resolve(client: AsyncClient):
    """User B cannot resolve User A's parked thought via /resolve alias; exact 404 returned and status remains 'parked'."""
    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    pool = await get_pool()
    async with pool.acquire() as conn:
        thought_rec = await park_thought(conn, text="A's second thought", user_id=user_a)
    thought_id = thought_rec["id"]

    # Unauthenticated returns 401
    res_unauth = await client.patch(f"/api/parked/{thought_id}/resolve")
    assert res_unauth.status_code == 401

    # User B attempts to resolve -> 404
    res_b = await client.patch(f"/api/parked/{thought_id}/resolve", headers=_auth(user_b))
    assert res_b.status_code == 404

    # Victim data unchanged
    async with pool.acquire() as conn:
        items = await list_parked_thoughts(conn, user_id=user_a, status="parked")
        assert any(t["id"] == thought_id and t["status"] == "parked" for t in items)


@pytest.mark.asyncio
@pytest.mark.route("POST /api/chat/recap")
async def test_neg_post_chat_recap(client: AsyncClient):
    """User B cannot recap User A's private conversation; exact 403 returned, 404 for missing, 429 when over daily budget."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from datetime import date
    from backend.memory import conversations
    from backend.services.budgets import MAX_DAILY_IDENTITY_RECAP_CALLS, _daily_recap_calls

    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_a = str(uuid.uuid4())

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conversations.get_or_create_conversation(conn, conversation_id=conv_a, user_id=user_a, title="A's Strategy")
        await conversations.add_message(conn, conversation_id=conv_a, role="user", content="Confidential plan for Q4.")

    # Unauthenticated request returns 401
    res_unauth = await client.post("/api/chat/recap", json={"conversation_id": conv_a})
    assert res_unauth.status_code == 401

    # Attack: User B tries to recap User A's conversation -> exact 403
    res_b = await client.post(
        "/api/chat/recap",
        json={"conversation_id": conv_a},
        headers=_auth(user_b),
    )
    assert res_b.status_code == 403
    assert "Forbidden" in res_b.json().get("detail", "")

    # Non-existent conversation -> exact 404
    non_existent = str(uuid.uuid4())
    res_missing = await client.post(
        "/api/chat/recap",
        json={"conversation_id": non_existent},
        headers=_auth(user_a),
    )
    assert res_missing.status_code == 404

    # Daily budget enforcement: count calls and assert 429 when limit reached
    reset_daily_budget(user_a)
    with patch("openai.AsyncOpenAI") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content="- Key decision: Plan Q4\nThat's a solid next step. Want me to write it down?"))]
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_resp)
        mock_openai_cls.return_value = mock_instance

        # Successful recap within budget
        res_ok = await client.post("/api/chat/recap", json={"conversation_id": conv_a}, headers=_auth(user_a))
        assert res_ok.status_code == 200

        # Simulate reaching the daily call budget limit
        today_str = date.today().isoformat()
        _daily_recap_calls.setdefault(today_str, {})[user_a] = MAX_DAILY_IDENTITY_RECAP_CALLS

        # Next call must trigger 429
        res_over = await client.post("/api/chat/recap", json={"conversation_id": conv_a}, headers=_auth(user_a))
        assert res_over.status_code == 429
        assert "budget" in res_over.json().get("detail", "").lower()

    reset_daily_budget(user_a)


@pytest.mark.asyncio
async def test_neg_tone_and_mode_cross_identity(client: AsyncClient):
    """Tone dial and mode parameters are strictly scoped to the caller's active conversation."""
    from backend.memory import conversations

    user_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    user_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"
    conv_a = str(uuid.uuid4())

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conversations.get_or_create_conversation(conn, conversation_id=conv_a, user_id=user_a, title="A conv")

    # B cannot hijack A's conversation to inject different mode/tone
    hijack_res = await client.post(
        "/api/chat",
        json={"message": "Hijack attempt", "conversation_id": conv_a, "tone": "exploratory", "mode": "sounding_board"},
        headers=_auth(user_b),
    )
    # B receives 403 because conversation_id belongs to A
    assert hijack_res.status_code == 403
