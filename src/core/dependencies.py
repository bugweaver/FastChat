from redis.asyncio import Redis
from starlette.requests import Request


def get_redis_client(request: Request) -> Redis:
    """Returns the Redis client from the application state (for HTTP or WebSocket)."""
    if (
        not hasattr(request.app.state, "redis_client")
        or request.app.state.redis_client is None
    ):
        raise RuntimeError("Redis client not available in application state.")
    return request.app.state.redis_client
