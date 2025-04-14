from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from fakeredis import FakeAsyncRedis

from core.auth.services.token_service import TokenService
from core.models import User


def get_redis_refresh_token_key(user_id: int) -> str:
    return f"refresh_token:{user_id}"


@pytest_asyncio.fixture(scope="function")
def token_service(redis_client: FakeAsyncRedis) -> TokenService:
    """A TokenService instance using a sandboxed redis client."""
    return TokenService(redis_client)


@pytest_asyncio.fixture(scope="function")
async def test_user_token(test_user: User, token_service: TokenService) -> str:
    """Generates an access token for a test user."""
    return token_service.create_access_token(test_user)


@pytest_asyncio.fixture
async def mock_redis_client_on_token_service(
    token_service: TokenService,
) -> AsyncGenerator[AsyncMock, None]:
    """Overrides the revoke_refresh_token method in TokenService."""
    with patch.object(
        token_service, "revoke_refresh_token", new_callable=AsyncMock
    ) as mock:
        yield mock
