import logging

from fastapi import Depends, Query, WebSocketException
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from core.auth.services.auth_service import AuthService
from core.auth.services.token_service import TokenService
from core.auth.utils.token_utils import verify_token_ws
from core.config import settings
from core.dependencies import get_redis_client
from core.models import db_helper

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api.prefix}{settings.api.v1.prefix}{settings.api.v1.auth}/login"
)


def get_auth_service(
    db: AsyncSession = Depends(db_helper.session_getter),
    redis: Redis = Depends(get_redis_client),
) -> AuthService:
    """Initializing AuthService with dependencies"""
    return AuthService(db, redis)


def get_token_service(redis: Redis = Depends(get_redis_client)) -> TokenService:
    return TokenService(redis)


async def get_verified_ws_user_id(
    token: str = Query(..., description="Authentication token"),
    db: AsyncSession = Depends(db_helper.session_getter),
) -> int:
    """
    Dependency to verify WebSocket token and return user ID.
    Raises WebSocketException if token is invalid.
    """
    user_id = await verify_token_ws(token, db)
    if not user_id:
        logging.warning("WebSocket connection rejected: Invalid token.")
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid authentication token."
        )
    logging.debug("WebSocket token verified for user_id: %s", user_id)
    return user_id


async def require_specific_user(
    user_id: int, token_user_id: int = Depends(get_verified_ws_user_id)
) -> int:
    """
    Dependency to ensure the verified token user ID matches the user ID from the path.
    Relies on get_verified_ws_user_id for the actual token check.
    Returns the verified user_id if it matches.
    """
    if user_id <= 0:
        logging.warning(
            "WebSocket connection rejected: Invalid path user_id (%s).", user_id
        )
        raise WebSocketException(
            code=status.WS_1003_UNSUPPORTED_DATA,
            reason=f"Invalid user ID in path: {user_id}",
        )

    if token_user_id != user_id:
        logging.warning(
            "WebSocket connection rejected for user %s: Token mismatch (token for %s).",
            user_id,
            token_user_id,
        )
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Token does not match the specified user ID.",
        )
    return user_id
