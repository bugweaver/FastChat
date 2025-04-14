import pytest
from fakeredis import FakeAsyncRedis
from httpx import AsyncClient, Response

from core.models import User
from tests.fixtures.auth import get_redis_refresh_token_key


@pytest.mark.asyncio
class TestRefresh:
    REFRESH_URL = "/api/v1/auth/refresh"
    LOGIN_URL = "/api/v1/auth/login"
    REFRESH_COOKIE_NAME = "refresh_token"
    ACCESS_COOKIE_NAME = "access_token"

    async def _request_refresh(
        self, async_client: AsyncClient, headers: dict | None = None
    ) -> Response:
        """Sends a POST request to the token refresh endpoint."""
        return await async_client.post(self.REFRESH_URL, headers=headers or {})

    async def test_refresh_success(
        self,
        async_client: AsyncClient,
        test_user: User,
        redis_client: FakeAsyncRedis,
    ):
        login_data = {"username": test_user.username, "password": "testpassword"}
        login_response = await async_client.post(self.LOGIN_URL, data=login_data)
        assert login_response.status_code == 200
        initial_refresh_token = login_response.cookies.get(self.REFRESH_COOKIE_NAME)
        assert initial_refresh_token is not None

        redis_key = get_redis_refresh_token_key(test_user.id)
        assert await redis_client.get(redis_key) == initial_refresh_token

        headers = {"cookie": f"{self.REFRESH_COOKIE_NAME}={initial_refresh_token}"}
        refresh_response = await self._request_refresh(async_client, headers=headers)

        assert refresh_response.status_code == 200
        refresh_data = refresh_response.json()

        assert "access_token" in refresh_data
        assert "refresh_token" in refresh_data
        new_access_token = refresh_data["access_token"]
        new_refresh_token = refresh_data["refresh_token"]
        assert new_access_token
        assert new_refresh_token
        assert new_refresh_token != initial_refresh_token

        assert self.ACCESS_COOKIE_NAME in refresh_response.cookies
        assert self.REFRESH_COOKIE_NAME in refresh_response.cookies
        assert refresh_response.cookies[self.ACCESS_COOKIE_NAME] == new_access_token
        assert refresh_response.cookies[self.REFRESH_COOKIE_NAME] == new_refresh_token

        stored_token = await redis_client.get(redis_key)
        assert stored_token is not None
        assert stored_token == new_refresh_token

    async def test_refresh_without_token(self, async_client: AsyncClient):
        response = await self._request_refresh(async_client)

        assert response.status_code == 401
        assert "Refresh Token not found" in response.json()["detail"]

    async def test_refresh_with_invalid_token(
        self, async_client: AsyncClient, test_user: User, redis_client: FakeAsyncRedis
    ):
        redis_key = get_redis_refresh_token_key(test_user.id)
        valid_token_in_redis = "valid_token_123"
        invalid_token_in_cookie = "invalid_token_456"

        await redis_client.set(redis_key, valid_token_in_redis)

        headers = {"cookie": f"{self.REFRESH_COOKIE_NAME}={invalid_token_in_cookie}"}
        response = await self._request_refresh(async_client, headers=headers)

        assert response.status_code == 401
        assert "Invalid refresh token" in response.json()["detail"]
        assert await redis_client.get(redis_key) == valid_token_in_redis
