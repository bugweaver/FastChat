from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fakeredis import FakeAsyncRedis
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from core.redis.pubsub_manager import RedisPubSubManager


@pytest.fixture
def mock_redis_client(mock_pubsub: AsyncMock) -> AsyncMock:
    """Creates a mock Redis client for testing."""
    client = AsyncMock(spec=Redis)
    client.ping = AsyncMock(return_value=True)
    client.publish = AsyncMock(return_value=1)

    client.pubsub = AsyncMock(return_value=mock_pubsub)

    client.close = AsyncMock()
    client.connection = AsyncMock()
    client.connection.disconnect = AsyncMock()
    return client


@pytest.fixture
def mock_pubsub() -> AsyncMock:
    """Creates a mock PubSub client for testing."""
    pubsub = AsyncMock(spec=PubSub)
    pubsub.subscribe = AsyncMock()
    pubsub.psubscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.punsubscribe = AsyncMock()

    pubsub.get_message = AsyncMock(return_value=None)
    pubsub.close = AsyncMock()
    pubsub.connection = AsyncMock()
    pubsub.connection.disconnect = AsyncMock()
    pubsub.patterns_match = MagicMock(return_value=True)
    return pubsub


@pytest.fixture(autouse=True)
def patch_redis_from_url(
    mock_redis_client: AsyncMock,
) -> Generator[MagicMock | AsyncMock, Any, None]:
    """Patches Redis.from_url to return a mock client."""
    with patch(
        "redis.asyncio.Redis.from_url", return_value=mock_redis_client
    ) as patched:
        yield patched


@pytest.fixture
async def pubsub_manager(
    mock_redis_client: AsyncMock, mock_pubsub: AsyncMock
) -> RedisPubSubManager:
    """
    Creates a RedisPubSubManager instance
    with patched Redis components.
    """
    manager = RedisPubSubManager("redis://mockhost:6379")

    manager.publisher._redis_client = mock_redis_client
    manager.subscriber._redis_client = mock_redis_client

    manager._pubsub_client = mock_pubsub

    mock_redis_client.reset_mock()
    mock_pubsub.reset_mock()

    try:
        yield manager
    finally:
        if (
            hasattr(manager, "_listener_task")
            and manager.listener_task
            and not manager.listener_task.done()
        ):
            manager.listener_task.cancel()


@pytest.fixture
async def real_pubsub_manager(
    fake_redis_instance: FakeAsyncRedis,
) -> RedisPubSubManager:
    """
    Creates a RedisPubSubManager instance with
    FakeAsyncRedis for integration tests.
    """
    manager = RedisPubSubManager("redis://fakehost:6379")

    manager.publisher._redis_client = fake_redis_instance
    manager.subscriber._redis_client = fake_redis_instance

    pubsub = fake_redis_instance.pubsub(ignore_subscribe_messages=True)
    manager._pubsub_client = pubsub

    await fake_redis_instance.flushall()

    try:
        yield manager
    finally:
        if manager.listener_task and not manager.listener_task.done():
            await manager.stop_listener()
        await manager.close()
        await fake_redis_instance.flushall()
