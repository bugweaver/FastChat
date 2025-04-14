from typing import AsyncGenerator

import pytest_asyncio
from fakeredis import FakeAsyncRedis


@pytest_asyncio.fixture(scope="session")
def fake_redis_instance() -> FakeAsyncRedis:
    """FakeAsyncRedis instance at session level."""
    return FakeAsyncRedis(decode_responses=True)


@pytest_asyncio.fixture(scope="function")
async def redis_client(
    fake_redis_instance: FakeAsyncRedis,
) -> AsyncGenerator[FakeAsyncRedis, None]:
    """
    FakeAsyncRedis client at the function level,
    provides isolation between tests.
    """
    await fake_redis_instance.flushall()
    yield fake_redis_instance
    await fake_redis_instance.flushall()
