from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.auth.services.token_service import create_access_token
from core.auth.utils.password_utils import hash_password
from core.dependencies import get_redis
from core.models import Base, User, db_helper
from main import app

TEST_DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
engine_test = create_async_engine(TEST_DATABASE_URL, echo=True)
async_session_maker = async_sessionmaker(
    engine_test, class_=AsyncSession, expire_on_commit=False
)

Base.metadata.bind = engine_test


async def override_get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


app.dependency_overrides[db_helper.session_getter] = override_get_async_session


async def override_get_redis() -> Redis:
    return Redis.from_url(
        "redis://localhost:6379/0", encoding="utf-8", decode_responses=True
    )


app.dependency_overrides[get_redis] = override_get_redis


@pytest.fixture
def mock_redis() -> AsyncGenerator[MagicMock, None]:
    with patch("core.auth.services.token_service.delete_refresh_token") as mock:
        mock.return_value = None
        yield mock


@pytest.fixture(scope="session", autouse=True)
async def create_test_database() -> AsyncGenerator[None, None]:
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="session")
async def test_app() -> FastAPI:
    yield app


@pytest.fixture(scope="session")
async def async_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.fixture(scope="session")
async def async_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


@pytest.fixture(scope="function")
async def async_transaction(
    async_db: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    async with async_db.begin() as transaction:
        yield async_db
        await transaction.rollback()


@pytest.fixture(scope="function")
async def redis_client() -> AsyncGenerator[Redis, None]:
    redis = Redis.from_url(
        "redis://localhost:6379/0", encoding="utf-8", decode_responses=True
    )
    await redis.flushall()
    yield redis
    await redis.flushall()
    await redis.aclose()


@pytest.fixture(scope="function")
async def test_user(async_transaction: AsyncSession) -> User:
    unique_email: str = "testuser@example.com"
    unique_username: str = "testuser"
    user = User(
        email=unique_email,
        username=unique_username,
        password=hash_password("testpassword").decode("utf-8"),
        is_active=True,
    )
    async_transaction.add(user)
    await async_transaction.flush()
    return user


@pytest.fixture(scope="function")
def test_user_token(test_user: User) -> str:
    return create_access_token(test_user)
