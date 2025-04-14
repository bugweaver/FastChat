from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from _pytest.monkeypatch import MonkeyPatch
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.auth.dependencies import get_token_service
from core.auth.services.token_service import TokenService
from core.dependencies import get_redis_client
from core.models import db_helper
from core.websockets.connection_manager import ConnectionManager
from core.websockets.dependencies import get_connection_manager
from main import app
from tests.fixtures.db import override_get_async_session


@pytest.fixture(scope="session")
def monkeypatch_session() -> Generator[MonkeyPatch, Any, None]:
    from _pytest.monkeypatch import MonkeyPatch

    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest_asyncio.fixture(scope="session")
def test_app(
    fake_redis_instance: FakeAsyncRedis,
) -> Generator[FastAPI, Any, None]:
    """
    FastAPI application with substituted dependencies for session tests.
    Uses direct modification of app.dependency_overrides.
    """

    async def _override_get_redis() -> FakeAsyncRedis:
        return fake_redis_instance

    async def _override_get_token_service() -> TokenService:
        return TokenService(fake_redis_instance)

    mock_conn_manager = AsyncMock(spec=ConnectionManager)
    mock_conn_manager.initialize = AsyncMock()
    mock_conn_manager.close = AsyncMock()
    mock_conn_manager.connect = AsyncMock()
    mock_conn_manager.disconnect = AsyncMock()
    mock_conn_manager.broadcast_to_chat_via_pubsub = AsyncMock()

    async def _override_get_connection_manager() -> AsyncMock:
        return mock_conn_manager

    original_overrides = app.dependency_overrides.copy()

    app.dependency_overrides[db_helper.session_getter] = override_get_async_session
    app.dependency_overrides[get_redis_client] = _override_get_redis
    app.dependency_overrides[get_token_service] = _override_get_token_service
    app.dependency_overrides[get_connection_manager] = _override_get_connection_manager

    app.state.redis_client = fake_redis_instance
    app.state.connection_manager = mock_conn_manager

    yield app

    app.dependency_overrides = original_overrides

    if hasattr(app.state, "redis_client"):
        del app.state.redis_client
    if hasattr(app.state, "connection_manager"):
        del app.state.connection_manager


@pytest_asyncio.fixture(scope="function")
async def async_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://testserver"
    ) as client:
        yield client
