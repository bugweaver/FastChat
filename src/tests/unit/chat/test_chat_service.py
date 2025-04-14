from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.chat.services.chat_service import ChatService
from core.schemas.chat_schemas import (
    ChatCreatedResponse,
    ChatInfoResponse,
    UserChatsResponse,
)
from tests.factories.chat_factory import ChatFactory, MessageFactory
from tests.factories.user_factory import UserFactory

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_db() -> AsyncMock:
    """Provides a mock AsyncSession with relevant methods mocked."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.get = AsyncMock()
    session.execute = AsyncMock()
    mock_execute_result = AsyncMock()
    mock_execute_result.scalar = MagicMock(return_value=True)
    session.execute.return_value = mock_execute_result
    return session


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Provides a mock Redis client with awaitable methods."""
    mock = AsyncMock(spec=Redis)
    mock.smembers = AsyncMock(return_value=set())
    mock.sismember = AsyncMock(return_value=False)
    return mock


class TestChatService:
    async def test_create_private_chat_success(self, mock_db: AsyncMock):
        current_user_id = 1
        target_user_id = 2

        mock_target = await UserFactory.build_async(id=target_user_id, username="t")
        mock_chat = await ChatFactory.build_async(id=10)

        with (
            patch(
                "repositories.user_repo.get_user_by_id",
                AsyncMock(return_value=mock_target),
            ) as mock_get_u,
            patch(
                "repositories.chat_repo.get_or_create_private_chat",
                AsyncMock(return_value=mock_chat),
            ) as mock_get_c,
        ):
            res = await ChatService.create_private_chat(
                mock_db, current_user_id, target_user_id
            )
            assert isinstance(res, ChatCreatedResponse)
            assert res.chat_id == 10
            mock_get_u.assert_awaited_once_with(mock_db, target_user_id)
            mock_get_c.assert_awaited_once_with(
                mock_db, current_user_id, target_user_id
            )
            mock_db.commit.assert_awaited_once()
            mock_db.rollback.assert_not_awaited()

    async def test_create_private_chat_with_self(self, mock_db: AsyncMock):
        with pytest.raises(HTTPException) as e:
            await ChatService.create_private_chat(mock_db, 1, 1)
        assert e.value.status_code == 400
        mock_db.commit.assert_not_awaited()

    async def test_create_private_chat_target_not_found(self, mock_db: AsyncMock):
        with patch(
            "repositories.user_repo.get_user_by_id", AsyncMock(return_value=None)
        ) as mock_get_u:
            with pytest.raises(HTTPException) as e:
                await ChatService.create_private_chat(mock_db, 1, 9)
            assert e.value.status_code == 404
            mock_get_u.assert_awaited_once_with(mock_db, 9)
            mock_db.commit.assert_not_awaited()

    async def test_create_private_chat_repo_error(self, mock_db: AsyncMock):
        mock_target = await UserFactory.build_async(id=2)
        err = Exception("DB err")
        with (
            patch(
                "repositories.user_repo.get_user_by_id",
                AsyncMock(return_value=mock_target),
            ),
            patch(
                "repositories.chat_repo.get_or_create_private_chat",
                AsyncMock(side_effect=err),
            ),
        ):
            with pytest.raises(HTTPException) as e:
                await ChatService.create_private_chat(mock_db, 1, 2)
            assert e.value.status_code == 500
            mock_db.commit.assert_not_awaited()
            mock_db.rollback.assert_awaited_once()

    async def test_get_chat_info_success_private_offline(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        chat_id = 10
        user_id = 1
        partner_id = 2

        mock_chat = await ChatFactory.build_async(
            id=chat_id, is_group=False, created_at=datetime.now()
        )
        mock_partner = await UserFactory.build_async(
            id=partner_id, username="p", avatar="a.png"
        )

        with (
            patch(
                "repositories.chat_repo.get_chat_by_id",
                AsyncMock(return_value=mock_chat),
            ) as mock_get_chat,
            patch(
                "core.chat.services.chat_service.check_user_in_chat",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_check,
            patch(
                "repositories.chat_repo.get_chat_partner",
                AsyncMock(return_value=mock_partner),
            ) as mock_get_p,
            patch(
                "core.chat.services.chat_service.is_user_online",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_is_online,
        ):
            result = await ChatService.get_chat_info(
                mock_db, chat_id, user_id, mock_redis
            )

            assert isinstance(result, ChatInfoResponse)
            assert result.chat_partner is not None
            assert result.chat_partner.is_online is False

            mock_get_chat.assert_awaited_once_with(mock_db, chat_id)
            mock_check.assert_awaited_once_with(mock_db, user_id, chat_id)
            mock_get_p.assert_awaited_once_with(mock_db, chat_id, user_id)
            mock_is_online.assert_awaited_once_with(mock_redis, partner_id)

    async def test_get_chat_info_success_private_online(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        chat_id = 11
        user_id = 1
        partner_id = 3

        mock_chat = await ChatFactory.build_async(
            id=chat_id, is_group=False, created_at=datetime.now()
        )
        mock_partner = await UserFactory.build_async(id=partner_id, username="p_on")

        with (
            patch(
                "repositories.chat_repo.get_chat_by_id",
                AsyncMock(return_value=mock_chat),
            ),
            patch(
                "core.chat.services.chat_service.check_user_in_chat",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_check,
            patch(
                "repositories.chat_repo.get_chat_partner",
                AsyncMock(return_value=mock_partner),
            ) as mock_get_p,
            patch(
                "core.chat.services.chat_service.is_user_online",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_is_online,
        ):
            result = await ChatService.get_chat_info(
                mock_db, chat_id, user_id, mock_redis
            )

            assert isinstance(result, ChatInfoResponse)
            assert result.chat_partner is not None
            assert result.chat_partner.is_online is True

            mock_check.assert_awaited_once_with(mock_db, user_id, chat_id)
            mock_get_p.assert_awaited_once_with(mock_db, chat_id, user_id)
            mock_is_online.assert_awaited_once_with(mock_redis, partner_id)

    async def test_get_chat_info_success_group(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        chat_id = 20
        user_id = 1

        mock_chat = await ChatFactory.build_async(
            id=chat_id, name="G", is_group=True, created_at=datetime.now()
        )

        with (
            patch(
                "repositories.chat_repo.get_chat_by_id",
                AsyncMock(return_value=mock_chat),
            ) as mock_get_chat,
            patch(
                "core.chat.services.chat_service.check_user_in_chat",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_check,
            patch(
                "repositories.chat_repo.get_chat_partner", new_callable=AsyncMock
            ) as mock_get_p,
            patch(
                "core.chat.services.chat_service.is_user_online", new_callable=AsyncMock
            ) as mock_is_online,
        ):
            result = await ChatService.get_chat_info(
                mock_db, chat_id, user_id, mock_redis
            )

            assert isinstance(result, ChatInfoResponse)
            assert result.chat_partner is None

            mock_get_chat.assert_awaited_once_with(mock_db, chat_id)
            mock_check.assert_awaited_once_with(mock_db, user_id, chat_id)
            mock_get_p.assert_not_awaited()
            mock_is_online.assert_not_awaited()

    async def test_get_chat_info_not_found(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        with patch(
            "repositories.chat_repo.get_chat_by_id", AsyncMock(return_value=None)
        ) as mock_get_chat:
            with pytest.raises(HTTPException) as e:
                await ChatService.get_chat_info(mock_db, 9, 1, mock_redis)
            assert e.value.status_code == 404
            mock_get_chat.assert_awaited_once_with(mock_db, 9)

    async def test_get_chat_info_not_participant(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        mock_chat = await ChatFactory.build_async(
            id=10, is_group=False, created_at=datetime.now()
        )

        with (
            patch(
                "repositories.chat_repo.get_chat_by_id",
                AsyncMock(return_value=mock_chat),
            ),
            patch(
                "core.chat.services.chat_service.check_user_in_chat",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_check,
            patch(
                "repositories.chat_repo.get_chat_partner", new_callable=AsyncMock
            ) as mock_get_p,
        ):
            with pytest.raises(HTTPException) as e:
                await ChatService.get_chat_info(mock_db, 10, 1, mock_redis)

            assert e.value.status_code == 403
            assert "Access forbidden: User not in chat" in e.value.detail
            mock_check.assert_awaited_once_with(mock_db, 1, 10)
            mock_get_p.assert_not_awaited()

    async def test_get_user_chats_success(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        user_id = 1
        now = datetime.now()

        mock_s = await UserFactory.build_async(id=3, username="s")
        mock_lm = await MessageFactory.build_async(
            id=101, content="L", sender_id=3, chat_id=1, created_at=now, sender=mock_s
        )
        mock_c1 = await ChatFactory.build_async(
            id=1, name="G1", is_group=True, created_at=now
        )
        mock_c1.last_message_at = now

        mock_p2 = await UserFactory.build_async(id=2, username="p_off")
        mock_c2 = await ChatFactory.build_async(id=2, is_group=False, created_at=now)

        mock_p3 = await UserFactory.build_async(id=4, username="p_on")
        mock_c3 = await ChatFactory.build_async(id=3, is_group=False, created_at=now)

        mock_repo_data = [
            (mock_c1, mock_lm, None),
            (mock_c2, None, mock_p2),
            (mock_c3, None, mock_p3),
        ]
        mock_online_set = {str(mock_p3.id)}

        with (
            patch(
                "repositories.chat_repo.get_user_chats_data",
                AsyncMock(return_value=mock_repo_data),
            ) as mock_get_data,
            patch(
                "core.chat.services.chat_service.get_online_users",
                new_callable=AsyncMock,
                return_value=mock_online_set,
            ) as mock_get_online,
        ):
            result = await ChatService.get_user_chats(mock_db, user_id, mock_redis)

            assert isinstance(result, UserChatsResponse)
            assert len(result.chats) == 3
            mock_get_data.assert_awaited_once_with(mock_db, user_id)
            mock_get_online.assert_awaited_once_with(mock_redis)

            if len(result.chats) == 3:
                assert result.chats[1].is_online is False
                assert result.chats[2].is_online is True

    async def test_get_user_chats_empty(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        user_id = 1
        with (
            patch(
                "repositories.chat_repo.get_user_chats_data", AsyncMock(return_value=[])
            ) as mock_get_data,
            patch(
                "core.chat.services.chat_service.get_online_users",
                new_callable=AsyncMock,
                return_value=set(),
            ) as mock_get_online,
        ):
            result = await ChatService.get_user_chats(mock_db, user_id, mock_redis)
            assert isinstance(result, UserChatsResponse)
            assert len(result.chats) == 0
            mock_get_data.assert_awaited_once_with(mock_db, user_id)
            mock_get_online.assert_awaited_once_with(mock_redis)

    async def test_get_user_chats_repo_error(
        self, mock_db: AsyncMock, mock_redis: AsyncMock
    ):
        user_id = 1
        err = Exception("DB fail")
        with (
            patch(
                "repositories.chat_repo.get_user_chats_data", AsyncMock(side_effect=err)
            ) as mock_get_data,
            patch(
                "core.chat.services.chat_service.get_online_users",
                new_callable=AsyncMock,
            ) as mock_get_online,
        ):
            res = await ChatService.get_user_chats(mock_db, user_id, mock_redis)
            assert isinstance(res, UserChatsResponse)
            assert len(res.chats) == 0
            mock_get_data.assert_awaited_once_with(mock_db, user_id)
            mock_get_online.assert_not_awaited()
