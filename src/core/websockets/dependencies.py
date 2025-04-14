import logging

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_verified_ws_user_id, require_specific_user
from core.dependencies import get_redis_client
from core.models import db_helper
from core.websockets.connection_manager import ConnectionManager
from core.websockets.services.websocket_service import WebSocketService

log = logging.getLogger(__name__)


async def get_connection_manager(request: Request) -> ConnectionManager:
    """
    Returns an initialized ConnectionManager from the application state.
    Ensures that the manager was created in the lifespan.
    """
    if (
        not hasattr(request.app.state, "connection_manager")
        or request.app.state.connection_manager is None
    ):
        log.critical(
            "ConnectionManager not found in application state! Check lifespan function."
        )
        raise RuntimeError("ConnectionManager not available in application state.")
    return request.app.state.connection_manager


async def get_websocket_service(
    db: AsyncSession = Depends(db_helper.session_getter),
    redis_client: Redis = Depends(get_redis_client),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> WebSocketService:
    """Dependency provider for WebSocketService."""
    return WebSocketService(db=db, redis_client=redis_client, manager=manager)


__all__ = [
    "get_connection_manager",
    "get_websocket_service",
    "get_verified_ws_user_id",
    "require_specific_user",
]
