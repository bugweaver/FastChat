import asyncio
import logging
from unittest.mock import AsyncMock, patch

import orjson as json
import pytest
from fastapi import status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from core.models import Chat, User
from core.schemas.ws_schemas import (
    IncomingChatPayload,
    PingMessage,
    PongMessageResp,
    SearchQueryMessage,
    SearchResultsResp,
    UserSearchResultData,
)
from core.websockets.services.websocket_service import WebSocketService

pytestmark = pytest.mark.asyncio
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_redis() -> AsyncMock:
    mock = AsyncMock(spec=Redis)
    mock.get = AsyncMock(return_value=None)
    mock.smembers = AsyncMock(return_value=set())
    mock.pipeline = AsyncMock()
    return mock


class TestWebSocketService:
    @pytest.fixture
    def websocket_service(
        self,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
        mock_connection_manager: AsyncMock,
    ) -> WebSocketService:
        """Creates an instance of WebSocketService with mocks."""
        return WebSocketService(
            db=mock_db, redis_client=mock_redis, manager=mock_connection_manager
        )

    async def test_send_error_sends_correct_format(
        self, websocket_service: WebSocketService, connected_mock_websocket: AsyncMock
    ):
        """Verifies the format of the error message sent over the websocket."""
        error_message = "Test error occurred"
        error_code = status.WS_1008_POLICY_VIOLATION

        await websocket_service._send_error(
            connected_mock_websocket, error_message, error_code
        )

        connected_mock_websocket.send_text.assert_awaited_once()
        sent_data = connected_mock_websocket.send_text.call_args[0][0]
        decoded_data = json.loads(sent_data)
        assert decoded_data["type"] == "error"
        assert decoded_data["error"]["message"] == error_message
        assert decoded_data["error"]["code"] == error_code

    async def test_perform_user_search_success(
        self,
        websocket_service: WebSocketService,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
    ):
        """
        Tests successful user search, excluding self and checking online status.
        """

        query = "test"
        current_user_id = 1
        user1 = User(id=2, username="test_user", email="t@e.com", avatar="a.jpg")
        user2 = User(id=3, username="tester", email="t2@e.com", avatar=None)
        user_self = User(id=1, username="test_self", email="s@e.com")

        with (
            patch(
                "core.websockets.services.websocket_service.get_users_by_username",
                AsyncMock(return_value=[user1, user_self, user2]),
            ) as mock_get_users,
            patch(
                "core.websockets.services.websocket_service.get_online_users",
                AsyncMock(return_value={"2"}),
            ) as mock_get_online,
        ):
            results = await websocket_service._perform_user_search(
                query, current_user_id
            )

            mock_get_users.assert_awaited_once_with(websocket_service.db, query)
            mock_get_online.assert_awaited_once_with(websocket_service.redis_client)
            assert len(results) == 2
            assert isinstance(results[0], UserSearchResultData)
            assert results[0].id == user1.id
            assert results[0].is_online is True
            assert results[1].id == user2.id
            assert results[1].is_online is False

    async def test_perform_user_search_no_results(
        self, websocket_service: WebSocketService
    ):
        """Tests the case where the search does not find any users."""
        with patch(
            "core.websockets.services.websocket_service.get_users_by_username",
            AsyncMock(return_value=[]),
        ) as mock_get_users:
            results = await websocket_service._perform_user_search("no_such_user", 1)
            assert results == []
            mock_get_users.assert_awaited_once()

    async def test_perform_user_search_db_error(
        self, websocket_service: WebSocketService
    ):
        """Tests database error handling during search."""
        with patch(
            "core.websockets.services.websocket_service.get_users_by_username",
            AsyncMock(side_effect=Exception("DB Error")),
        ) as mock_get_users:
            results = await websocket_service._perform_user_search("query", 1)
            assert results == []
            mock_get_users.assert_awaited_once()

    async def test_search_message_loop_ping_pong(
        self, websocket_service: WebSocketService, connected_mock_websocket: AsyncMock
    ):
        """Tests Ping handling and Pong sending in a search loop."""
        ping_msg_obj = PingMessage()
        ping_msg = json.dumps(ping_msg_obj.model_dump()).decode("utf-8")
        pong_msg_obj = PongMessageResp()
        pong_msg = json.dumps(pong_msg_obj.model_dump()).decode("utf-8")

        connected_mock_websocket.receive_text.side_effect = [
            ping_msg,
            WebSocketDisconnect(code=1000),
        ]
        with pytest.raises(WebSocketDisconnect):
            await websocket_service._search_message_loop(connected_mock_websocket, 1)

        connected_mock_websocket.send_text.assert_awaited_with(pong_msg)

    async def test_search_message_loop_search_query(
        self, websocket_service: WebSocketService, connected_mock_websocket: AsyncMock
    ):
        """Tests the processing of a search query in the search loop."""
        query = "search_term"

        search_msg_obj = SearchQueryMessage(query=query)
        search_msg = json.dumps(search_msg_obj.model_dump()).decode("utf-8")

        result_data = UserSearchResultData(
            id=5, username="found", avatar=None, is_online=False
        )

        expected_response_obj = SearchResultsResp(results=[result_data])
        expected_response = json.dumps(expected_response_obj.model_dump()).decode(
            "utf-8"
        )

        connected_mock_websocket.receive_text.side_effect = [
            search_msg,
            WebSocketDisconnect(code=1000),
        ]

        with (
            patch.object(
                websocket_service,
                "_perform_user_search",
                AsyncMock(return_value=[result_data]),
            ) as mock_perform_search,
            patch.object(
                websocket_service, "_send_error", AsyncMock()
            ) as mock_send_error,
        ):
            with pytest.raises(WebSocketDisconnect):
                await websocket_service._search_message_loop(
                    connected_mock_websocket, 1
                )

            mock_perform_search.assert_awaited_once_with(query, 1)
            connected_mock_websocket.send_text.assert_awaited_with(expected_response)
            mock_send_error.assert_not_awaited()

    async def test_search_message_loop_unsupported_type(
        self, websocket_service: WebSocketService, connected_mock_websocket: AsyncMock
    ):
        """Tests handling of unsupported message type in the search loop."""
        invalid_msg_text = '{"type": "unknown"}'
        connected_mock_websocket.receive_text.side_effect = [
            invalid_msg_text,
            WebSocketDisconnect(code=1000),
        ]

        expected_error_msg = "Unsupported message type for search."

        with patch.object(
            websocket_service, "_send_error", AsyncMock()
        ) as mock_send_error:
            with pytest.raises(WebSocketDisconnect):
                await websocket_service._search_message_loop(
                    connected_mock_websocket, 1
                )

            mock_send_error.assert_awaited_once_with(
                connected_mock_websocket,
                expected_error_msg,
                status.WS_1003_UNSUPPORTED_DATA,
            )

    async def test_chat_message_loop_incoming_message(
        self,
        websocket_service: WebSocketService,
        connected_mock_websocket: AsyncMock,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
    ):
        """Tests the processing of an incoming chat message."""

        user_id = 1
        chat_id = 10
        payload = IncomingChatPayload(content="Hello there!", reply_to_id=None)
        incoming_msg_json = json.dumps(
            {"type": "message", "data": payload.model_dump()}
        ).decode("utf-8")

        connected_mock_websocket.receive_text.side_effect = [
            incoming_msg_json,
            WebSocketDisconnect(code=1000),
        ]

        with (
            patch(
                "core.websockets.services.websocket_service.MessageService.create_message",
                AsyncMock(),
            ) as mock_create_message,
            patch.object(
                websocket_service, "_send_error", AsyncMock()
            ) as mock_send_error,
        ):
            with pytest.raises(WebSocketDisconnect):
                await websocket_service._chat_message_loop(
                    connected_mock_websocket, chat_id, user_id
                )

            mock_create_message.assert_awaited_once_with(
                db=websocket_service.db,
                content=payload.content,
                sender_id=user_id,
                chat_id=chat_id,
                reply_to_id=payload.reply_to_id,
                redis=websocket_service.redis_client,
            )
            mock_send_error.assert_not_awaited()
            connected_mock_websocket.send_text.assert_not_awaited()

    async def test_chat_message_loop_raw_text_message(
        self,
        websocket_service: WebSocketService,
        connected_mock_websocket: AsyncMock,
        mock_db: AsyncMock,
        mock_redis: AsyncMock,
    ):
        """Tests the processing of a simple text message."""

        user_id = 2
        chat_id = 11
        raw_text = "Just raw text"
        connected_mock_websocket.receive_text.side_effect = [
            raw_text,
            WebSocketDisconnect(code=1000),
        ]
        with (
            patch(
                "core.websockets.services.websocket_service.MessageService.create_message",
                AsyncMock(),
            ) as mock_create_message,
            patch.object(
                websocket_service, "_send_error", AsyncMock()
            ) as mock_send_error,
        ):
            with pytest.raises(WebSocketDisconnect):
                await websocket_service._chat_message_loop(
                    connected_mock_websocket, chat_id, user_id
                )

            mock_create_message.assert_awaited_once_with(
                db=websocket_service.db,
                content=raw_text,
                sender_id=user_id,
                chat_id=chat_id,
                reply_to_id=None,
                redis=websocket_service.redis_client,
            )
            mock_send_error.assert_not_awaited()
            connected_mock_websocket.send_text.assert_not_awaited()

    async def test_chat_message_loop_timeout(
        self,
        websocket_service: WebSocketService,
        connected_mock_websocket: AsyncMock,
        mock_connection_manager: AsyncMock,
    ):
        """Tests connection disconnection due to inactivity timeout."""

        connected_mock_websocket.receive_text.side_effect = asyncio.TimeoutError

        await websocket_service._chat_message_loop(connected_mock_websocket, 10, 1)

        mock_connection_manager.disconnect.assert_awaited_once_with(
            connected_mock_websocket,
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Inactivity timeout",
        )

    async def test_keep_alive_loop_ping_pong(
        self, websocket_service: WebSocketService, connected_mock_websocket: AsyncMock
    ):
        """Tests Ping/Pong handling in a keep-alive loop."""

        ping_msg_obj = PingMessage()
        ping_msg = json.dumps(ping_msg_obj.model_dump()).decode("utf-8")
        pong_msg_obj = PongMessageResp()
        pong_msg = json.dumps(pong_msg_obj.model_dump()).decode("utf-8")
        connected_mock_websocket.receive_text.side_effect = [
            ping_msg,
            WebSocketDisconnect(code=1000),
        ]
        with pytest.raises(WebSocketDisconnect):
            await websocket_service._keep_alive_loop(
                connected_mock_websocket, 1, "/status"
            )

        connected_mock_websocket.send_text.assert_awaited_with(pong_msg)

    async def test_keep_alive_loop_ignores_other_messages(
        self, websocket_service: WebSocketService, connected_mock_websocket: AsyncMock
    ):
        """
        Tests that keep-alive ignores unsupported messages and does not crash.
        """
        other_msg_text = '{"type": "some_other_message"}'
        connected_mock_websocket.receive_text.side_effect = [
            other_msg_text,
            WebSocketDisconnect(code=1000),
        ]

        with patch.object(
            websocket_service, "_safe_close_ws", AsyncMock()
        ) as mock_safe_close:
            with pytest.raises(WebSocketDisconnect):
                await websocket_service._keep_alive_loop(
                    connected_mock_websocket, 1, "/status"
                )

            mock_safe_close.assert_not_awaited()
            connected_mock_websocket.send_text.assert_not_awaited()

    @patch(
        "core.websockets.services.websocket_service.WebSocketService._search_message_loop",
        new_callable=AsyncMock,
    )
    async def test_handle_search_endpoint_calls_loop(
        self,
        mock_search_loop: AsyncMock,
        websocket_service: WebSocketService,
        connected_mock_websocket: AsyncMock,
    ):
        """Checks that handle_search_endpoint calls _search_message_loop."""
        user_id = 1
        await websocket_service.handle_search_endpoint(
            connected_mock_websocket, user_id
        )
        connected_mock_websocket.accept.assert_awaited_once()
        mock_search_loop.assert_awaited_once_with(connected_mock_websocket, user_id)

    @patch(
        "core.websockets.services.websocket_service.check_user_in_chat",
        new_callable=AsyncMock,
    )
    @patch(
        "core.websockets.services.websocket_service.get_chat_by_id",
        new_callable=AsyncMock,
    )
    async def test_handle_chat_endpoint_calls_loop(
        self,
        mock_get_chat_by_id: AsyncMock,
        mock_check_user_in_chat: AsyncMock,
        websocket_service: WebSocketService,
        connected_mock_websocket: AsyncMock,
        mock_connection_manager: AsyncMock,
    ):
        """Checks that handle_chat_endpoint calls connect and _chat_message_loop."""
        user_id = 1
        chat_id = 10

        mock_check_user_in_chat.return_value = True
        mock_get_chat_by_id.return_value = AsyncMock(spec=Chat, id=chat_id)
        websocket_service.connection_manager = mock_connection_manager

        with patch.object(
            websocket_service, "_chat_message_loop", new_callable=AsyncMock
        ) as mock_chat_loop:
            await websocket_service.handle_chat_endpoint(
                connected_mock_websocket, chat_id, user_id
            )

            mock_get_chat_by_id.assert_awaited_once_with(websocket_service.db, chat_id)
            mock_check_user_in_chat.assert_awaited_once_with(
                websocket_service.db, user_id, chat_id
            )
            mock_connection_manager.connect.assert_awaited_once_with(
                connected_mock_websocket, str(chat_id), str(user_id)
            )
            mock_chat_loop.assert_awaited_once_with(
                connected_mock_websocket, chat_id, user_id
            )

    @patch(
        "core.websockets.services.websocket_service.get_online_users",
        AsyncMock(return_value={"1", "2"}),
    )
    @patch(
        "core.websockets.services.websocket_service.WebSocketService._keep_alive_loop",
        new_callable=AsyncMock,
    )
    async def test_handle_status_endpoint_sends_initial_and_calls_loop(
        self,
        mock_keep_alive_loop: AsyncMock,
        websocket_service: WebSocketService,
        connected_mock_websocket: AsyncMock,
    ):
        """Проверяет отправку начального статуса и вызов keep-alive цикла."""
        user_id = 1
        await websocket_service.handle_status_endpoint(
            connected_mock_websocket, user_id
        )

        connected_mock_websocket.accept.assert_awaited_once()
        connected_mock_websocket.send_text.assert_awaited_once()

        sent_data = connected_mock_websocket.send_text.call_args[0][0]
        decoded_data = json.loads(sent_data)
        assert decoded_data["type"] == "initial_status"
        assert set(decoded_data["data"]["online_users"]) == {1, 2}

        mock_keep_alive_loop.assert_awaited_once_with(
            connected_mock_websocket, user_id, "/status"
        )
