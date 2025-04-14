import asyncio
import logging
from collections import defaultdict
from typing import Any

import orjson as json
from fastapi import WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from core.chat.services.redis_service import set_online_status
from core.redis.keys import (
    CHAT_MESSAGES_PATTERN,
    DELETED_MESSAGES_PATTERN,
    get_chat_connections_key,
    get_chat_message_channel,
    get_user_chats_key,
)
from core.redis.pubsub_manager import RedisPubSubManager

log = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections using Redis for scalability
    and Pub/Sub for messaging between instances.
    """

    def __init__(
        self,
        redis_url: str,
        redis_client: Redis,
        heartbeat_interval: int = 45,
        connection_ttl: int = 60,
    ) -> None:
        """
        Initializes the ConnectionManager.
        """
        self.redis_client = redis_client
        self.pubsub_manager = RedisPubSubManager(redis_url)
        self.heartbeat_interval = heartbeat_interval
        self.connection_ttl = connection_ttl
        self.active_local_connections: dict[WebSocket, tuple[str, str]] = {}
        self.local_chats: dict[str, set[WebSocket]] = defaultdict(set)
        self._heartbeat_tasks: dict[WebSocket, asyncio.Task] = {}
        self._pubsub_listener_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Initializing Pub/Sub subscriptions."""
        log.info("Initializing ConnectionManager Pub/Sub subscriptions...")
        await self.pubsub_manager.subscribe(
            CHAT_MESSAGES_PATTERN, self._handle_chat_message_pubsub
        )
        await self.pubsub_manager.subscribe(
            DELETED_MESSAGES_PATTERN, self._handle_deleted_message_pubsub
        )
        log.info("ConnectionManager Pub/Sub subscriptions initialized.")

    async def connect(self, websocket: WebSocket, chat_id: str, user_id: str) -> None:
        """Registers a new WebSocket connection locally and in Redis."""
        await websocket.accept()
        log.info("WebSocket accepted for user %s in chat %s", user_id, chat_id)

        self.active_local_connections[websocket] = (user_id, chat_id)
        self.local_chats[chat_id].add(websocket)

        try:
            async with self.redis_client.pipeline(transaction=True) as pipe:
                await pipe.sadd(get_chat_connections_key(chat_id), user_id)
                await pipe.expire(
                    get_chat_connections_key(chat_id), self.connection_ttl
                )
                await pipe.sadd(get_user_chats_key(user_id), chat_id)
                await pipe.expire(get_user_chats_key(user_id), self.connection_ttl)
                await pipe.execute()
            log.debug(
                "User %s connection to chat %s registered in Redis.", user_id, chat_id
            )
        except Exception as e:
            log.error(
                "Failed to register connection in Redis for user %s, chat %s: %s",
                user_id,
                chat_id,
                e,
            )

        await set_online_status(self.redis_client, user_id, True)

        if websocket not in self._heartbeat_tasks:
            self._heartbeat_tasks[websocket] = asyncio.create_task(
                self._heartbeat_loop(websocket)
            )
            log.debug("Heartbeat task started for user %s in chat %s", user_id, chat_id)

    async def disconnect(
        self,
        websocket: WebSocket,
        code: int = status.WS_1000_NORMAL_CLOSURE,
        reason: str = "Disconnecting",
    ) -> None:
        """Disables WebSocket, removes it from local structures and Redis."""
        if websocket in self.active_local_connections:
            user_id, chat_id = self.active_local_connections[websocket]
            log.info("Disconnecting user %s from chat %s...", user_id, chat_id)

            if websocket in self._heartbeat_tasks:
                task = self._heartbeat_tasks.pop(websocket, None)
                if task:
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

            del self.active_local_connections[websocket]
            if websocket in self.local_chats.get(chat_id, set()):
                self.local_chats[chat_id].remove(websocket)
                if not self.local_chats[chat_id]:
                    del self.local_chats[chat_id]

            try:
                async with self.redis_client.pipeline(transaction=True) as pipe:
                    await pipe.srem(get_chat_connections_key(chat_id), user_id)
                    await pipe.srem(get_user_chats_key(user_id), chat_id)
                    await pipe.exists(get_user_chats_key(user_id))
                    results = await pipe.execute()

                user_has_other_chats = results[2] > 0
                log.debug(
                    "Redis cleanup results for user %s, chat %s: %s."
                    " Has other chats: %s",
                    user_id,
                    chat_id,
                    results[:2],
                    user_has_other_chats,
                )

                await set_online_status(self.redis_client, user_id, False)

            except Exception as e:
                log.error(
                    "Failed to clean up Redis connection for user %s, chat %s: %s",
                    user_id,
                    chat_id,
                    e,
                )

            try:
                await websocket.close(code=code, reason=reason)
                log.info(
                    "WebSocket closed for user %s, chat %s. Code: %d",
                    user_id,
                    chat_id,
                    code,
                )
            except RuntimeError as e:
                log.warning(
                    "Error closing WebSocket for"
                    " user %s, chat %s (possibly already closed): %s",
                    user_id,
                    chat_id,
                    e,
                )
            except Exception as e:
                log.error(
                    "Unexpected error closing WebSocket for user %s, chat %s: %s",
                    user_id,
                    chat_id,
                    e,
                )
        else:
            log.warning("Attempted to disconnect a non-tracked WebSocket.")
            await websocket.close(code=code, reason=reason)

    async def _heartbeat_loop(self, websocket: WebSocket) -> None:
        """Periodically sends ping and checks the connection."""
        while websocket in self.active_local_connections:
            try:
                await websocket.send_text('{"type": "ping"}')
                log.debug("Sent ping to websocket %d", id(websocket))
                await asyncio.sleep(self.heartbeat_interval)
            except (WebSocketDisconnect, asyncio.CancelledError) as e:
                log.info(
                    "Heartbeat loop stopped for websocket %d: %s",
                    id(websocket),
                    type(e).__name__,
                )
                break
            except Exception as e:
                log.error(
                    "Heartbeat failed for websocket %d: %s. Disconnecting.",
                    id(websocket),
                    e,
                )
                await self.disconnect(
                    websocket,
                    code=status.WS_1011_INTERNAL_ERROR,
                    reason="Heartbeat failure",
                )
                break

    async def broadcast_to_chat_via_pubsub(
        self,
        chat_id: str,
        payload: dict[str, Any],
        sender_user_id: str | None = None,
    ) -> None:
        """Publishes a message to a chat channel via Redis Pub/Sub."""
        channel = get_chat_message_channel(chat_id)
        full_payload = {
            "type": payload.get("type", "message"),
            "sender_id": sender_user_id,
            "data": payload,
        }
        await self.pubsub_manager.publish(channel, full_payload)

    async def _handle_chat_message_pubsub(self, message: dict[str, Any]) -> None:
        """Handler for chat messages received via Pub/Sub."""
        log.debug("Received chat message via PubSub: %s", message)
        try:
            chat_id = message.get("data", {}).get("chat_id")
            sender_id = message.get("sender_id")
            payload_to_send = message.get("data")

            if not chat_id or not payload_to_send:
                log.warning(
                    "Invalid chat message received via PubSub"
                    " (missing chat_id or data): %s",
                    message,
                )
                return

            chat_id = chat_id

            if chat_id in self.local_chats:
                tasks = []
                for ws in list(self.local_chats[chat_id]):
                    ws_user_id, _ = self.active_local_connections.get(ws, (None, None))
                    if ws_user_id and sender_id and ws_user_id == sender_id:
                        log.debug(
                            "Skipping broadcast to sender %s in chat %s",
                            sender_id,
                            chat_id,
                        )
                        continue

                    log.debug(
                        "Sending message to local user %s in chat %s",
                        ws_user_id,
                        chat_id,
                    )
                    tasks.append(self._send_to_websocket(ws, payload_to_send))

                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for _i, result in enumerate(results):
                        if isinstance(result, Exception):
                            log.warning(
                                "Error sending message to a"
                                " local websocket in chat %s: %s",
                                chat_id,
                                result,
                            )

        except Exception as e:
            log.exception(
                "Error processing chat message from PubSub: %s. Message: %s", e, message
            )

    async def _handle_deleted_message_pubsub(self, message: dict[str, Any]) -> None:
        """Message deletion notification handler."""
        try:
            chat_id = message.get("chat_id")
            message_id = message.get("message_id")
            payload_to_send = message

            if not chat_id or not message_id:
                log.warning(
                    "Invalid deleted message notification received via PubSub: %s",
                    message,
                )
                return

            if chat_id in self.local_chats:
                tasks = [
                    self._send_to_websocket(ws, payload_to_send)
                    for ws in list(self.local_chats[chat_id])
                ]
                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for _i, result in enumerate(results):
                        if isinstance(result, Exception):
                            log.warning(
                                "Error sending deletion notification"
                                " to a local websocket in chat %s: %s",
                                chat_id,
                                result,
                            )

        except Exception as e:
            log.exception(
                "Error processing deleted message notification from PubSub:"
                " %s. Message: %s",
                e,
                message,
            )

    async def _send_to_websocket(
        self, websocket: WebSocket, payload: dict[str, Any]
    ) -> bool:
        """Securely sends a JSON message over a WebSocket."""
        if websocket in self.active_local_connections:
            try:
                await websocket.send_text(json.dumps(payload).decode("utf-8"))
                return True
            except WebSocketDisconnect:
                log.info("Client %d disconnected during send.", id(websocket))
                await self.disconnect(websocket)
            except Exception as e:
                log.error(
                    "Failed to send message to websocket %d: %s", id(websocket), e
                )
                await self.disconnect(
                    websocket, code=status.WS_1011_INTERNAL_ERROR, reason="Send error"
                )
        return False

    async def close(self) -> None:
        """Closes all active connections and Pub/Sub."""
        log.info("Closing ConnectionManager...")
        await self.pubsub_manager.close()

        tasks = [
            self.disconnect(
                ws, code=status.WS_1012_SERVICE_RESTART, reason="Server shutting down"
            )
            for ws in list(self.active_local_connections.keys())
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for task in self._heartbeat_tasks.values():
            task.cancel()
        if self._heartbeat_tasks:
            await asyncio.gather(
                *self._heartbeat_tasks.values(), return_exceptions=True
            )

        self.active_local_connections.clear()
        self.local_chats.clear()
        self._heartbeat_tasks.clear()
        log.info("ConnectionManager closed.")
