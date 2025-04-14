import pytest
from httpx import AsyncClient, Response  # Добавили Response для type hinting

# Импортируем сервис токенов, чтобы создать реальный токен
from core.auth.services.token_service import TokenService
from core.models import User


@pytest.mark.asyncio
class TestUserInfo:
    USER_INFO_URL = "/api/v1/auth/users/me"
    AUTH_HEADER_FORMAT = "Bearer {}"

    @pytest.fixture(autouse=True)
    def _setup_tokens(
        self, token_service: TokenService, test_user: User, inactive_test_user: User
    ):
        """Generates tokens for tests of this class"""
        self.access_token_active = token_service.create_access_token(test_user)
        self.access_token_inactive = token_service.create_access_token(
            inactive_test_user
        )

    async def _request_user_info(
        self, async_client: AsyncClient, token: str | None = None
    ) -> Response:
        """Sends a GET request to the /users/me endpoint with an optional token."""
        headers = {}
        if token:
            headers["Authorization"] = self.AUTH_HEADER_FORMAT.format(token)
        return await async_client.get(self.USER_INFO_URL, headers=headers)

    async def test_auth_user_check_self_info_success(
        self,
        async_client: AsyncClient,
        test_user: User,
    ):
        response = await self._request_user_info(
            async_client, token=self.access_token_active
        )

        assert response.status_code == 200
        user_data = response.json()
        assert user_data["id"] == test_user.id
        assert user_data["email"] == test_user.email
        assert user_data["username"] == test_user.username
        assert user_data.get("is_active") is True

    async def test_auth_user_check_self_info_inactive(
        self,
        async_client: AsyncClient,
    ):
        response = await self._request_user_info(
            async_client, token=self.access_token_inactive
        )

        assert response.status_code == 403
        assert "The user is inactive" in response.json()["detail"]

    async def test_auth_user_check_self_info_unauthenticated(
        self,
        async_client: AsyncClient,
    ):
        response = await self._request_user_info(async_client)

        assert response.status_code == 401
        assert (
            "Not authenticated" in response.json()["detail"]
            or "Invalid token" in response.json()["detail"]
        )
