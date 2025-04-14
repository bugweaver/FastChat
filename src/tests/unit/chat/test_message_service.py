from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.chat.services.message_service import (
    DEFAULT_CHAT_SETTINGS,
    MessageService,
)
from core.redis.keys import get_chat_message_channel, get_message_deleted_channel
from core.schemas.chat_schemas import MessagesListResponse
from tests.factories.chat_factory import ChatFactory, MessageFactory
from tests.factories.user_factory import UserFactory

pytestmark = pytest.mark.asyncio


class TestMessageService:
    @pytest.fixture
    async def user(self, db_session_test_func: AsyncSession):
        """Creates a test user."""
        return await UserFactory.create_async(session=db_session_test_func)

    @pytest.fixture
    async def other_user(self, db_session_test_func: AsyncSession):
        """Creates another test user."""
        return await UserFactory.create_async(session=db_session_test_func)

    @pytest.fixture
    async def chat(self, db_session_test_func: AsyncSession):
        """Создает тестовый чат"""
        return await ChatFactory.create_async(session=db_session_test_func)

    @pytest.fixture
    async def message(self, db_session_test_func: AsyncSession, user, chat):
        """Creates test message"""
        msg = await MessageFactory.create_async(
            session=db_session_test_func,
            content="Test message",
            sender_id=user.id,
            chat_id=chat.id,
            created_at=datetime.now(timezone.utc),
            sender=user,
        )
        msg.sender = user
        return msg

    @pytest.fixture
    def mock_dependencies(self):
        """Sets up mocks for MessageService dependencies"""
        with (
            patch(
                "repositories.chat_repo.get_chat_by_id", new_callable=AsyncMock
            ) as mock_get_chat,
            patch(
                "core.chat.services.message_service.check_user_in_chat",
                new_callable=AsyncMock,
            ) as mock_check_user,
            patch(
                "repositories.chat_repo.get_message_by_id", new_callable=AsyncMock
            ) as mock_get_msg,
            patch(
                "repositories.chat_repo.create_message", new_callable=AsyncMock
            ) as mock_create_msg_repo,
            patch(
                "repositories.chat_repo.delete_message", new_callable=AsyncMock
            ) as mock_delete_msg_repo,
            patch(
                "repositories.chat_repo.get_recent_chat_messages",
                new_callable=AsyncMock,
            ) as mock_get_recent_db,
            patch(
                "core.chat.services.message_service.add_message_to_chat_history",
                new_callable=AsyncMock,
            ) as mock_add_redis,
            patch(
                "core.chat.services.message_service.get_chat_history",
                new_callable=AsyncMock,
            ) as mock_get_redis,
            patch(
                "core.chat.services.message_service.delete_message_from_redis",
                new_callable=AsyncMock,
            ) as mock_delete_redis,
            patch(
                "core.chat.services.message_service.publish_message",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch(
                "sqlalchemy.ext.asyncio.AsyncSession.refresh", new_callable=AsyncMock
            ) as mock_db_refresh,
        ):

            async def refresh_side_effect(instance, attribute_names=None):
                return instance

            mock_db_refresh.side_effect = refresh_side_effect

            yield {
                "get_chat": mock_get_chat,
                "check_user": mock_check_user,
                "get_message": mock_get_msg,
                "create_message_repo": mock_create_msg_repo,
                "delete_message_repo": mock_delete_msg_repo,
                "get_recent_db": mock_get_recent_db,
                "add_redis": mock_add_redis,
                "get_redis": mock_get_redis,
                "delete_redis": mock_delete_redis,
                "publish": mock_publish,
                "db_refresh": mock_db_refresh,
            }

    async def test_create_message_success(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Test of successful message creation"""
        content = "Привет! Как дела?"
        ts = datetime.now(timezone.utc)

        created_msg_orm = MessageFactory.build(
            id=123,
            content=content,
            sender_id=user.id,
            chat_id=chat.id,
            created_at=ts,
            sender=user,
        )
        db_session_test_func.add(created_msg_orm)
        if not hasattr(created_msg_orm, "sender") or created_msg_orm.sender is None:
            created_msg_orm.sender = user

        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["create_message_repo"].return_value = created_msg_orm
        mock_dependencies["add_redis"].return_value = None
        mock_dependencies["publish"].return_value = None

        result = await MessageService.create_message(
            db_session_test_func, content, user.id, chat.id, redis=redis_client
        )

        assert isinstance(result, dict)
        assert result["id"] == created_msg_orm.id
        assert result["content"] == content
        assert result["chat_id"] == chat.id
        assert result["sender"]["id"] == user.id

        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["create_message_repo"].assert_awaited_once()
        mock_dependencies["db_refresh"].assert_awaited_once_with(
            created_msg_orm, attribute_names=["sender"]
        )
        mock_dependencies["add_redis"].assert_awaited_once()
        mock_dependencies["publish"].assert_awaited_once()

        publish_args, _ = mock_dependencies["publish"].call_args
        assert publish_args[0] == redis_client
        assert publish_args[1] == get_chat_message_channel(chat.id)
        published_data = publish_args[2]
        assert published_data["type"] == "new_message"

        assert published_data["data"]["id"] == created_msg_orm.id
        assert published_data["data"]["content"] == content

    async def test_create_message_chat_not_found(
        self, db_session_test_func: AsyncSession, redis_client, user, mock_dependencies
    ):
        """Test creating a message with a non-existent chat"""
        chat_id = 9999
        mock_dependencies["get_chat"].return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.create_message(
                db_session_test_func, "Test", user.id, chat_id, redis=redis_client
            )

        assert exc_info.value.status_code == 404
        assert "Chat not found" in exc_info.value.detail
        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat_id
        )
        mock_dependencies["check_user"].assert_not_awaited()
        mock_dependencies["create_message_repo"].assert_not_awaited()

    async def test_create_message_not_participant(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Test of creating a message by a user not participating in the chat"""
        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.create_message(
                db_session_test_func, "Test", user.id, chat.id, redis=redis_client
            )

        assert exc_info.value.status_code == 403
        assert "Sender is not a participant of this chat" in exc_info.value.detail
        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["create_message_repo"].assert_not_awaited()

    async def test_create_message_reply_not_found(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Test creating a reply to a non-existent message"""
        reply_id = 9999
        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["get_message"].return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.create_message(
                db_session_test_func,
                "Ответ",
                user.id,
                chat.id,
                reply_to_id=reply_id,
                redis=redis_client,
            )

        assert exc_info.value.status_code == 404
        assert "Message to reply to not found" in exc_info.value.detail
        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["get_message"].assert_awaited_once_with(
            db_session_test_func, reply_id
        )
        mock_dependencies["create_message_repo"].assert_not_awaited()

    async def test_create_message_reply_wrong_chat(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Test creating a reply to a message from another chat"""
        other_chat = await ChatFactory.create_async(session=db_session_test_func)
        reply_msg = await MessageFactory.create_async(
            session=db_session_test_func, chat_id=other_chat.id, sender_id=user.id
        )

        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["get_message"].return_value = reply_msg

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.create_message(
                db_session_test_func,
                "Ответ",
                user.id,
                chat.id,
                reply_to_id=reply_msg.id,
                redis=redis_client,
            )

        assert exc_info.value.status_code == 400
        assert (
            "Cannot reply to a message from a different chat" in exc_info.value.detail
        )
        mock_dependencies["get_message"].assert_awaited_once_with(
            db_session_test_func, reply_msg.id
        )
        mock_dependencies["create_message_repo"].assert_not_awaited()

    async def test_create_message_repo_fails(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Test of error handling when saving a message to the database"""
        db_error = Exception("DB write error")
        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["create_message_repo"].side_effect = db_error

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.create_message(
                db_session_test_func, "Test", user.id, chat.id, redis=redis_client
            )

        assert exc_info.value.status_code == 500
        assert "An error occurred while creating the message." in exc_info.value.detail
        mock_dependencies["create_message_repo"].assert_awaited_once()
        mock_dependencies["add_redis"].assert_not_awaited()
        mock_dependencies["publish"].assert_not_awaited()

    async def test_delete_message_success(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        message,
        mock_dependencies,
    ):
        """Test of successful message deletion"""
        mock_dependencies["get_message"].return_value = message
        mock_dependencies["delete_message_repo"].return_value = True
        mock_dependencies["delete_redis"].return_value = True
        mock_dependencies["publish"].return_value = None

        await MessageService.delete_message(
            db=db_session_test_func,
            message_id=message.id,
            current_user_id=user.id,
            redis=redis_client,
        )

        mock_dependencies["get_message"].assert_awaited_once_with(
            db_session_test_func, message.id
        )
        mock_dependencies["delete_message_repo"].assert_awaited_once_with(
            db_session_test_func, message.id, user.id
        )
        mock_dependencies["delete_redis"].assert_awaited_once_with(
            redis_client, chat.id, message.id, DEFAULT_CHAT_SETTINGS
        )
        mock_dependencies["publish"].assert_awaited_once()

        publish_args, _ = mock_dependencies["publish"].call_args
        assert publish_args[0] == redis_client
        assert publish_args[1] == get_message_deleted_channel(chat.id)
        published_data = publish_args[2]
        assert published_data["type"] == "message_deleted"
        assert published_data["message_id"] == message.id
        assert published_data["chat_id"] == chat.id

    async def test_delete_message_not_found(
        self, db_session_test_func: AsyncSession, redis_client, user, mock_dependencies
    ):
        """Test of deleting a non-existent message"""
        message_id = 999
        mock_dependencies["get_message"].return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.delete_message(
                db_session_test_func, message_id, user.id, redis_client
            )

        assert exc_info.value.status_code == 404
        assert "Message not found" in exc_info.value.detail
        mock_dependencies["get_message"].assert_awaited_once_with(
            db_session_test_func, message_id
        )
        mock_dependencies["delete_message_repo"].assert_not_awaited()
        mock_dependencies["delete_redis"].assert_not_awaited()
        mock_dependencies["publish"].assert_not_awaited()

    async def test_delete_message_forbidden(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        other_user,
        chat,
        message,
        mock_dependencies,
    ):
        """Test of deleting someone else's message (not by the owner)"""
        mock_dependencies["get_message"].return_value = message

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.delete_message(
                db_session_test_func, message.id, other_user.id, redis_client
            )

        assert exc_info.value.status_code == 403
        assert "User cannot delete this message" in exc_info.value.detail
        mock_dependencies["get_message"].assert_awaited_once_with(
            db_session_test_func, message.id
        )
        mock_dependencies["delete_message_repo"].assert_not_awaited()
        mock_dependencies["delete_redis"].assert_not_awaited()
        mock_dependencies["publish"].assert_not_awaited()

    async def test_delete_message_repo_fails(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        message,
        mock_dependencies,
    ):
        """Test of error handling when deleting a message from the database"""
        db_error = Exception("DB delete error")
        mock_dependencies["get_message"].return_value = message
        mock_dependencies["delete_message_repo"].side_effect = db_error

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.delete_message(
                db_session_test_func, message.id, user.id, redis_client
            )

        assert exc_info.value.status_code == 500
        assert "An error occurred while deleting the message." in exc_info.value.detail
        mock_dependencies["get_message"].assert_awaited_once_with(
            db_session_test_func, message.id
        )
        mock_dependencies["delete_message_repo"].assert_awaited_once_with(
            db_session_test_func, message.id, user.id
        )
        mock_dependencies["delete_redis"].assert_not_awaited()
        mock_dependencies["publish"].assert_not_awaited()

    async def test_get_chat_messages_from_cache(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Тест получения сообщений из кэша Redis"""
        ts = datetime.now(timezone.utc)
        cached_message_dict = {
            "id": 101,
            "chat_id": chat.id,
            "content": "Кэшированное сообщение",
            "created_at": ts.isoformat(),
            "sender": {"id": user.id, "username": user.username, "avatar": user.avatar},
            "reply_to_id": None,
        }

        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["get_redis"].return_value = [cached_message_dict]

        result = await MessageService.get_chat_messages(
            db_session_test_func, chat.id, user.id, redis_client
        )

        assert isinstance(result, MessagesListResponse)
        assert len(result.messages) == 1
        assert result.messages[0].id == 101
        assert result.messages[0].content == "Кэшированное сообщение"
        assert result.messages[0].created_at == ts
        assert result.messages[0].sender.id == user.id

        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["get_redis"].assert_awaited_once()
        mock_dependencies["get_recent_db"].assert_not_awaited()
        mock_dependencies["add_redis"].assert_not_awaited()

    async def test_get_chat_messages_from_db_populate_cache(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        message,
        mock_dependencies,
    ):
        """Тест получения сообщений из БД с последующим кэшированием"""
        if not hasattr(message, "sender") or message.sender is None:
            message.sender = user

        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["get_redis"].return_value = []
        mock_dependencies["get_recent_db"].return_value = [message]
        mock_dependencies["add_redis"].return_value = None

        result = await MessageService.get_chat_messages(
            db_session_test_func, chat.id, user.id, redis_client
        )

        assert isinstance(result, MessagesListResponse)
        assert len(result.messages) == 1
        assert result.messages[0].id == message.id
        assert result.messages[0].content == message.content
        assert result.messages[0].sender.id == user.id

        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["get_redis"].assert_awaited_once()
        mock_dependencies["get_recent_db"].assert_awaited_once()
        mock_dependencies["add_redis"].assert_awaited_once()
        add_args, _ = mock_dependencies["add_redis"].call_args
        assert add_args[0] == redis_client
        assert add_args[1] == chat.id
        message_to_cache = add_args[2]
        assert isinstance(message_to_cache, dict)
        assert message_to_cache["id"] == message.id

    async def test_get_chat_messages_invalid_cache_data(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        message,
        mock_dependencies,
    ):
        """Test of processing invalid data from cache (expected fallback to DB)"""
        if not hasattr(message, "sender") or message.sender is None:
            message.sender = user

        invalid_cache_data = {"bad": "data", "no_id": True}

        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = True
        mock_dependencies["get_redis"].return_value = [invalid_cache_data]
        mock_dependencies["get_recent_db"].return_value = [message]
        mock_dependencies["add_redis"].return_value = None

        with patch("core.chat.services.message_service.log", MagicMock()) as mock_log:
            result = await MessageService.get_chat_messages(
                db_session_test_func, chat.id, user.id, redis_client
            )

        assert isinstance(result, MessagesListResponse)
        assert len(result.messages) == 1
        assert result.messages[0].id == message.id

        mock_log.warning.assert_called_once()
        assert (
            mock_log.warning.call_args[0][0]
            == "Invalid message data in Redis cache for chat %s, msg_id=%s: %s"
        )
        assert isinstance(mock_log.warning.call_args[0][3], pydantic.ValidationError)

        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["get_redis"].assert_awaited_once()
        mock_dependencies["get_recent_db"].assert_awaited_once()
        mock_dependencies["add_redis"].assert_awaited_once()

    async def test_get_chat_messages_not_participant(
        self,
        db_session_test_func: AsyncSession,
        redis_client,
        user,
        chat,
        mock_dependencies,
    ):
        """Test for receiving messages by a non-chat participant"""
        mock_dependencies["get_chat"].return_value = chat
        mock_dependencies["check_user"].return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.get_chat_messages(
                db_session_test_func, chat.id, user.id, redis_client
            )

        assert exc_info.value.status_code == 403
        assert (
            "User does not have access to this chat's messages" in exc_info.value.detail
        )
        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat.id
        )
        mock_dependencies["check_user"].assert_awaited_once_with(
            db_session_test_func, user.id, chat.id
        )
        mock_dependencies["get_redis"].assert_not_awaited()
        mock_dependencies["get_recent_db"].assert_not_awaited()

    async def test_get_chat_messages_chat_not_found(
        self, db_session_test_func: AsyncSession, redis_client, user, mock_dependencies
    ):
        """Test for receiving messages by a non-chat participant"""
        chat_id = 999
        mock_dependencies["get_chat"].return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await MessageService.get_chat_messages(
                db_session_test_func, chat_id, user.id, redis_client
            )

        assert exc_info.value.status_code == 404
        assert "Chat not found" in exc_info.value.detail
        mock_dependencies["get_chat"].assert_awaited_once_with(
            db_session_test_func, chat_id
        )
        mock_dependencies["check_user"].assert_not_awaited()
        mock_dependencies["get_redis"].assert_not_awaited()
        mock_dependencies["get_recent_db"].assert_not_awaited()
