from typing import Any
from unittest.mock import AsyncMock

import pytest_asyncio
from fastapi import WebSocket
from redis.asyncio import Redis
from starlette.websockets import WebSocketState

from core.redis.pubsub_manager import RedisPubSubManager
from core.websockets.connection_manager import ConnectionManager
from core.websockets.services.websocket_service import WebSocketService

WS_BASE_PATH = "/api/v1/ws"


@pytest_asyncio.fixture
async def mock_websocket() -> AsyncMock:
    """Creates a basic mock WebSocket object for testing routes."""
    websocket = AsyncMock(spec=WebSocket)
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    websocket.receive_text = AsyncMock(return_value='{"type":"test"}')
    websocket.send_text = AsyncMock()
    websocket.client_state = WebSocketState.CONNECTING
    websocket.application_state = WebSocketState.CONNECTING
    websocket.query_params = {"token": "test_token"}
    return websocket


@pytest_asyncio.fixture
async def connected_mock_websocket(mock_websocket: AsyncMock) -> AsyncMock:
    """Provides a mock WebSocket already in CONNECTED state."""
    mock_websocket.client_state = WebSocketState.CONNECTED
    mock_websocket.application_state = WebSocketState.CONNECTED

    async def mock_accept() -> None:
        mock_websocket.client_state = WebSocketState.CONNECTED
        mock_websocket.application_state = WebSocketState.CONNECTED

    mock_websocket.accept.side_effect = mock_accept
    return mock_websocket


@pytest_asyncio.fixture
def mock_pubsub_manager() -> AsyncMock:
    """Mocks the RedisPubSubManager."""
    manager = AsyncMock(spec=RedisPubSubManager)
    manager.subscribe = AsyncMock()
    manager.unsubscribe = AsyncMock()
    manager.publish = AsyncMock()
    manager.start_listener = AsyncMock()
    manager.stop_listener = AsyncMock()
    manager.close = AsyncMock()
    return manager


@pytest_asyncio.fixture
async def mock_connection_manager(mock_pubsub_manager: AsyncMock) -> AsyncMock:
    """Mocks the ConnectionManager."""
    manager = AsyncMock(spec=ConnectionManager)
    manager.connect = AsyncMock()
    manager.disconnect = AsyncMock()
    manager.redis_client = AsyncMock(spec=Redis)
    manager.pubsub_manager = mock_pubsub_manager
    manager.active_local_connections = {}
    manager.local_chats = {}
    return manager


@pytest_asyncio.fixture
async def mock_websocket_service(mock_connection_manager: AsyncMock) -> AsyncMock:
    """Creates a mock WebSocketService for testing routes."""
    service_mock = AsyncMock(spec=WebSocketService)

    service_mock.handle_search_endpoint = AsyncMock()
    service_mock.handle_chat_endpoint = AsyncMock()
    service_mock.handle_status_endpoint = AsyncMock()

    service_mock.manager = mock_connection_manager

    async def accept_ws(*args: tuple[Any, ...], **kwargs: dict[str, Any]) -> None:
        """Handles WebSocket acceptance."""
        if args and isinstance(args[0], WebSocket):
            await args[0].accept()  # type: ignore

    service_mock.handle_search_endpoint.side_effect = accept_ws
    service_mock.handle_chat_endpoint.side_effect = accept_ws
    service_mock.handle_status_endpoint.side_effect = accept_ws

    return service_mock
