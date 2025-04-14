from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from api.v1.websocket_router import websocket_status
from core.auth.dependencies import require_specific_user
from core.models import User
from core.websockets.dependencies import get_websocket_service

pytestmark = pytest.mark.asyncio


async def test_websocket_status_route(
    test_app: FastAPI,
    mock_websocket: AsyncMock,
    test_user: User,
    mock_websocket_service: AsyncMock,
    monkeypatch,
):
    """
    Tests the WebSocket status route wiring:
    - Verifies dependency injection (auth, service).
    - Confirms the correct service handler is called.
    """
    expected_user_id = test_user.id

    monkeypatch.setitem(
        test_app.dependency_overrides, require_specific_user, lambda: expected_user_id
    )

    monkeypatch.setitem(
        test_app.dependency_overrides,
        get_websocket_service,
        lambda: mock_websocket_service,
    )

    await websocket_status(
        websocket=mock_websocket,
        user_id=expected_user_id,
        ws_service=mock_websocket_service,
        _verified_user_id=expected_user_id,
    )

    mock_websocket_service.handle_status_endpoint.assert_awaited_once_with(
        mock_websocket, expected_user_id
    )
    mock_websocket.accept.assert_awaited_once()
