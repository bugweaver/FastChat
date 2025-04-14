import fakeredis.aioredis
import pytest
from httpx import AsyncClient

from core.models import User
from tests.fixtures.auth import get_redis_refresh_token_key


@pytest.mark.asyncio
class TestLogout:
    async def test_logout_success(
        self,
        async_client: AsyncClient,
        test_user: User,
        redis_client: fakeredis.aioredis.FakeRedis,
    ):
        login_data = {"username": test_user.username, "password": "testpassword"}
        login_response = await async_client.post("/api/v1/auth/login", data=login_data)
        assert login_response.status_code == 200
        refresh_token_cookie = login_response.cookies.get("refresh_token")
        assert refresh_token_cookie is not None

        redis_key = get_redis_refresh_token_key(test_user.id)
        assert await redis_client.exists(redis_key) == 1

        logout_response = await async_client.post("/api/v1/auth/logout")

        # Assert
        assert logout_response.status_code == 200
        logout_data = logout_response.json()
        assert logout_data.get("status") == "success"
        assert logout_data.get("detail") == "Successfully logged out"
        assert logout_data.get("user") == test_user.username

        assert await redis_client.exists(redis_key) == 0

        assert "access_token" not in logout_response.cookies
        assert "refresh_token" not in logout_response.cookies

    async def test_logout_without_token(self, async_client: AsyncClient):
        async_client.cookies.clear()
        response = await async_client.post("/api/v1/auth/logout")

        assert response.status_code == 401
        assert "Refresh Token not found in cookie." in response.json()["detail"]
