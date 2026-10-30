import pytest
import uuid
from backend.agent_step_executor import execute_agent_tool_step
from backend.skills.registry import (
    GUEST_DISALLOWED_TOOLS,
    dispatch_skill,
    is_tool_allowed_for_identity,
)
from backend.dependencies import Identity


@pytest.mark.asyncio
async def test_guest_uuid_disallowed_in_registry():
    guest_uuid = str(uuid.uuid4())
    guest_ident = Identity(
        id=guest_uuid,
        is_admin=False,
        is_guest=True,
        user_id=None,
        guest_id=guest_uuid,
    )

    for tool in GUEST_DISALLOWED_TOOLS:
        assert not is_tool_allowed_for_identity(tool, guest_ident)
        assert not is_tool_allowed_for_identity(tool, guest_uuid, is_guest=True)


@pytest.mark.asyncio
async def test_authenticated_user_allowed_in_registry():
    user_id = "user_regular_123"
    user_ident = Identity(
        id=user_id,
        is_admin=False,
        is_guest=False,
        user_id=user_id,
        guest_id=None,
    )

    for tool in GUEST_DISALLOWED_TOOLS:
        assert is_tool_allowed_for_identity(tool, user_ident)
        assert is_tool_allowed_for_identity(tool, user_id, is_guest=False)


@pytest.mark.asyncio
async def test_guest_uuid_disallowed_in_dispatch_skill():
    guest_uuid = str(uuid.uuid4())
    for tool in GUEST_DISALLOWED_TOOLS:
        with pytest.raises(PermissionError, match="Guest sessions are forbidden"):
            await dispatch_skill(tool, {"user_id": guest_uuid, "is_guest": True}, pool=None)


@pytest.mark.asyncio
async def test_guest_uuid_disallowed_in_agent_step_executor():
    guest_uuid = str(uuid.uuid4())
    for tool in GUEST_DISALLOWED_TOOLS:
        obs_step, tool_result, search_unlocked, a_pay, t_pay = await execute_agent_tool_step(
            func_name=tool,
            tool_args={"user_id": guest_uuid},
            raw_args="{}",
            tc_id="tc_guest_1",
            step_num=1,
            step_start=0.0,
            run_id="run_test_guest",
            pool=None,
            user_id=guest_uuid,
            goal="test guest gate",
            abstain_first=False,
            search_web_unlocked=True,
            tools_used=[],
            is_guest=True,
        )
        assert "Permission denied: Guest sessions are forbidden" in obs_step.content
        assert obs_step.model_tier == "Compass Permission Gate"
