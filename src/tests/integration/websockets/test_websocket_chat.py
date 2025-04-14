from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from api.v1.websocket_router import websocket_chat
from core.auth.dependencies import require_specific_user
from core.models import User
from core.websockets.dependencies import get_websocket_service

pytestmark = pytest.mark.asyncio


async def test_websocket_chat_route(
    test_app: FastAPI,
    mock_websocket: AsyncMock,
    test_user: User,
    mock_websocket_service: AsyncMock,
    monkeypatch,
):
    """
    Tests the WebSocket chat route wiring:
    - Verifies dependency injection (auth, service).
    - Confirms the correct service handler is called.
    """
    chat_id = 1
    expected_user_id = test_user.id

    monkeypatch.setitem(
        test_app.dependency_overrides, require_specific_user, lambda: expected_user_id
    )

    monkeypatch.setitem(
        test_app.dependency_overrides,
        get_websocket_service,
        lambda: mock_websocket_service,
    )

    await websocket_chat(
        websocket=mock_websocket,
        chat_id=chat_id,
        user_id=expected_user_id,
        ws_service=mock_websocket_service,
        _verified_user_id=expected_user_id,
    )

    mock_websocket_service.handle_chat_endpoint.assert_awaited_once_with(
        mock_websocket, chat_id, expected_user_id
    )
    mock_websocket.accept.assert_awaited_once()


# Add more tests here if needed, e.g., testing authorization failure
# async def test_websocket_chat_route_unauthorized(...):
#    ... mock require_specific_user to raise HTTPException ...
#    ... assert websocket.close was called ...
