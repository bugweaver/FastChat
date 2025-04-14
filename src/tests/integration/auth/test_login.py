import pytest
from fakeredis import FakeAsyncRedis
from httpx import AsyncClient
from starlette import status

from core.models import User
from tests.fixtures.auth import get_redis_refresh_token_key


@pytest.mark.asyncio
class TestLogin:
    API_ENDPOINT = "/api/v1/auth/login"

    @pytest.mark.parametrize(
        "password, expected_status",
        [
            ("testpassword", 200),
            ("wrongpassword", 401),
        ],
    )
    async def test_login(
        self,
        async_client: AsyncClient,
        test_user: User,
        redis_client: FakeAsyncRedis,
        password: str,
        expected_status: int,
    ):
        login_data = {"username": test_user.username, "password": password}
        redis_key = get_redis_refresh_token_key(test_user.id)

        assert await redis_client.exists(redis_key) == 0

        response = await async_client.post(self.API_ENDPOINT, data=login_data)

        # Assert
        assert response.status_code == expected_status

        if expected_status == 200:
            data = response.json()
            assert "access_token" in data
            assert "refresh_token" in data
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            assert access_token
            assert refresh_token

            assert "access_token" in response.cookies
            assert "refresh_token" in response.cookies
            assert response.cookies["access_token"] == access_token
            assert response.cookies["refresh_token"] == refresh_token

            stored_token = await redis_client.get(redis_key)
            assert stored_token is not None
            assert stored_token == refresh_token
        else:
            assert await redis_client.exists(redis_key) == 0
            assert "access_token" not in response.cookies
            assert "refresh_token" not in response.cookies

    async def test_login_inactive_user(
        self,
        async_client: AsyncClient,
        inactive_test_user: User,
        redis_client: FakeAsyncRedis,
    ):
        login_data = {
            "username": inactive_test_user.username,
            "password": "testpassword",
        }
        redis_key = get_redis_refresh_token_key(inactive_test_user.id)

        response = await async_client.post(self.API_ENDPOINT, data=login_data)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        detail = response.json().get("detail", "").lower()
        assert "user account is inactive" in detail

        assert await redis_client.exists(redis_key) == 0
        assert "access_token" not in response.cookies
        assert "refresh_token" not in response.cookies
