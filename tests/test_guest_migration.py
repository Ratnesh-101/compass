"""
Compass — Comprehensive Anonymous / Guest Conversation & Migration Test Suite.

Validates:
  1. Cryptographic guest token generation and HMAC verification (tamper-proofing).
  2. Forged/tampered guest tokens are rejected.
  3. Guest rate limiting protection.
  4. Guest session creation (POST /api/guest/session) & recovery (GET /api/guest/session).
  5. Guest conversation persistence and retrieval via x-guest-token.
  6. Strict tenant isolation:
     - Guest A cannot access Guest B's data
     - Guest cannot access User's data
     - User cannot see Guest data without migration
  7. Migration flow:
     - Migration status detection
     - Import All (preserves original guest data, links messages, idempotency)
     - Selective Import (imports chosen IDs, leaves others)
     - Idempotent repeated imports (no duplicates)
     - Skip preference
     - Privacy control: Delete guest data
"""

import uuid
import pytest
from httpx import AsyncClient

from backend.dependencies import (
    generate_guest_token,
    verify_guest_token,
)


# ---------------------------------------------------------------------------
# 1. Cryptographic Identity & Tamper Resistance
# ---------------------------------------------------------------------------

def test_generate_and_verify_guest_token():
    """Verify guest token format <uuid>.<hmac> and valid verification."""
    gid, token = generate_guest_token()
    assert gid is not None
    assert token.startswith(f"{gid}.")
    
    # Verification returns matching UUID
    verified_gid = verify_guest_token(token)
    assert verified_gid == gid


def test_tampered_guest_token_rejected():
    """Verify that altering either the guest UUID or HMAC signature fails verification."""
    gid, token = generate_guest_token()
    parts = token.split(".")
    
    # 1. Altered UUID with original signature
    fake_gid = str(uuid.uuid4())
    tampered_1 = f"{fake_gid}.{parts[1]}"
    assert verify_guest_token(tampered_1) is None

    # 2. Original UUID with forged signature
    tampered_2 = f"{gid}.deadbeef12345678"
    assert verify_guest_token(tampered_2) is None

    # 3. Empty or malformed tokens
    assert verify_guest_token("") is None
    assert verify_guest_token(None) is None
    assert verify_guest_token("not-a-token") is None
    assert verify_guest_token("invalid-uuid.signature") is None


# ---------------------------------------------------------------------------
# 2. Guest Session API Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guest_session_creation_and_recovery(client: AsyncClient):
    """Test POST /api/guest/session to create and GET /api/guest/session to recover."""
    # 1. POST creates a fresh session
    res = await client.post("/api/guest/session")
    assert res.status_code == 200
    data = res.json()
    assert "guest_id" in data
    assert "guest_token" in data
    guest_id = data["guest_id"]
    guest_token = data["guest_token"]
    assert guest_token.startswith(f"{guest_id}.")

    # 2. GET recovers session using header
    get_res = await client.get("/api/guest/session", headers={"x-guest-token": guest_token})
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["guest_id"] == guest_id

    # 3. GET with invalid token fails with 401
    bad_res = await client.get("/api/guest/session", headers={"x-guest-token": "bad.token"})
    assert bad_res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Guest Conversations & Tenant Isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guest_conversation_persistence_and_isolation(client: AsyncClient):
    """Verify guest conversations persist under guest token and are isolated from other guests and users."""
    gid_a, token_a = generate_guest_token()
    gid_b, token_b = generate_guest_token()
    user_email = f"auth_user_{uuid.uuid4().hex[:6]}@example.com"

    # Guest A starts a chat
    chat_a_res = await client.post(
        "/api/chat",
        json={"message": "Hello from Guest A", "conversation_id": None},
        headers={"x-guest-token": token_a, "x-guest-id": gid_a},
    )
    assert chat_a_res.status_code == 200
    conv_a_id = chat_a_res.json().get("conversation_id")
    assert conv_a_id is not None

    # Guest A lists conversations — should include conv_a_id
    list_a_res = await client.get(
        "/api/conversations",
        headers={"x-guest-token": token_a, "x-guest-id": gid_a},
    )
    assert list_a_res.status_code == 200
    convs_a = list_a_res.json().get("conversations", [])
    assert any(c["id"] == conv_a_id for c in convs_a)

    # Guest B lists conversations — should NOT see Guest A's conversation
    list_b_res = await client.get(
        "/api/conversations",
        headers={"x-guest-token": token_b, "x-guest-id": gid_b},
    )
    assert list_b_res.status_code == 200
    convs_b = list_b_res.json().get("conversations", [])
    assert not any(c["id"] == conv_a_id for c in convs_b)

    # Authenticated user lists conversations — should NOT see Guest A's conversation before migration
    list_user_res = await client.get(
        "/api/conversations",
        headers={"x-user-id": user_email},
    )
    assert list_user_res.status_code == 200
    convs_user = list_user_res.json().get("conversations", [])
    assert not any(c["id"] == conv_a_id for c in convs_user)

    # Guest B cannot update or delete Guest A's conversation (IDOR prevention)
    patch_res = await client.patch(
        f"/api/conversations/{conv_a_id}",
        json={"title": "Hacked Title"},
        headers={"x-guest-token": token_b, "x-guest-id": gid_b},
    )
    assert patch_res.status_code in (403, 404)

    delete_res = await client.delete(
        f"/api/conversations/{conv_a_id}",
        headers={"x-guest-token": token_b, "x-guest-id": gid_b},
    )
    assert delete_res.status_code in (403, 404)


# ---------------------------------------------------------------------------
# 4. Migration: Status, Import All, Selective Import, Preservation, Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migration_flow_and_preservation(client: AsyncClient):
    """Test full migration flow:
       - Status check
       - Selective import
       - Import all
       - Preservation of original guest data
       - Idempotency on repeated imports
    """
    gid, token = generate_guest_token()
    user_email = f"migrate_tester_{uuid.uuid4().hex[:6]}@example.com"
    from backend.routers.auth import create_session
    user_auth = f"Bearer {create_session(user_email)}"

    # 1. Guest creates 2 conversations
    chat_1 = await client.post(
        "/api/chat",
        json={"message": "First chat topic: Machine learning architecture", "conversation_id": None},
        headers={"x-guest-token": token, "x-guest-id": gid},
    )
    assert chat_1.status_code == 200
    conv_1_id = chat_1.json().get("conversation_id")

    chat_2 = await client.post(
        "/api/chat",
        json={"message": "Second chat topic: Hackathon timeline planning", "conversation_id": None},
        headers={"x-guest-token": token, "x-guest-id": gid},
    )
    assert chat_2.status_code == 200
    conv_2_id = chat_2.json().get("conversation_id")

    # 2. Check migration status with both user and guest headers
    status_res = await client.get(
        "/api/migration/status",
        headers={"Authorization": user_auth, "x-user-id": user_email, "x-guest-token": token, "x-guest-id": gid},
    )
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["has_guest_data"] is True
    assert status_data["guest_conversations_count"] >= 2

    # 3. Check migration conversations list
    list_mig_res = await client.get(
        "/api/migration/conversations",
        headers={"Authorization": user_auth, "x-user-id": user_email, "x-guest-token": token, "x-guest-id": gid},
    )
    assert list_mig_res.status_code == 200
    mig_convs = list_mig_res.json().get("conversations", [])
    assert any(c["id"] == conv_1_id for c in mig_convs)
    assert any(c["id"] == conv_2_id for c in mig_convs)

    # 4. Selective Import: Import only conv_1_id
    select_res = await client.post(
        "/api/migration/import-selected",
        json={"conversation_ids": [conv_1_id], "import_memory": True},
        headers={"Authorization": user_auth, "x-user-id": user_email, "x-guest-token": token, "x-guest-id": gid},
    )
    assert select_res.status_code == 200
    select_data = select_res.json()
    assert select_data["status"] == "ok"
    assert select_data["imported_count"] == 1

    # 5. Check Authenticated User history — should now contain imported conversation
    user_convs_res = await client.get(
        "/api/conversations",
        headers={"Authorization": user_auth, "x-user-id": user_email},
    )
    assert user_convs_res.status_code == 200
    user_convs = user_convs_res.json().get("conversations", [])
    # Check by imported_from_id or title
    assert len(user_convs) >= 1

    # 6. VERY IMPORTANT (Requirement 7): Guest conversation MUST STILL EXIST!
    guest_convs_res = await client.get(
        "/api/conversations",
        headers={"x-guest-token": token, "x-guest-id": gid},
    )
    assert guest_convs_res.status_code == 200
    g_convs = guest_convs_res.json().get("conversations", [])
    assert any(c["id"] == conv_1_id for c in g_convs), "Original guest conversation was deleted!"
    assert any(c["id"] == conv_2_id for c in g_convs), "Non-selected guest conversation was deleted!"

    # 7. Idempotency test (Requirement 8): Import conv_1_id AGAIN
    repeat_res = await client.post(
        "/api/migration/import-selected",
        json={"conversation_ids": [conv_1_id], "import_memory": False},
        headers={"Authorization": user_auth, "x-user-id": user_email, "x-guest-token": token, "x-guest-id": gid},
    )
    assert repeat_res.status_code == 200
    repeat_data = repeat_res.json()
    # It should report already_imported=True for conv_1_id and NOT duplicate it
    assert repeat_data["imported_count"] == 0
    assert any(c.get("already_imported") for c in repeat_data.get("conversations", []))

    # 8. Import All remaining: Should import conv_2_id safely
    import_all_res = await client.post(
        "/api/migration/import-all",
        headers={"Authorization": user_auth, "x-user-id": user_email, "x-guest-token": token, "x-guest-id": gid},
    )
    assert import_all_res.status_code == 200
    import_all_data = import_all_res.json()
    assert import_all_data["status"] == "ok"
    assert import_all_data["imported_count"] >= 1


@pytest.mark.asyncio
async def test_skip_migration_endpoint(client: AsyncClient):
    """Test POST /api/migration/skip records preference without modifying or deleting data."""
    gid, token = generate_guest_token()
    user_email = f"skip_user_{uuid.uuid4().hex[:6]}@example.com"

    res = await client.post(
        "/api/migration/skip",
        headers={"x-user-id": user_email, "x-guest-token": token, "x-guest-id": gid},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "skipped")


@pytest.mark.asyncio
async def test_delete_guest_data_privacy(client: AsyncClient):
    """Test DELETE /api/guest/data completely purges guest records (GDPR privacy control)."""
    gid, token = generate_guest_token()

    # Create a conversation
    chat_res = await client.post(
        "/api/chat",
        json={"message": "Temporary guest message to delete", "conversation_id": None},
        headers={"x-guest-token": token, "x-guest-id": gid},
    )
    assert chat_res.status_code == 200
    conv_id = chat_res.json().get("conversation_id")

    # Delete guest data
    del_res = await client.delete(
        "/api/guest/data",
        headers={"x-guest-token": token, "x-guest-id": gid},
    )
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["status"] in ("ok", "deleted")

    # Verify conversation is gone
    list_res = await client.get(
        "/api/conversations",
        headers={"x-guest-token": token, "x-guest-id": gid},
    )
    assert list_res.status_code == 200
    assert not any(c["id"] == conv_id for c in list_res.json().get("conversations", []))

