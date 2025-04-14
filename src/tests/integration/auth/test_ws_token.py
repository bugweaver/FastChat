import pytest
from httpx import AsyncClient, Response

from core.models import User


@pytest.mark.asyncio
class TestWsToken:
    LOGIN_URL = "/api/v1/auth/login"
    WS_TOKEN_URL = "/api/v1/auth/token-for-ws"
    AUTH_HEADER_FORMAT = "Bearer {}"

    @pytest.fixture
    async def logged_in_token(self, async_client: AsyncClient, test_user: User) -> str:
        """Logs in the test user and returns a valid access token."""
        login_data = {"username": test_user.username, "password": "testpassword"}
        login_response = await async_client.post(self.LOGIN_URL, data=login_data)
        login_response.raise_for_status()
        login_data = login_response.json()
        assert "access_token" in login_data
        return login_data["access_token"]

    async def _request_ws_token(
        self, async_client: AsyncClient, access_token: str | None
    ) -> Response:
        """Requests the WebSocket token endpoint."""
        headers = {}
        if access_token:
            headers["Authorization"] = self.AUTH_HEADER_FORMAT.format(access_token)
        return await async_client.get(self.WS_TOKEN_URL, headers=headers)

    async def test_get_token_for_ws_success(
        self,
        async_client: AsyncClient,
        logged_in_token: str,
    ):
        response = await self._request_ws_token(
            async_client, access_token=logged_in_token
        )

        assert response.status_code == 200
        response_data = response.json()
        assert "token" in response_data
        ws_token = response_data["token"]
        assert isinstance(ws_token, str)
        assert len(ws_token) > 20

    async def test_get_token_for_ws_unauthenticated(
        self,
        async_client: AsyncClient,
    ):
        response = await self._request_ws_token(async_client, access_token=None)

        assert response.status_code == 401
        assert (
            "Not authenticated" in response.json()["detail"]
            or "Invalid token" in response.json()["detail"]
        )

    async def test_get_token_for_ws_invalid_token(
        self,
        async_client: AsyncClient,
    ):
        invalid_token = "this.is.invalid"
        response = await self._request_ws_token(
            async_client, access_token=invalid_token
        )
        assert response.status_code == 401
