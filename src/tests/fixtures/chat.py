import logging
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.models import Chat
from tests.factories.chat_factory import ChatFactory
from tests.factories.user_factory import UserFactory

API_PREFIX = settings.api.prefix + settings.api.v1.prefix
CHAT_PREFIX = settings.api.v1.chat
FULL_CHAT_PREFIX = API_PREFIX + CHAT_PREFIX

log = logging.getLogger(__name__)


@pytest.fixture
def auth_headers(test_user_token: str) -> dict[str, str]:
    """Provides authorization headers for the test user."""
    return {"Authorization": f"Bearer {test_user_token}"}


@pytest.fixture
async def other_chat(db_session_test_func: AsyncSession) -> Chat:
    """Creates a chat between two unrelated users."""
    user3 = await UserFactory.create_async(
        session=db_session_test_func,
    )
    user4 = await UserFactory.create_async(
        session=db_session_test_func,
    )
    chat = await ChatFactory.create_private_chat(
        session=db_session_test_func, user1=user3, user2=user4
    )
    return chat


async def perform_delete_and_assert_not_published(
    async_client: AsyncClient,
    auth_headers: dict[str, str],
    message_id: int,
    expected_status: int,
) -> None:
    """Helper to perform DELETE request and assert publish was not called."""
    with patch(
        "core.chat.services.message_service.publish_message", new_callable=AsyncMock
    ) as mock_publish:
        response = await async_client.delete(
            f"{FULL_CHAT_PREFIX}/messages/{message_id}", headers=auth_headers
        )

    assert response.status_code == expected_status, f"Response body: {response.text}"
    mock_publish.assert_not_awaited()
