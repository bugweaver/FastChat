from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis

from core.config import settings

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api.prefix}{settings.api.v1.prefix}{settings.api.v1.auth}/login"
)


def get_redis(request: Request) -> Redis:
    return request.app.state.redis_client
