import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import orjson as json
import pytest
from fastapi import WebSocket, status
from redis.asyncio import Redis

from core.redis.keys import (
    CHAT_MESSAGES_PATTERN,
    DELETED_MESSAGES_PATTERN,
    get_chat_connections_key,
    get_user_chats_key,
)
from core.websockets.connection_manager import ConnectionManager
from tests.factories.chat_factory import ChatFactory, MessageFactory
from tests.factories.user_factory import UserFactory

pytestmark = pytest.mark.asyncio
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis_client = AsyncMock(spec=Redis)

    pipe = AsyncMock()
    pipe.sadd = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.srem = AsyncMock()
    pipe.exists = AsyncMock(return_value=1)
    pipe.execute = AsyncMock(return_value=[1, 1, 1])

    pipeline_cm = AsyncMock()
    pipeline_cm.__aenter__ = AsyncMock(return_value=pipe)
    pipeline_cm.__aexit__ = AsyncMock(return_value=None)

    redis_client.pipeline = MagicMock(return_value=pipeline_cm)

    return redis_client


class TestNewConnectionManager:
    @pytest.fixture
    async def connection_manager(
        self, mock_redis: AsyncMock, mock_pubsub_manager: AsyncMock
    ) -> ConnectionManager:
        with patch(
            "core.websockets.connection_manager.set_online_status",
            new_callable=AsyncMock,
        ) as mock_set_status:
            manager = ConnectionManager(
                redis_url="redis://mockhost",
                redis_client=mock_redis,
                heartbeat_interval=0.1,
            )
            manager.pubsub_manager = mock_pubsub_manager
            manager._mock_set_online_status = mock_set_status
            yield manager

    @pytest.fixture
    async def test_user1(self, db_session_for_fixtures):
        return await UserFactory.create_async(session=db_session_for_fixtures)

    @pytest.fixture
    async def test_user2(self, db_session_for_fixtures):
        return await UserFactory.create_async(session=db_session_for_fixtures)

    @pytest.fixture
    async def test_sender(self, db_session_for_fixtures):
        return await UserFactory.create_async(session=db_session_for_fixtures)

    @pytest.fixture
    async def test_chat(self, db_session_for_fixtures, test_user1, test_user2):
        return await ChatFactory.create_private_chat(
            session=db_session_for_fixtures, user1=test_user1, user2=test_user2
        )

    async def test_initialize_subscribes_to_patterns(
        self, connection_manager: ConnectionManager, mock_pubsub_manager: AsyncMock
    ):
        """Checks that initialize subscribes to the required Pub/Sub patterns."""
        await connection_manager.initialize()
        expected_calls = [
            call(CHAT_MESSAGES_PATTERN, connection_manager._handle_chat_message_pubsub),
            call(
                DELETED_MESSAGES_PATTERN,
                connection_manager._handle_deleted_message_pubsub,
            ),
        ]
        mock_pubsub_manager.subscribe.assert_has_calls(expected_calls, any_order=True)

    async def test_connect_registers_local_and_redis_starts_heartbeat(
        self,
        connection_manager: ConnectionManager,
        connected_mock_websocket: AsyncMock,
        mock_redis: AsyncMock,
        test_user1,
        test_chat,
    ):
        """Tests connection registration, Redis calls, and heartbeat startup."""
        user_id = test_user1.id
        chat_id = test_chat.id

        ws_key = connected_mock_websocket

        connection_manager.active_local_connections.clear()
        connection_manager.local_chats.clear()
        connection_manager._heartbeat_tasks.clear()

        await connection_manager.connect(connected_mock_websocket, chat_id, user_id)

        connected_mock_websocket.accept.assert_awaited_once()
        assert ws_key in connection_manager.active_local_connections
        assert connection_manager.active_local_connections[ws_key] == (user_id, chat_id)
        assert ws_key in connection_manager.local_chats[chat_id]

        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        expected_sadd_calls = [
            call(get_chat_connections_key(chat_id), user_id),
            call(get_user_chats_key(user_id), chat_id),
        ]
        actual_sadd_calls = pipe.sadd.call_args_list
        assert expected_sadd_calls[0] in actual_sadd_calls
        assert expected_sadd_calls[1] in actual_sadd_calls

        pipe.expire.assert_has_calls(
            [
                call(
                    get_chat_connections_key(chat_id), connection_manager.connection_ttl
                ),
                call(get_user_chats_key(user_id), connection_manager.connection_ttl),
            ],
            any_order=True,
        )
        pipe.execute.assert_awaited_once()

        connection_manager._mock_set_online_status.assert_awaited_once_with(
            mock_redis, user_id, True
        )

        assert ws_key in connection_manager._heartbeat_tasks

        if ws_key in connection_manager._heartbeat_tasks:
            heartbeat_task = connection_manager._heartbeat_tasks.pop(ws_key)
            heartbeat_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(heartbeat_task), timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def test_disconnect_removes_local_redis_stops_heartbeat_updates_status(
        self,
        connection_manager: ConnectionManager,
        connected_mock_websocket: AsyncMock,
        mock_redis: AsyncMock,
        test_user1,
        test_chat,
    ):
        """Tests removing connection, stopping heartbeat and updating status."""
        user_id = test_user1.id
        chat_id = test_chat.id

        ws_key = connected_mock_websocket

        await connection_manager.connect(ws_key, chat_id, user_id)
        connection_manager._mock_set_online_status.reset_mock()

        assert ws_key in connection_manager._heartbeat_tasks
        heartbeat_task = connection_manager._heartbeat_tasks[ws_key]
        assert not heartbeat_task.done()

        pipe = AsyncMock()
        pipe.srem = AsyncMock()
        pipe.exists = AsyncMock(return_value=0)
        pipe.execute = AsyncMock(return_value=[1, 1, 0])
        mock_redis.pipeline.return_value.__aenter__.return_value = pipe

        await connection_manager.disconnect(ws_key)

        assert ws_key not in connection_manager.active_local_connections
        assert chat_id not in connection_manager.local_chats
        assert ws_key not in connection_manager._heartbeat_tasks

        assert heartbeat_task.cancelled()

        pipe.srem.assert_has_calls(
            [
                call(get_chat_connections_key(chat_id), user_id),
                call(get_user_chats_key(user_id), chat_id),
            ],
            any_order=True,
        )
        pipe.exists.assert_awaited_once_with(get_user_chats_key(user_id))
        pipe.execute.assert_awaited_once()

        connection_manager._mock_set_online_status.assert_awaited_once_with(
            mock_redis, user_id, False
        )

        ws_key.close.assert_awaited_once_with(
            code=status.WS_1000_NORMAL_CLOSURE, reason="Disconnecting"
        )
        await asyncio.sleep(0)

    async def test_handle_chat_message_pubsub_sends_to_local_clients(
        self,
        connection_manager: ConnectionManager,
        mock_websocket: AsyncMock,
        test_user1,
        test_user2,
        test_sender,
        test_chat,
        db_session_for_fixtures,
    ):
        """Tests sending Pub/Sub message to local clients in chat."""
        chat_id = test_chat.id
        user_id1 = test_user1.id
        user_id2 = test_user2.id
        sender_id = test_sender.id

        ws1 = AsyncMock(spec=WebSocket)
        ws1.send_text = AsyncMock()

        ws2 = AsyncMock(spec=WebSocket)
        ws2.send_text = AsyncMock()

        ws3 = AsyncMock(spec=WebSocket)
        ws3.send_text = AsyncMock(side_effect=Exception("Send failed"))

        ws_sender = AsyncMock(spec=WebSocket)
        ws_sender.send_text = AsyncMock()

        connection_manager.active_local_connections = {
            ws1: (user_id1, chat_id),
            ws2: (user_id2, chat_id),
            ws3: (user_id2, chat_id),
            ws_sender: (sender_id, chat_id),
        }
        connection_manager.local_chats = {chat_id: {ws1, ws2, ws3, ws_sender}}

        message = await MessageFactory.create_in_chat(
            session=db_session_for_fixtures, chat=test_chat, sender=test_sender
        )

        message_data = {
            "id": message.id,
            "content": message.content,
            "chat_id": chat_id,
        }
        pubsub_payload = {
            "type": "new_message",
            "sender_id": sender_id,
            "data": message_data,
        }
        expected_sent_json_str = json.dumps(message_data).decode("utf-8")

        with patch.object(
            connection_manager, "disconnect", AsyncMock()
        ) as mock_disconnect:
            await connection_manager._handle_chat_message_pubsub(pubsub_payload)

            ws1.send_text.assert_awaited_once_with(expected_sent_json_str)
            ws2.send_text.assert_awaited_once_with(expected_sent_json_str)
            ws3.send_text.assert_awaited_once_with(expected_sent_json_str)
            ws_sender.send_text.assert_not_awaited()

            mock_disconnect.assert_awaited_once_with(
                ws3, code=status.WS_1011_INTERNAL_ERROR, reason="Send error"
            )

    async def test_handle_deleted_message_pubsub_sends_to_local_clients(
        self,
        connection_manager: ConnectionManager,
        test_user1,
        test_chat,
        db_session_for_fixtures,
    ):
        """Tests sending a notification about message deletion."""
        chat_id = test_chat.id
        user_id1 = test_user1.id

        ws1 = AsyncMock(spec=WebSocket)
        ws1.send_text = AsyncMock()

        connection_manager.active_local_connections = {ws1: (user_id1, chat_id)}
        connection_manager.local_chats = {chat_id: {ws1}}

        message = await MessageFactory.create_in_chat(
            session=db_session_for_fixtures, chat=test_chat, sender=test_user1
        )

        from datetime import datetime, timezone

        deleted_time = datetime.now(timezone.utc)

        pubsub_payload = {
            "type": "message_deleted",
            "message_id": message.id,
            "chat_id": chat_id,
            "deleted_at": deleted_time,
        }
        expected_sent_json_str = json.dumps(pubsub_payload).decode("utf-8")

        await connection_manager._handle_deleted_message_pubsub(pubsub_payload)

        ws1.send_text.assert_awaited_once_with(expected_sent_json_str)

    async def test_heartbeat_loop_sends_ping_and_disconnects_on_error(
        self,
        connection_manager: ConnectionManager,
        connected_mock_websocket: AsyncMock,
        test_user1,
        test_chat,
    ):
        """Tests sending ping and calling disconnect on sending error."""
        user_id = test_user1.id
        chat_id = test_chat.id

        ws_key = connected_mock_websocket

        connection_manager.active_local_connections[ws_key] = (user_id, chat_id)
        call_count = 0

        async def send_text_side_effect(data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                assert data == '{"type": "ping"}'
                await asyncio.sleep(0)
            else:
                raise Exception("Fake send error")

        connected_mock_websocket.send_text.side_effect = send_text_side_effect

        with patch.object(
            connection_manager, "disconnect", AsyncMock()
        ) as mock_disconnect:
            task = asyncio.create_task(connection_manager._heartbeat_loop(ws_key))
            connection_manager._heartbeat_tasks[ws_key] = task

            await asyncio.sleep(connection_manager.heartbeat_interval * 1.5)

            mock_disconnect.assert_awaited_once_with(
                ws_key, code=status.WS_1011_INTERNAL_ERROR, reason="Heartbeat failure"
            )

            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.1)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
            await connection_manager._heartbeat_tasks.pop(ws_key, None)
            connection_manager.active_local_connections.pop(ws_key, None)

    async def test_close_stops_pubsub_disconnects_clients_cancels_heartbeats(
        self,
        connection_manager: ConnectionManager,
        mock_pubsub_manager: AsyncMock,
        test_user1,
        test_user2,
        test_chat,
    ):
        """Tests the complete closure of the manager."""
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)

        connection_manager.active_local_connections = {
            ws1: (test_user1.id, test_chat.id),
            ws2: (test_user2.id, test_chat.id),
        }

        async def dummy_coro():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise

        task1 = asyncio.create_task(dummy_coro(), name="DummyTask1")
        task2 = asyncio.create_task(dummy_coro(), name="DummyTask2")
        connection_manager._heartbeat_tasks = {ws1: task1, ws2: task2}

        disconnect_calls = []

        async def mock_disconnect_side_effect(ws, code, reason):
            if ws in connection_manager.active_local_connections:
                user_id, chat_id = connection_manager.active_local_connections.pop(ws)
                if chat_id in connection_manager.local_chats:
                    connection_manager.local_chats[chat_id].discard(ws)
                    if not connection_manager.local_chats[chat_id]:
                        del connection_manager.local_chats[chat_id]
            disconnect_calls.append(ws)
            ws.close = AsyncMock()

        connection_manager.disconnect = AsyncMock(
            side_effect=mock_disconnect_side_effect
        )

        assert not task1.done()
        assert not task2.done()

        await connection_manager.close()

        mock_pubsub_manager.close.assert_awaited_once()

        assert len(disconnect_calls) == 2
        assert ws1 in disconnect_calls
        assert ws2 in disconnect_calls

        assert task1.cancelled()
        assert task2.cancelled()

        assert not connection_manager.active_local_connections
        assert not connection_manager._heartbeat_tasks

        await asyncio.sleep(0)
