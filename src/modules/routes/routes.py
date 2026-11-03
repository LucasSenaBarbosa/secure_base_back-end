from fastapi import APIRouter

from config.settings import get_settings
from modules.routes.auth_routes import router as auth_router
from modules.routes.health_routes import router as health_router
from modules.routes.homes_routes import router as homes_router
from modules.routes.root_routes import router as root_router
from modules.routes.users_routes import router as users_router

settings = get_settings()
api_router = APIRouter()
api_router.include_router(root_router)
api_router.include_router(health_router)

versioned_router = APIRouter(prefix=settings.api_prefix)
versioned_router.include_router(auth_router)
versioned_router.include_router(homes_router)
versioned_router.include_router(users_router)
api_router.include_router(versioned_router)
