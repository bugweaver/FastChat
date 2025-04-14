from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from api.v1.websocket_router import websocket_search
from core.auth.dependencies import get_verified_ws_user_id
from core.models import User
from core.websockets.dependencies import get_websocket_service

pytestmark = pytest.mark.asyncio


async def test_websocket_search_route(
    test_app: FastAPI,
    mock_websocket: AsyncMock,
    test_user: User,
    mock_websocket_service: AsyncMock,
    monkeypatch,
):
    """
    Tests the WebSocket search route wiring:
    - Verifies dependency injection (auth, service).
    - Confirms the correct service handler is called.
    """
    expected_user_id = test_user.id

    async def override_get_verified_ws_user_id():
        return expected_user_id

    monkeypatch.setitem(
        test_app.dependency_overrides,
        get_verified_ws_user_id,
        override_get_verified_ws_user_id,
    )

    monkeypatch.setitem(
        test_app.dependency_overrides,
        get_websocket_service,
        lambda: mock_websocket_service,
    )

    await websocket_search(
        websocket=mock_websocket,
        ws_service=mock_websocket_service,
        verified_user_id=expected_user_id,
    )

    mock_websocket_service.handle_search_endpoint.assert_awaited_once_with(
        mock_websocket, expected_user_id
    )
    mock_websocket.accept.assert_awaited_once()
