"""
Compass — API Routers Package.
"""

from backend.routers.admin import router as admin_router
from backend.routers.tasks import router as tasks_router
from backend.routers.chat import router as chat_router
from backend.routers.agent import router as agent_router
from backend.routers.calendar import router as calendar_router
from backend.routers.auth import router as auth_router
from backend.routers.specialist import router as specialist_router

__all__ = [
    "admin_router",
    "tasks_router",
    "chat_router",
    "agent_router",
    "calendar_router",
    "auth_router",
    "specialist_router",
]
