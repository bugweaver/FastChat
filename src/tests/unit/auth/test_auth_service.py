import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Response, responses, status

from core.auth.forms import CustomOAuth2PasswordRequestForm
from core.auth.services.auth_service import AuthService
from core.schemas.user_schemas import UserSchema
from tests.factories.user_factory import UserRegisterFactory


@pytest.fixture
def auth_service(db_session_test_func, redis_client):
    """Provides an instance of AuthService initialized with test DB and Redis."""
    return AuthService(db=db_session_test_func, redis=redis_client)


@pytest.fixture
def mock_response():
    """Provides a MagicMock simulating a FastAPI Response object."""
    response_mock = MagicMock(spec=Response)
    response_mock.set_cookie = MagicMock()
    response_mock.delete_cookie = MagicMock()
    return response_mock


@pytest.mark.asyncio
class TestAuthService:
    async def test_register_user_success(self, auth_service):
        """Test successful user registration."""
        user_data = UserRegisterFactory()

        result = await auth_service.register_user(user_data)

        assert isinstance(result, UserSchema)
        assert result.email == user_data.email
        assert result.username == user_data.username
        assert result.first_name == user_data.first_name
        assert result.last_name == user_data.last_name

    async def test_register_user_already_exists(self, auth_service, test_user):
        """Test registration attempt when user email already exists."""
        user_data = UserRegisterFactory(
            email=test_user.email, username="new_username_for_email_test"
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.register_user(user_data)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "email" in exc_info.value.detail.lower()
        assert "already exists" in exc_info.value.detail.lower()

    async def test_register_user_username_already_exists(self, auth_service, test_user):
        """Test registration attempt when username already exists."""
        user_data = UserRegisterFactory(
            username=test_user.username, email="new_unique@example.com"
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.register_user(user_data)

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "username" in exc_info.value.detail.lower()
        assert "already exists" in exc_info.value.detail.lower()

    async def test_register_user_unexpected_error(self, auth_service):
        """Test registration failure due to an unexpected internal error."""
        user_data = UserRegisterFactory()
        error_message = "Simulated DB error during creation"

        with patch(
            "core.auth.services.auth_service.create_user",
            side_effect=Exception(error_message),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.register_user(user_data)

            assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "server error" in exc_info.value.detail.lower()

    async def test_login_user_success(self, auth_service, mock_response, test_user):
        """Test successful user login and token generation."""
        form_data = CustomOAuth2PasswordRequestForm(
            username=test_user.username,
            password="testpassword",
        )
        expected_access_token = "mock_access_token"
        expected_refresh_token = "mock_refresh_token"

        with (
            patch.object(
                auth_service.token_service,
                "create_access_token",
                return_value=expected_access_token,
            ) as mock_create_access,
            patch.object(
                auth_service.token_service,
                "create_refresh_token",
                new_callable=AsyncMock,
                return_value=expected_refresh_token,
            ) as mock_create_refresh,
            patch(
                "core.auth.utils.password_utils.validate_password", return_value=True
            ),
        ):
            result = await auth_service.login_user(form_data, mock_response)

            assert result.access_token == expected_access_token
            assert result.refresh_token == expected_refresh_token
            mock_create_access.assert_called_once()
            mock_create_refresh.assert_called_once()
            mock_response.set_cookie.assert_any_call(
                key="access_token",
                value=expected_access_token,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=ANY,
            )
            mock_response.set_cookie.assert_any_call(
                key="refresh_token",
                value=expected_refresh_token,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=ANY,
            )

    async def test_login_user_invalid_credentials_wrong_password(
        self, auth_service, mock_response, test_user
    ):
        """Test login failure with incorrect password."""
        form_data = CustomOAuth2PasswordRequestForm(
            username=test_user.username,
            password="wrongpassword",
        )

        with patch(
            "core.auth.utils.password_utils.validate_password", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.login_user(form_data, mock_response)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "incorrect username or password" in exc_info.value.detail.lower()

    async def test_login_user_invalid_credentials_wrong_username(
        self, auth_service, mock_response
    ):
        """Test login failure with non-existent username."""
        form_data = CustomOAuth2PasswordRequestForm(
            username="nonexistent_user",
            password="anypassword",
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.login_user(form_data, mock_response)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "incorrect username or password" in exc_info.value.detail.lower()

    async def test_login_user_inactive(
        self, auth_service, mock_response, inactive_test_user
    ):
        """Test login failure for an inactive user."""
        form_data = CustomOAuth2PasswordRequestForm(
            username=inactive_test_user.username, password="testpassword"
        )

        with patch(
            "core.auth.utils.password_utils.validate_password", return_value=True
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.login_user(form_data, mock_response)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "user account is inactive" in exc_info.value.detail.lower()

    async def test_validate_auth_user_success(self, auth_service, test_user):
        """Test successful validation of active user credentials."""
        username = test_user.username
        correct_password = "testpassword"

        with patch(
            "core.auth.utils.password_utils.validate_password", return_value=True
        ):
            result = await auth_service.validate_auth_user(username, correct_password)

        assert isinstance(result, UserSchema)
        assert result.username == username
        assert result.email == test_user.email
        assert result.is_active is True

    async def test_validate_auth_user_not_found(self, auth_service):
        """Test validation failure when user is not found."""
        username = "nonexistent_user"
        password = "anypassword"

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.validate_auth_user(username, password)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "incorrect username or password" in exc_info.value.detail.lower()

    async def test_validate_auth_user_wrong_password(self, auth_service, test_user):
        """Test validation failure due to incorrect password."""
        username = test_user.username
        wrong_password = "wrongpassword"

        with patch(
            "core.auth.utils.password_utils.validate_password", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.validate_auth_user(username, wrong_password)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "incorrect username or password" in exc_info.value.detail.lower()

    async def test_validate_auth_user_inactive(self, auth_service, inactive_test_user):
        """Test validation failure for an inactive user."""
        username = inactive_test_user.username
        correct_password = "testpassword"

        with patch(
            "core.auth.utils.password_utils.validate_password", return_value=True
        ):
            with pytest.raises(HTTPException) as exc_info:
                await auth_service.validate_auth_user(username, correct_password)

            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "user account is inactive" in exc_info.value.detail.lower()

    async def test_refresh_tokens(self, auth_service, mock_response, test_user):
        """Test successful refreshing of access and refresh tokens."""
        expected_new_access = "new_access_token"
        expected_new_refresh = "new_refresh_token"

        with (
            patch.object(
                auth_service.token_service,
                "revoke_refresh_token",
                new_callable=AsyncMock,
            ) as mock_revoke,
            patch.object(
                auth_service.token_service,
                "create_access_token",
                return_value=expected_new_access,
            ) as mock_create_access,
            patch.object(
                auth_service.token_service,
                "create_refresh_token",
                new_callable=AsyncMock,
                return_value=expected_new_refresh,
            ) as mock_create_refresh,
        ):
            result = await auth_service.refresh_tokens(test_user, mock_response)

            assert result == {
                "access_token": expected_new_access,
                "refresh_token": expected_new_refresh,
            }
            mock_revoke.assert_called_once_with(test_user.id)
            mock_create_access.assert_called_once_with(test_user)
            mock_create_refresh.assert_called_once_with(test_user)

            mock_response.set_cookie.assert_any_call(
                key="access_token",
                value=expected_new_access,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=ANY,
            )
            mock_response.set_cookie.assert_any_call(
                key="refresh_token",
                value=expected_new_refresh,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=ANY,
            )

    async def test_logout_user(self, auth_service, mock_response, test_user):
        """Test successful user logout (token revocation)."""
        with patch.object(
            auth_service.token_service, "revoke_refresh_token", new_callable=AsyncMock
        ) as mock_revoke:
            result = await auth_service.logout_user(test_user, mock_response)

            assert isinstance(result, (Response, responses.JSONResponse))
            assert result.status_code == status.HTTP_200_OK
            body_content = result.body
            if isinstance(body_content, bytes):
                body_content = body_content.decode()
            if isinstance(body_content, str):
                assert "successfully logged out" in body_content.lower()
            else:
                assert (
                    "successfully logged out" in result.body.get("message", "").lower()
                )

            mock_revoke.assert_called_once_with(test_user.id)
            mock_response.delete_cookie.assert_any_call(
                key="access_token", httponly=True, samesite="lax", secure=False
            )
            mock_response.delete_cookie.assert_any_call(
                key="refresh_token", httponly=True, samesite="lax", secure=False
            )

    async def test_get_ws_token(self, auth_service, test_user):
        """Test generation of a WebSocket token."""
        expected_ws_token = "mock_websocket_token"

        with patch.object(
            auth_service.token_service,
            "create_access_token",
            return_value=expected_ws_token,
        ) as mock_create_ws_token:
            result = await auth_service.get_ws_token(test_user)

            assert isinstance(result, (Response, responses.JSONResponse))
            assert result.status_code == status.HTTP_200_OK

            body = result.body
            if isinstance(body, bytes):
                body = body.decode()

            try:
                json_body = json.loads(body)
                assert "token" in json_body
                assert json_body["token"] == expected_ws_token
            except json.JSONDecodeError:
                pytest.fail(f"Response body is not valid JSON: {body}")
            except TypeError:
                pytest.fail(
                    "Response body could not be parsed"
                    f"(might not be string/bytes): {type(body)}"
                )

            mock_create_ws_token.assert_called_once()

    async def test_get_current_user_info(self, auth_service, test_user):
        """Test retrieving current user information."""
        result = await auth_service.get_current_user_info(test_user)

        assert isinstance(result, UserSchema)
        assert result.id == test_user.id
        assert result.username == test_user.username
        assert result.email == test_user.email
        assert result.first_name == test_user.first_name
        assert result.last_name == test_user.last_name
        assert result.is_active == test_user.is_active
