import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Chat, User
from tests.fixtures.chat import FULL_CHAT_PREFIX


@pytest.mark.asyncio
class TestChatCreation:
    async def test_create_private_chat_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        partner_user: User,
        db_session_test_func: AsyncSession,
    ):
        request_data = {"target_user_id": partner_user.id}
        response = await async_client.post(
            f"{FULL_CHAT_PREFIX}/create", json=request_data, headers=auth_headers
        )
        assert response.status_code == status.HTTP_201_CREATED, (
            f"Response: {response.text}"
        )
        response_data = response.json()
        assert "chat_id" in response_data
        chat_from_db = await db_session_test_func.get(Chat, response_data["chat_id"])
        assert chat_from_db is not None

    async def test_create_private_chat_with_self_fails(
        self, async_client: AsyncClient, auth_headers: dict[str, str], test_user: User
    ):
        request_data = {"target_user_id": test_user.id}
        response = await async_client.post(
            f"{FULL_CHAT_PREFIX}/create", json=request_data, headers=auth_headers
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    async def test_create_private_chat_target_not_found_fails(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        non_existent_user_id = 999999
        request_data = {"target_user_id": non_existent_user_id}
        response = await async_client.post(
            f"{FULL_CHAT_PREFIX}/create", json=request_data, headers=auth_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_create_private_chat_unauthenticated_fails(
        self, async_client: AsyncClient, partner_user: User
    ):
        request_data = {"target_user_id": partner_user.id}
        response = await async_client.post(
            f"{FULL_CHAT_PREFIX}/create", json=request_data
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
