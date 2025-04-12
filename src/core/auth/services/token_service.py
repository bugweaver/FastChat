from datetime import timedelta

from fastapi import HTTPException, Request
from jwt import InvalidTokenError
from redis.asyncio import Redis
from starlette import status

from core.auth.services.redis_service import (
    delete_refresh_token,
    get_refresh_token,
    set_refresh_token,
)
from core.auth.utils.token_utils import decode_jwt, encode_jwt
from core.config import settings
from core.models import User
from core.schemas.user_schemas import UserSchema


class TokenService:
    TOKEN_TYPE_FIELD = "type"
    ACCESS_TOKEN_TYPE = "access"
    REFRESH_TOKEN_TYPE = "refresh"

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    def create_jwt(
        self,
        token_type: str,
        token_data: dict,
        expire_minutes: int | None = None,
        expire_timedelta: timedelta | None = None,
    ) -> str:
        jwt_payload = {self.TOKEN_TYPE_FIELD: token_type}
        jwt_payload.update(token_data)
        return encode_jwt(
            payload=jwt_payload,
            expire_minutes=expire_minutes,
            expire_timedelta=expire_timedelta,
        )

    def create_access_token(self, user: User | UserSchema) -> str:
        jwt_payload = {
            "sub": user.username,
        }
        return self.create_jwt(
            token_type=self.ACCESS_TOKEN_TYPE,
            token_data=jwt_payload,
            expire_minutes=settings.auth_jwt.access_token_expire_minutes,
        )

    async def create_refresh_token(self, user: User | UserSchema) -> str:
        jwt_payload = {
            "sub": user.username,
        }
        refresh_token = self.create_jwt(
            token_type=self.REFRESH_TOKEN_TYPE,
            token_data=jwt_payload,
            expire_timedelta=timedelta(
                days=settings.auth_jwt.refresh_token_expire_days
            ),
        )
        expire_seconds = settings.auth_jwt.refresh_token_expire_days * 86400
        await set_refresh_token(self.redis, user.id, refresh_token, expire_seconds)
        return refresh_token

    async def validate_refresh_token(self, user_id: int, token: str) -> bool:
        stored_token = await get_refresh_token(self.redis, user_id)
        return stored_token == token

    async def revoke_refresh_token(self, user_id: int) -> None:
        await delete_refresh_token(self.redis, user_id)

    @staticmethod
    def get_current_refresh_token_from_cookie(request: Request) -> str:
        """Getting refresh token"""
        token = request.cookies.get("refresh_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh Token not found in cookie.",
            )
        return token

    @staticmethod
    def get_current_access_token_payload(request: Request) -> dict:
        """Getting access token"""
        token = request.cookies.get("access_token")

        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access Token not found in cookie.",
            )

        try:
            payload = decode_jwt(token=token)
        except InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}",
            ) from e

        return payload

    @staticmethod
    def get_current_refresh_token_payload(request: Request) -> dict:
        """Getting refresh token"""
        token = request.cookies.get("refresh_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh Token not found in cookie.",
            )

        try:
            payload = decode_jwt(token=token)
        except InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid refresh token: {e}",
            ) from e

        return payload

    def validate_token_type(self, payload: dict, token_type: str) -> bool:
        """Check for a suitable token"""
        current_token_type = payload.get(self.TOKEN_TYPE_FIELD)
        if current_token_type == token_type:
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type {current_token_type!r},"
            f" expected: {token_type!r}",
        )
