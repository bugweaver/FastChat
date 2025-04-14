import pytest
from fastapi import status
from httpx import AsyncClient

from core.models import Chat
from tests.fixtures.chat import FULL_CHAT_PREFIX


@pytest.mark.asyncio
class TestChatInfo:
    async def test_get_chat_info_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        existing_chat: Chat,
    ):
        partner_user = getattr(existing_chat, "partner_user_in_test", None)
        assert partner_user is not None

        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/{existing_chat.id}", headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK, f"Response: {response.text}"
        data = response.json()
        assert data["id"] == existing_chat.id
        assert data["chat_partner"]["id"] == partner_user.id

    async def test_get_chat_info_not_participant_fails(
        self, async_client: AsyncClient, auth_headers: dict[str, str], other_chat: Chat
    ):
        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/{other_chat.id}", headers=auth_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_get_chat_info_not_found_fails(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/999999", headers=auth_headers
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
