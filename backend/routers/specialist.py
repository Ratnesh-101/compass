import hmac
from fastapi import APIRouter, Depends, Request, HTTPException
from backend.dependencies import rate_limit, _get_current_user_id
from backend.memory.db import get_pool
from backend.config import get_settings

router = APIRouter(tags=["specialist"])


@router.post("/api/specialist/dispatch", dependencies=[Depends(rate_limit)])
async def dispatch_specialist_endpoint(request_data: dict, request: Request):
    """Direct thin API endpoint for the Specialist Multi-Agent System UI.
    Validates request -> verifies user/auth -> delegates to SpecialistDispatcher -> returns structured SpecialistResult.
    """
    settings = get_settings()

    # Verify authorization (bearer token or session/user identity)
    auth_header = request.headers.get("authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    user_id = _get_current_user_id(request)

    if settings.is_production():
        is_token_valid = bool(token and settings.AUTH_TOKEN and hmac.compare_digest(token, settings.AUTH_TOKEN))
        if not is_token_valid and not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized: valid bearer token or authenticated user session required.")

    from backend.agents.specialist import SpecialistRequest, SpecialistDispatcher
    pool = await get_pool()

    capability = request_data.get("capability", "memory")
    user_goal = request_data.get("user_goal") or request_data.get("goal") or ""
    relevant_context = request_data.get("relevant_context")
    allowed_tools = request_data.get("allowed_tools")

    req_cap = capability.lower().strip() if isinstance(capability, str) else "memory"
    if req_cap not in ("coursework", "research", "calendar", "memory"):
        req_cap = "memory"

    spec_req = SpecialistRequest(
        capability=req_cap,  # type: ignore
        user_goal=user_goal,
        relevant_context=relevant_context,
        allowed_tools=allowed_tools,
    )
    result = await SpecialistDispatcher.dispatch(spec_req, pool=pool)
    return result.model_dump()
