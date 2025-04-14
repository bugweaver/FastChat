import asyncio
import logging
from typing import Optional

import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

log = logging.getLogger(__name__)


class RedisConnectionManager:
    """Manages connections to Redis."""

    def __init__(self, redis_url: str, reconnect_delay: float = 5.0) -> None:
        self.redis_url = redis_url
        self.reconnect_delay = reconnect_delay
        self._redis_client: Optional[redis.Redis] = None
        self._connection_lock = asyncio.Lock()

    async def get_client(self, decode_responses: bool = False) -> redis.Redis:
        """Returns an active Redis client, creating one if necessary."""
        async with self._connection_lock:
            if self._redis_client is None or not await self._is_client_connected():
                log.info(
                    "Connecting to Redis (decode_responses=%s)...", decode_responses
                )
                try:
                    self._redis_client = redis.Redis.from_url(
                        self.redis_url, decode_responses=decode_responses
                    )
                    await self._redis_client.ping()
                    log.info("Redis connected successfully.")
                except (RedisConnectionError, RedisTimeoutError, OSError) as e:
                    log.error("Failed to connect to Redis: %s", e)
                    self._redis_client = None
                    raise ConnectionError(
                        "Cannot connect to Redis at %s" % self.redis_url
                    ) from e
            return self._redis_client

    async def _is_client_connected(self) -> bool:
        if self._redis_client is None:
            return False
        try:
            return await self._redis_client.ping()
        except (RedisConnectionError, RedisTimeoutError, OSError, AttributeError):
            return False
        except Exception:
            log.warning("Unexpected error during Redis ping", exc_info=True)
            return False

    async def close(self) -> None:
        """Closes the connection to Redis."""
        async with self._connection_lock:
            if self._redis_client:
                client = self._redis_client
                self._redis_client = None
                try:
                    await client.aclose()
                    log.info("Redis client connection closed.")
                except Exception as e:
                    log.error("Error closing Redis client: %s", e)
