from datetime import timedelta

from redis.asyncio import Redis

from core.auth.services.redis_service import (
    delete_refresh_token,
    get_refresh_token,
    set_refresh_token,
)
from core.auth.utils.token_utils import encode_jwt
from core.config import settings
from core.models import User
from core.schemas.user_schemas import UserSchema

TOKEN_TYPE_FIELD = "type"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def create_jwt(
    token_type: str,
    token_data: dict,
    expire_minutes: int = settings.auth_jwt.access_token_expire_minutes,
    expire_timedelta: timedelta | None = None,
) -> str:
    jwt_payload = {TOKEN_TYPE_FIELD: token_type}
    jwt_payload.update(token_data)
    return encode_jwt(
        payload=jwt_payload,
        expire_minutes=expire_minutes,
        expire_timedelta=expire_timedelta,
    )


def create_access_token(user: User | UserSchema) -> str:
    jwt_payload = {
        "sub": user.username,
    }
    return create_jwt(
        token_type=ACCESS_TOKEN_TYPE,
        token_data=jwt_payload,
        expire_minutes=settings.auth_jwt.access_token_expire_minutes,
    )


async def create_refresh_token(user: User | UserSchema, redis: Redis) -> str:
    jwt_payload = {
        "sub": user.username,
    }
    refresh_token = create_jwt(
        token_type=REFRESH_TOKEN_TYPE,
        token_data=jwt_payload,
        expire_timedelta=timedelta(days=settings.auth_jwt.refresh_token_expire_days),
    )
    expire_seconds = settings.auth_jwt.refresh_token_expire_days * 86400
    await set_refresh_token(redis, user.id, refresh_token, expire_seconds)
    return refresh_token


async def validate_refresh_token(user_id: int, token: str, redis: Redis) -> bool:
    stored_token = await get_refresh_token(redis, user_id)
    return stored_token == token


async def revoke_refresh_token(user_id: int, redis: Redis) -> None:
    await delete_refresh_token(redis, user_id)
