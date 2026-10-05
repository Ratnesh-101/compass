"""
Compass — API Routers Package.
"""

from backend.routers.admin import router as admin_router
from backend.routers.tasks import router as tasks_router
from backend.routers.chat import router as chat_router
from backend.routers.agent import router as agent_router
from backend.routers.calendar import router as calendar_router
from backend.routers.auth import router as auth_router
from backend.routers.migration import router as migration_router
from backend.routers.profile import router as profile_router
from backend.routers.persona import router as persona_router

__all__ = [
    "admin_router",
    "tasks_router",
    "chat_router",
    "agent_router",
    "calendar_router",
    "auth_router",
    "migration_router",
    "profile_router",
    "persona_router",
]


