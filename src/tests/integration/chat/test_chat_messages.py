import logging
from unittest.mock import AsyncMock, patch

import pydantic
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Chat, User
from core.schemas.chat_schemas import MessageSchema
from tests.factories.chat_factory import MessageFactory
from tests.fixtures.chat import (
    FULL_CHAT_PREFIX,
    perform_delete_and_assert_not_published,
)

log = logging.getLogger(__name__)


@pytest.mark.asyncio
class TestChatMessages:
    async def test_get_chat_messages_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        existing_chat: Chat,
        message_id_in_chat: int,
        test_user: User,
    ):
        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/{existing_chat.id}/messages", headers=auth_headers
        )
        assert response.status_code == status.HTTP_200_OK, f"Response: {response.text}"
        data = response.json()
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert len(data["messages"]) >= 1

        found_message_dict = next(
            (m for m in data["messages"] if m["id"] == message_id_in_chat), None
        )
        assert found_message_dict is not None

        try:
            validated_msg = MessageSchema.model_validate(found_message_dict)
            assert validated_msg.sender is not None
            assert validated_msg.sender.id == test_user.id
        except pydantic.ValidationError as e:
            pytest.fail(f"Response message validation failed: {e}")

    async def test_get_chat_messages_not_participant_fails(
        self, async_client: AsyncClient, auth_headers: dict[str, str], other_chat: Chat
    ):
        response = await async_client.get(
            f"{FULL_CHAT_PREFIX}/{other_chat.id}/messages", headers=auth_headers
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_delete_message_success(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        message_id_in_chat: int,
        db_session_test_func: AsyncSession,
    ):
        message_id_to_delete = message_id_in_chat
        log.debug("Attempting to delete message %d...", message_id_to_delete)

        with patch(
            "core.chat.services.message_service.publish_message", new_callable=AsyncMock
        ) as mock_publish:
            response = await async_client.delete(
                f"{FULL_CHAT_PREFIX}/messages/{message_id_to_delete}",
                headers=auth_headers,
            )

        assert response.status_code == status.HTTP_204_NO_CONTENT, (
            f"Response body: {response.text}"
        )
        mock_publish.assert_awaited_once()
        log.debug("Delete request for message %d returned 204.", message_id_to_delete)

    async def test_delete_message_forbidden(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        existing_chat: Chat,
        partner_user: User,
        db_session_test_func: AsyncSession,
    ):
        other_message = await MessageFactory.create_in_chat(
            session=db_session_test_func,
            chat=existing_chat,
            sender=partner_user,
            content="Partner message to delete",
        )
        message_id_to_delete = other_message.id
        log.debug(
            "Created partner message %d for forbidden delete test.",
            message_id_to_delete,
        )

        await perform_delete_and_assert_not_published(
            async_client, auth_headers, message_id_to_delete, status.HTTP_403_FORBIDDEN
        )
        log.debug(
            "Forbidden delete request for message %d correctly returned 403.",
            message_id_to_delete,
        )

    async def test_delete_message_not_found(
        self, async_client: AsyncClient, auth_headers: dict[str, str]
    ):
        message_id_to_delete = 999999
        log.debug("Attempting to delete non-existent message %d.", message_id_to_delete)

        await perform_delete_and_assert_not_published(
            async_client, auth_headers, message_id_to_delete, status.HTTP_404_NOT_FOUND
        )
        log.debug(
            "Not found delete request for message %d correctly returned 404.",
            message_id_to_delete,
        )
