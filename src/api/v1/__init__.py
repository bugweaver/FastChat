from fastapi import APIRouter

from core.config import settings

from .auth_router import router as auth_router
from .chat_router import router as chat_router
from .websocket_router import router as websocket_router

router = APIRouter(
    prefix=settings.api.v1.prefix,
)
router.include_router(
    auth_router,
    prefix=settings.api.v1.auth,
)
router.include_router(
    websocket_router,
    prefix=settings.api.v1.ws,
)
router.include_router(
    chat_router,
    prefix=settings.api.v1.chat,
)
