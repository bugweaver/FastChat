import asyncio
import logging

import orjson as json
from fastapi import HTTPException, WebSocket, status
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from core.chat.services.message_service import MessageService
from core.chat.services.redis_service import (
    get_online_users,
)
from core.schemas.ws_schemas import (
    BaseWsMessage,
    IncomingChatMessage,
    IncomingChatPayload,
    InitialStatusData,
    InitialStatusResp,
    PingMessage,
    PongMessageResp,
    SearchQueryMessage,
    SearchResultsResp,
    UserSearchResultData,
    WsErrorData,
    WsErrorResp,
    parse_ws_message,
)
from core.websockets.connection_manager import ConnectionManager
from repositories.chat_repo import get_chat_by_id, check_user_in_chat
from repositories.user_repo import get_users_by_username

log = logging.getLogger(__name__)


class WebSocketService:
    HEARTBEAT_TIMEOUT = 60
    MAX_MESSAGE_SIZE = 16 * 1024  # 16 KB

    def __init__(
        self, db: AsyncSession, redis_client: Redis, manager: ConnectionManager
    ) -> None:
        self.db = db
        self.redis_client = redis_client
        self.manager = manager

    async def _send_error(
        self,
        websocket: WebSocket,
        message: str,
        code: int = status.WS_1011_INTERNAL_ERROR,
    ) -> None:
        try:
            error_resp = WsErrorResp(error=WsErrorData(message=message, code=code))
            await websocket.send_text(
                json.dumps(error_resp.model_dump()).decode("utf-8")
            )
            log.warning(
                "Sent error to WebSocket %d: Code %d, Message: %s",
                id(websocket),
                code,
                message,
            )
        except WebSocketDisconnect:
            log.info(
                "WebSocket %d disconnected while sending error: %s",
                id(websocket),
                message,
            )
        except Exception as e:
            log.error("Failed to send error to WebSocket %d: %s", id(websocket), e)

    async def handle_search_endpoint(self, websocket: WebSocket, user_id: int) -> None:
        log.info(
            "WebSocket /search: User %d verified. Accepting connection...", user_id
        )
        try:
            await websocket.accept()
            log.info("WebSocket /search: Connection accepted for user %d.", user_id)
            await self._search_message_loop(websocket, user_id)
        except WebSocketDisconnect as e:
            log.info(
                "WebSocket /search: Connection closed by client (user %d). Code: %s",
                user_id,
                e.code,
            )
        except Exception as e:
            log.exception(
                "WebSocket /search: Unexpected error for user %d: %s", user_id, e
            )
            if websocket.client_state == websocket.application_state.CONNECTED:
                await self._safe_close_ws(websocket, code=status.WS_1011_INTERNAL_ERROR)
        finally:
            log.info(
                "WebSocket /search: Finished handling connection for user %d.", user_id
            )

    async def handle_chat_endpoint(
        self,
        websocket: WebSocket,
        chat_id: int,
        user_id: int,
    ) -> None:
        log.info(
            "WebSocket /chat: User %d attempting connection to chat %d.",
            user_id,
            chat_id,
        )

        try:
            chat = await get_chat_by_id(self.db, chat_id)
            if not chat:
                log.warning(
                    "WebSocket /chat: Chat %d not found for user %d.", chat_id, user_id
                )
                await self._safe_close_ws(
                    websocket, status.WS_1008_POLICY_VIOLATION, "Chat not found"
                )
                return

            is_participant = await check_user_in_chat(self.db, user_id, chat_id)
            if not is_participant:
                log.warning(
                    "WebSocket /chat: User %d forbidden access to chat %d.",
                    user_id,
                    chat_id,
                )
                await self._safe_close_ws(
                    websocket, status.WS_1008_POLICY_VIOLATION, "Access Forbidden"
                )
                return

            log.info(
                "WebSocket /chat: User %d access to chat %d verified.", user_id, chat_id
            )

            await self.manager.connect(websocket, str(chat_id), str(user_id))

            await self._chat_message_loop(websocket, chat_id, user_id)

        except WebSocketDisconnect as e:
            log.info(
                "WebSocket /chat: Connection closed (user %d, chat %d). Code: %s",
                user_id,
                chat_id,
                e.code,
            )
        except Exception:
            log.exception(
                "WebSocket /chat: Unexpected error for user %d in chat %d",
                user_id,
                chat_id,
            )
            if websocket in self.manager.active_local_connections:
                await self.manager.disconnect(
                    websocket, code=status.WS_1011_INTERNAL_ERROR
                )
            else:
                await self._safe_close_ws(websocket, code=status.WS_1011_INTERNAL_ERROR)
        finally:
            log.info(
                "WebSocket /chat: Finished handling connection for user %d, chat %d.",
                user_id,
                chat_id,
            )

    async def handle_status_endpoint(self, websocket: WebSocket, user_id: int) -> None:
        log.info(
            "WebSocket /status: User %d verified. Accepting connection...", user_id
        )
        try:
            await websocket.accept()
            log.info("WebSocket /status: Connection accepted for user %d.", user_id)

            online_users_set = await get_online_users(self.redis_client)
            initial_data = InitialStatusData(online_users=list(online_users_set))
            initial_resp = InitialStatusResp(data=initial_data)

            await websocket.send_text(
                json.dumps(initial_resp.model_dump()).decode("utf-8")
            )
            log.debug(
                "Sent initial online users (%d) to user %d.",
                len(initial_data.online_users),
                user_id,
            )

            await self._keep_alive_loop(websocket, user_id, "/status")

        except WebSocketDisconnect as e:
            log.info(
                "WebSocket /status: Connection closed by client (user %d). Code: %s",
                user_id,
                e.code,
            )
        except Exception as e:
            log.exception(
                "WebSocket /status: Unexpected error for user %d: %s", user_id, e
            )
            await self._safe_close_ws(websocket, code=status.WS_1011_INTERNAL_ERROR)
        finally:
            log.info(
                "WebSocket /status: Finished handling connection for user %d.", user_id
            )

    async def _search_message_loop(self, websocket: WebSocket, user_id: int) -> None:
        while True:
            try:
                data_text = await websocket.receive_text()
                if len(data_text) > self.MAX_MESSAGE_SIZE:
                    await self._send_error(
                        websocket, "Message too large.", status.WS_1009_MESSAGE_TOO_BIG
                    )
                    continue

                parsed_message = parse_ws_message(data_text)

                if isinstance(parsed_message, PingMessage):
                    await websocket.send_text(
                        json.dumps(PongMessageResp().model_dump()).decode("utf-8")
                    )
                elif isinstance(parsed_message, SearchQueryMessage):
                    query = parsed_message.query
                    if not query or not query.strip():
                        results_resp = SearchResultsResp(results=[])
                    else:
                        results_data = await self._perform_user_search(
                            query.strip(), user_id
                        )
                        results_resp = SearchResultsResp(results=results_data)
                    await websocket.send_text(
                        json.dumps(results_resp.model_dump()).decode("utf-8")
                    )
                else:
                    await self._send_error(
                        websocket,
                        "Unsupported message type for search.",
                        status.WS_1003_UNSUPPORTED_DATA,
                    )

            except WebSocketDisconnect:
                raise
            except ValidationError as e:
                log.warning(
                    "Search WS validation error for user %d: %s", user_id, e.errors()
                )
                await self._send_error(
                    websocket,
                    f"Invalid message format: {e.errors()}",
                    status.WS_1003_UNSUPPORTED_DATA,
                )
            except Exception as e:
                log.exception(
                    "Error processing message in /search loop for user %d: %s",
                    user_id,
                    e,
                )
                await self._send_error(
                    websocket, "Internal server error processing message."
                )

    async def _chat_message_loop(
        self, websocket: WebSocket, chat_id: int, user_id: int
    ) -> None:
        while True:
            try:
                data_text = await asyncio.wait_for(
                    websocket.receive_text(), timeout=self.HEARTBEAT_TIMEOUT
                )

                if len(data_text) > self.MAX_MESSAGE_SIZE:
                    await self._send_error(
                        websocket, "Message too large.", status.WS_1009_MESSAGE_TOO_BIG
                    )
                    continue

                parsed_message: BaseWsMessage | str | None = parse_ws_message(data_text)

                if isinstance(parsed_message, PingMessage):
                    await websocket.send_text(
                        json.dumps(PongMessageResp().model_dump()).decode("utf-8")
                    )
                elif isinstance(parsed_message, IncomingChatMessage) and isinstance(
                    parsed_message.data, IncomingChatPayload
                ):
                    payload = parsed_message.data

                    await MessageService.create_message(
                        db=self.db,
                        content=payload.content,
                        sender_id=user_id,
                        chat_id=chat_id,
                        reply_to_id=payload.reply_to_id,
                        redis=self.redis_client,
                    )
                elif isinstance(parsed_message, str) and parsed_message.strip():
                    await MessageService.create_message(
                        db=self.db,
                        content=parsed_message.strip(),
                        sender_id=user_id,
                        chat_id=chat_id,
                        reply_to_id=None,
                        redis=self.redis_client,
                    )
                else:
                    await self._send_error(
                        websocket,
                        "Unsupported message type or format.",
                        status.WS_1003_UNSUPPORTED_DATA,
                    )

            except asyncio.TimeoutError:
                log.warning(
                    "WebSocket %d timed out waiting for message (user %d, chat %d)."
                    " Closing.",
                    id(websocket),
                    user_id,
                    chat_id,
                )
                await self.manager.disconnect(
                    websocket,
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Inactivity timeout",
                )
                break
            except WebSocketDisconnect:
                raise
            except ValidationError as e:
                log.warning(
                    "Chat WS validation error for user %d, chat %d: %s",
                    user_id,
                    chat_id,
                    e.errors(),
                )
                await self._send_error(
                    websocket,
                    f"Invalid message format: {e.errors()}",
                    status.WS_1003_UNSUPPORTED_DATA,
                )
                continue
            except HTTPException as http_exc:
                log.error(
                    "HTTP Exception during message processing for user %d, chat %d: %s",
                    user_id,
                    chat_id,
                    http_exc.detail,
                )
                await self._send_error(
                    websocket,
                    f"Failed to process message: {http_exc.detail}",
                    code=status.WS_1011_INTERNAL_ERROR,
                )
                continue
            except Exception as e:
                log.exception(
                    "Error processing message in /chat loop for user %d, chat %d: %s",
                    user_id,
                    chat_id,
                    e,
                )
                await self._send_error(
                    websocket, "Internal server error processing message."
                )
                continue

    async def _keep_alive_loop(
        self, websocket: WebSocket, user_id: int, endpoint: str
    ) -> None:
        while True:
            try:
                data_text = await asyncio.wait_for(
                    websocket.receive_text(), timeout=self.HEARTBEAT_TIMEOUT
                )
                parsed_message = parse_ws_message(data_text)
                if isinstance(parsed_message, PingMessage):
                    await websocket.send_text(
                        json.dumps(PongMessageResp().model_dump()).decode("utf-8")
                    )
                else:
                    log.debug(
                        "Received ignored message type on %s from user %d: %s",
                        endpoint,
                        user_id,
                        type(parsed_message),
                    )

            except asyncio.TimeoutError:
                log.warning(
                    "WebSocket %d timed out (%s, user %d). Closing.",
                    id(websocket),
                    endpoint,
                    user_id,
                )
                await self._safe_close_ws(
                    websocket,
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="Inactivity timeout",
                )
                break
            except WebSocketDisconnect:
                raise
            except Exception as e:
                log.exception(
                    "Error in keep-alive loop (%s, user %d): %s", endpoint, user_id, e
                )
                await self._safe_close_ws(websocket, code=status.WS_1011_INTERNAL_ERROR)
                break

    async def _perform_user_search(
        self, query: str, current_user_id: int
    ) -> list[UserSearchResultData]:
        try:
            users = await get_users_by_username(self.db, query)
            log.info(
                "Search query '%s' by user %d: found %d potential users.",
                query,
                current_user_id,
                len(users),
            )

            user_data_list = []
            if not users:
                return []

            online_users_set = await get_online_users(self.redis_client)

            for user in users:
                if user.id == current_user_id:
                    continue

                is_online = str(user.id) in online_users_set

                try:
                    user_data = UserSearchResultData(
                        id=user.id,
                        username=user.username,
                        avatar=user.avatar,
                        is_online=is_online,
                    )
                    user_data_list.append(user_data)
                except ValidationError as e:
                    log.error(
                        "Data validation failed for user search result %d: %s",
                        user.id,
                        e,
                    )
            return user_data_list
        except Exception as e:
            log.exception(
                "Database or Redis error during user search for query '%s': %s",
                query,
                e,
            )
            return []

    async def _safe_close_ws(
        self,
        websocket: WebSocket,
        code: int = status.WS_1000_NORMAL_CLOSURE,
        reason: str = "",
    ) -> None:
        try:
            await websocket.close(code=code, reason=reason)
        except RuntimeError as e:
            if "WebSocket is not connected" in str(e):
                log.warning(
                    "Attempted to close WebSocket %s which was already closed.",
                    id(websocket),
                )
            else:
                raise e
        except Exception as e:
            log.error("Unexpected error closing WebSocket %s: %s", id(websocket), e)
