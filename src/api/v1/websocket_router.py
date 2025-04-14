import logging

from fastapi import APIRouter, Depends, WebSocket

from core.auth.dependencies import get_verified_ws_user_id, require_specific_user
from core.schemas.types import ChatID, UserID
from core.websockets.dependencies import get_websocket_service
from core.websockets.services.websocket_service import WebSocketService

log = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


@router.websocket("/search")
async def websocket_search(
    websocket: WebSocket,
    ws_service: WebSocketService = Depends(get_websocket_service),
    verified_user_id: int = Depends(get_verified_ws_user_id),
) -> None:
    await ws_service.handle_search_endpoint(websocket, verified_user_id)


@router.websocket("/chat/{chat_id}/{user_id}")
async def websocket_chat(
    websocket: WebSocket,
    chat_id: ChatID,
    user_id: UserID,
    ws_service: WebSocketService = Depends(get_websocket_service),
    _verified_user_id: int = Depends(require_specific_user),
) -> None:
    await ws_service.handle_chat_endpoint(websocket, chat_id, user_id)


@router.websocket("/status/{user_id}")
async def websocket_status(
    websocket: WebSocket,
    user_id: int,
    ws_service: WebSocketService = Depends(get_websocket_service),
    _verified_user_id: int = Depends(require_specific_user),
) -> None:
    await ws_service.handle_status_endpoint(websocket, user_id)
