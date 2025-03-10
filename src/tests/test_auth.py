import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.services.token_service import create_access_token, create_refresh_token
from core.models import User


@pytest.mark.asyncio()
async def test_register(async_client: AsyncClient, async_transaction: AsyncSession):
    unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    unique_username = f"testuser_{uuid.uuid4().hex[:8]}"
    registration_data = {
        "email": unique_email,
        "password": "password123",
        "confirm_password": "password123",
        "username": unique_username,
    }

    response = await async_client.post("/api/v1/auth/register", json=registration_data)
    assert response.status_code == 200

    user = await async_transaction.execute(select(User).filter_by(email=unique_email))
    user = user.scalar_one_or_none()
    assert user is not None
    assert user.email == unique_email
    assert user.username == unique_username


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "password,expected_status",
    [
        ("testpassword", 200),
        ("wrongpassword", 401),
    ],
)
async def test_login(
    async_client: AsyncClient, test_user: User, password, expected_status
):
    with patch(
        "core.auth.services.token_service.set_refresh_token", new_callable=AsyncMock
    ):
        login_data = {"username": test_user.username, "password": password}
        response = await async_client.post("/api/v1/auth/login", data=login_data)
        assert response.status_code == expected_status
        if expected_status == 200:
            assert "access_token" in response.json()
            assert "refresh_token" in response.json()


@pytest.mark.asyncio
async def test_refresh(async_client: AsyncClient, test_user: User):
    refresh_token = await create_refresh_token(test_user, AsyncMock())

    with (
        patch("core.auth.utils.token_utils.decode_jwt") as mock_decode,
        patch(
            "core.auth.services.token_service.set_refresh_token", new_callable=AsyncMock
        ),
        patch(
            "core.auth.services.token_service.delete_refresh_token",
            new_callable=AsyncMock,
        ),
        patch(
            "core.auth.services.token_service.get_refresh_token", new_callable=AsyncMock
        ) as mock_get_refresh_token,
    ):
        mock_decode.return_value = {"sub": test_user.username, "type": "refresh"}
        mock_get_refresh_token.return_value = refresh_token

        async_client.cookies.set("refresh_token", refresh_token)
        response = await async_client.post("/api/v1/auth/refresh")

        assert response.status_code == 200
        assert "access_token" in response.json()
        assert "refresh_token" in response.json()


@pytest.mark.asyncio
async def test_auth_user_check_self_info(async_client: AsyncClient, test_user: User):
    access_token = create_access_token(test_user)

    with patch("core.auth.utils.token_utils.decode_jwt") as mock_decode:
        mock_decode.return_value = {"sub": test_user.username, "type": "access"}
        headers = {"Authorization": f"Bearer {access_token}"}
        response = await async_client.get("/api/v1/auth/users/me", headers=headers)

    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == test_user.email
    assert user_data["username"] == test_user.username


@pytest.mark.asyncio
async def test_logout(async_client: AsyncClient, test_user: User):
    refresh_token = await create_refresh_token(test_user, AsyncMock())

    with (
        patch("core.auth.utils.token_utils.decode_jwt") as mock_decode,
        patch(
            "core.auth.services.token_service.delete_refresh_token",
            new_callable=AsyncMock,
        ),
    ):
        mock_decode.return_value = {"sub": test_user.username, "type": "refresh"}

        async_client.cookies.set("refresh_token", refresh_token)
        response = await async_client.post("/api/v1/auth/logout")

        assert response.status_code == 200
        assert response.json().get("status") == "success"
        assert "refresh_token" not in response.cookies


@pytest.mark.asyncio
async def test_access_protected_endpoint_without_token(async_client: AsyncClient):
    response = await async_client.get("/api/v1/auth/users/me")
    assert response.status_code == 401
