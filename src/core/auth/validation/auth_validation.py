import logging
from typing import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_token_service
from core.auth.services.token_service import TokenService
from core.models import User, db_helper
from repositories.user_repo import get_user_by_token_sub, get_user_by_username

logger = logging.getLogger(__name__)


async def get_current_user_from_refresh_token(
    request: Request,
    db: AsyncSession = Depends(db_helper.session_getter),
    token_service: TokenService = Depends(get_token_service),
) -> User:
    """
    Gets a user based on a refresh token from a cookie.
    Uses TokenService to retrieve and initially validate the payload.
    """
    try:
        token_from_cookie = token_service.get_current_refresh_token_from_cookie(request)
        logger.debug(
            "get_current_user_from_refresh_token: token from cookie found: ...%s",
            token_from_cookie[-10:] if token_from_cookie else "None",
        )

        payload = token_service.get_current_refresh_token_payload(request)
        logger.debug("get_current_user_from_refresh_token: payload: %s", payload)

        token_service.validate_token_type(payload, token_service.REFRESH_TOKEN_TYPE)
        logger.debug("get_current_user_from_refresh_token: token type valid (refresh)")

        username: str | None = payload.get("sub")
        if not username:
            logger.warning(
                "get_current_user_from_refresh_token: 'sub' not found in payload"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials (missing sub)",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.debug(
            "get_current_user_from_refresh_token: username from 'sub': %s", username
        )

    except HTTPException as http_exc:
        logger.warning(
            "get_current_user_from_refresh_token:"
            " HTTPException during token processing: %s - %s",
            http_exc.status_code,
            http_exc.detail,
        )
        raise http_exc

    user = await get_user_by_username(db, username)
    if not user:
        logger.warning(
            "get_current_user_from_refresh_token: User not found for username: %s",
            username,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials (user not found)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug(
        "get_current_user_from_refresh_token: User found: %s (ID: %s)",
        user.username,
        user.id,
    )
    return user


def get_current_auth_user_from_access_token_of_type(
    token_type: str,
) -> Callable[..., Awaitable[User]]:
    """Dependency factory for getting a user by Access token."""

    async def get_auth_user_from_token(
        request: Request,
        db: AsyncSession = Depends(db_helper.session_getter),
        token_service: TokenService = Depends(get_token_service),
    ) -> User:
        logger.debug(
            "get_auth_user_from_token: attempting to get payload for type %r",
            token_type,
        )
        try:
            payload = token_service.get_current_access_token_payload(request)
            logger.debug("get_auth_user_from_token: got payload: %s", payload)

            token_service.validate_token_type(payload, token_type)
            logger.debug("get_auth_user_from_token: token type %r is valid", token_type)

            user = await get_user_by_token_sub(payload, db)
            if not user:
                logger.warning(
                    "get_auth_user_from_token: user not found for payload 'sub': %s",
                    payload.get("sub"),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Could not validate credentials (user from token not found)",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            logger.debug(
                "get_auth_user_from_token: user found: %s (ID: %s)",
                user.username,
                user.id,
            )
            return user

        except HTTPException as http_exc:
            logger.warning(
                "get_auth_user_from_token: HTTPException: %s - %s",
                http_exc.status_code,
                http_exc.detail,
            )
            raise HTTPException(
                status_code=http_exc.status_code,
                detail=f"Invalid token ({http_exc.detail})",
                headers={"WWW-Authenticate": "Bearer"},
            ) from http_exc
        except Exception as e:
            logger.exception(
                "get_auth_user_from_token: Unexpected error: %s", e, exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error during token validation",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    return get_auth_user_from_token


def get_token_types() -> tuple[str, str]:
    return TokenService.ACCESS_TOKEN_TYPE, TokenService.REFRESH_TOKEN_TYPE


ACCESS_TOKEN_TYPE, REFRESH_TOKEN_TYPE = get_token_types()

get_current_auth_user = get_current_auth_user_from_access_token_of_type(
    ACCESS_TOKEN_TYPE
)


async def get_current_active_auth_user(
    user: User = Depends(get_current_auth_user),
) -> User:
    """Getting an active authorized user using an Access token."""
    logger.debug(
        "get_current_active_auth_user: Checking activity for user: %s (Active: %s)",
        user.username,
        user.is_active,
    )
    if user.is_active:
        return user
    logger.warning(
        "get_current_active_auth_user: User %s is not active.", user.username
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="The user is inactive",
    )
