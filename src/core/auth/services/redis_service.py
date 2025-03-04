from redis.asyncio import Redis

from core.config import settings


async def setup_redis_client() -> Redis:
    redis_client = Redis.from_url(str(settings.redis.url), decode_responses=True)
    return redis_client


async def set_refresh_token(
    redis: Redis, user_id: int, token: str, expire: int
) -> None:
    await redis.setex(f"refresh_token:{user_id}", expire, token)


async def get_refresh_token(redis: Redis, user_id: int) -> bytes | None:
    return await redis.get(f"refresh_token:{user_id}")


async def delete_refresh_token(redis: Redis, user_id: int) -> None:
    await redis.delete(f"refresh_token:{user_id}")
