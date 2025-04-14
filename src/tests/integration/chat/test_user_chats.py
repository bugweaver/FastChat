import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.services.token_service import TokenService
from core.models import Chat, Message, User
from tests.factories.user_factory import UserFactory
from tests.fixtures.chat import FULL_CHAT_PREFIX


@pytest.mark.asyncio
class TestUserChats:
    async def test_get_my_chats_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        existing_chat: Chat,
        message_id_in_chat: int,
        test_user: User,
        db_session_test_func: AsyncSession,
    ):
        partner_user = getattr(existing_chat, "partner_user_in_test", None)
        assert partner_user is not None

        last_message_orm = await db_session_test_func.get(Message, message_id_in_chat)
        assert last_message_orm is not None
        await db_session_test_func.refresh(last_message_orm, attribute_names=["sender"])
        assert last_message_orm.sender is not None

        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/my-chats", headers=auth_headers
        )

        assert response.status_code == status.HTTP_200_OK, f"Response: {response.text}"
        data = response.json()
        assert "chats" in data
        assert isinstance(data["chats"], list)
        assert len(data["chats"]) >= 1

        found_chat = next(
            (c for c in data["chats"] if c["id"] == existing_chat.id), None
        )
        assert found_chat is not None
        assert found_chat["name"] == partner_user.username
        assert found_chat["last_message"] is not None
        assert found_chat["last_message"]["content"] == last_message_orm.content
        assert found_chat["last_message"]["sender"] is not None
        assert found_chat["last_message"]["sender"]["id"] == last_message_orm.sender.id

    async def test_get_my_chats_empty(
        self,
        async_client: AsyncClient,
        db_session_test_func: AsyncSession,
        token_service: TokenService,
    ):
        new_user = await UserFactory.create_async(
            session=db_session_test_func,
            username="chatless_user_v2",
            email="chatless_v2@t.com",
        )
        new_user_token = token_service.create_access_token(new_user)
        headers = {"Authorization": f"Bearer {new_user_token}"}

        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/my-chats", headers=headers
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "chats" in data
        assert isinstance(data["chats"], list)
        assert len(data["chats"]) == 0
