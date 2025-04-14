import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import User
from tests.factories.user_factory import UserRegisterFactory


@pytest.mark.asyncio
class TestRegister:
    """Tests for the user registration endpoint."""

    API_ENDPOINT = "/api/v1/auth/register"

    async def test_register_success(
        self, async_client: AsyncClient, db_session_test_func: AsyncSession
    ):
        """
        Verify successful user registration with valid data.
        """
        registration_payload = UserRegisterFactory.build().model_dump()

        response = await async_client.post(self.API_ENDPOINT, json=registration_payload)

        assert response.status_code == 200, (
            f"Expected status 200, got {response.status_code}."
            f" Response: {response.text}"
        )
        response_data = response.json()
        assert response_data["email"] == registration_payload["email"]
        assert response_data["username"] == registration_payload["username"]
        assert "id" in response_data

        user = await db_session_test_func.scalar(
            select(User).filter_by(email=registration_payload["email"])
        )
        assert user is not None
        assert user.email == registration_payload["email"]
        assert user.username == registration_payload["username"]
        assert user.is_active is True
        assert user.first_name == registration_payload["first_name"]
        assert user.last_name == registration_payload["last_name"]

    async def test_register_duplicate_email(
        self, async_client: AsyncClient, test_user: User
    ):
        """
        Verify registration fails if the email already exists.
        """
        registration_payload = UserRegisterFactory.build(
            email=test_user.email
        ).model_dump()

        response = await async_client.post(self.API_ENDPOINT, json=registration_payload)

        assert response.status_code == 400, (
            f"Expected status 400, got {response.status_code}."
            f" Response: {response.text}"
        )
        response_data = response.json()
        assert "detail" in response_data
        assert "email" in response_data["detail"].lower()
        assert "already exists" in response_data["detail"].lower()

    async def test_register_duplicate_username(
        self,
        async_client: AsyncClient,
        test_user: User,
        db_session_test_func: AsyncSession,
    ):
        """
        Verify registration fails if the username already exists.
        """
        registration_payload = UserRegisterFactory.build(
            username=test_user.username
        ).model_dump()
        original_email = registration_payload["email"]

        response = await async_client.post(self.API_ENDPOINT, json=registration_payload)

        assert response.status_code == 400, (
            f"Expected status 400, got {response.status_code}."
            f" Response: {response.text}"
        )
        response_data = response.json()
        assert "detail" in response_data
        assert "username" in response_data["detail"].lower()
        assert "already exists" in response_data["detail"].lower()

        user = await db_session_test_func.scalar(
            select(User).filter_by(email=original_email)
        )
        assert user is None, "User should not have been created with duplicate username"

    async def test_register_password_mismatch(self, async_client: AsyncClient):
        """
        Verify registration fails with 422
        if password and confirm_password do not match.
        """
        registration_payload = {
            "email": f"mismatch_{uuid.uuid4().hex[:8]}@example.com",
            "username": f"mismatch_user_{uuid.uuid4().hex[:8]}",
            "first_name": "Mismatch",
            "last_name": "Pass",
            "password": "password123",
            "confirm_password": "password456",
        }

        response = await async_client.post(self.API_ENDPOINT, json=registration_payload)

        assert response.status_code == 422, (
            f"Expected status 422, got {response.status_code}."
            f" Response: {response.text}"
        )
        response_data = response.json()
        assert "detail" in response_data
        assert isinstance(response_data["detail"], list), (
            "Expected validation error detail to be a list"
        )
        assert len(response_data["detail"]) > 0, (
            "Expected at least one validation error"
        )
        password_error_found = False
        for error in response_data["detail"]:
            if (
                isinstance(error.get("loc"), list)
                and ("confirm_password" in error["loc"] or "password" in error["loc"])
                and "match" in error.get("msg", "").lower()
            ):
                password_error_found = True
                break
        assert password_error_found, (
            "Validation error detail for password mismatch not found:"
            f" {response_data['detail']}"
        )


# TODO: Test missing required fields (should result in 422),
# TODO: Test invalid email format (should result in 422)
# TODO: Test password complexity rules if you have them (should result in 400 or 422)
