from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from jwt import InvalidTokenError

from core.auth.services.token_service import TokenService
from core.models import User
from core.schemas.user_schemas import UserSchema


@pytest.mark.asyncio
class TestTokenService:
    async def test_create_jwt(self, token_service: TokenService):
        token_type = "test"
        token_data = {"sub": "test_user"}
        expire_minutes = 30

        with patch(
            "core.auth.services.token_service.encode_jwt", return_value="mock.jwt.token"
        ) as mock_encode:
            token = token_service.create_jwt(
                token_type=token_type,
                token_data=token_data,
                expire_minutes=expire_minutes,
            )
            assert token == "mock.jwt.token"
            mock_encode.assert_called_once()
            call_args = mock_encode.call_args[1]
            assert call_args["payload"][TokenService.TOKEN_TYPE_FIELD] == token_type
            assert call_args["payload"]["sub"] == "test_user"
            assert call_args["expire_minutes"] == expire_minutes

    async def test_create_access_token(
        self, token_service: TokenService, test_user: User
    ):
        user_schema = UserSchema.model_validate(test_user)

        with patch.object(
            token_service, "create_jwt", return_value="test_access_token"
        ) as mock_create_jwt:
            token = token_service.create_access_token(user_schema)

        assert token == "test_access_token"
        mock_create_jwt.assert_called_once()
        call_args = mock_create_jwt.call_args[1]
        assert call_args["token_type"] == TokenService.ACCESS_TOKEN_TYPE
        assert call_args["token_data"]["sub"] == user_schema.username

    async def test_create_refresh_token(
        self, token_service: TokenService, test_user: User
    ):
        user_schema = UserSchema.model_validate(test_user)

        with (
            patch(
                "core.auth.services.token_service.set_refresh_token",
                new_callable=AsyncMock,
            ) as mock_set,
            patch.object(
                token_service, "create_jwt", return_value="test_refresh_token"
            ) as mock_create_jwt,
        ):
            token = await token_service.create_refresh_token(user_schema)

        assert token == "test_refresh_token"
        mock_create_jwt.assert_called_once()
        mock_set.assert_called_once()
        call_args = mock_set.call_args[0]
        assert call_args[0] == token_service.redis
        assert call_args[1] == user_schema.id
        assert call_args[2] == "test_refresh_token"
        assert call_args[3] > 0

    async def test_validate_refresh_token_valid(self, token_service: TokenService):
        user_id = 1
        token = "test_token_string"

        with patch(
            "core.auth.services.token_service.get_refresh_token",
            new_callable=AsyncMock,
            return_value=token,
        ) as mock_get:
            result = await token_service.validate_refresh_token(user_id, token)

        assert result is True
        mock_get.assert_called_once_with(token_service.redis, user_id)

    async def test_validate_refresh_token_invalid_or_missing(
        self, token_service: TokenService
    ):
        user_id = 1
        token = "test_token"

        with patch(
            "core.auth.services.token_service.get_refresh_token",
            new_callable=AsyncMock,
            return_value="different_token",
        ) as mock_get_diff:
            result_diff = await token_service.validate_refresh_token(user_id, token)

        with patch(
            "core.auth.services.token_service.get_refresh_token",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_get_none:
            result_none = await token_service.validate_refresh_token(user_id, token)

        assert result_diff is False
        assert result_none is False
        mock_get_diff.assert_called_once_with(token_service.redis, user_id)
        mock_get_none.assert_called_once_with(token_service.redis, user_id)

    async def test_revoke_refresh_token(self, token_service: TokenService):
        user_id = 1

        with patch(
            "core.auth.services.token_service.delete_refresh_token",
            new_callable=AsyncMock,
        ) as mock_delete:
            await token_service.revoke_refresh_token(user_id)
        mock_delete.assert_called_once_with(token_service.redis, user_id)

    async def test_get_current_refresh_token_from_cookie(self):
        token = "test_refresh_token"
        request = MagicMock(spec=Request)
        request.cookies = {"refresh_token": token}
        result = TokenService.get_current_refresh_token_from_cookie(request)

        assert result == token

    async def test_get_current_refresh_token_from_cookie_missing(self):
        request = MagicMock(spec=Request)
        request.cookies = {}

        with pytest.raises(HTTPException) as excinfo:
            TokenService.get_current_refresh_token_from_cookie(request)

        assert excinfo.value.status_code == 401
        assert "Refresh Token not found in cookie." in excinfo.value.detail

    async def test_get_current_access_token_payload(self):
        token = "valid.jwt.token"
        payload_to_return = {
            "sub": "testuser",
            TokenService.TOKEN_TYPE_FIELD: TokenService.ACCESS_TOKEN_TYPE,
        }
        request = MagicMock(spec=Request)
        request.cookies = {"access_token": token}
        request.headers = {}

        with patch(
            "core.auth.services.token_service.decode_jwt",
            return_value=payload_to_return,
        ) as mock_decode:
            result = TokenService.get_current_access_token_payload(request)

        assert result == payload_to_return
        mock_decode.assert_called_once_with(token=token)

    async def test_get_current_access_token_payload_from_header(self):
        token = "valid.jwt.token.header"
        payload_to_return = {
            "sub": "testuser_header",
            TokenService.TOKEN_TYPE_FIELD: TokenService.ACCESS_TOKEN_TYPE,
        }
        request = MagicMock(spec=Request)
        request.cookies = {}
        request.headers = {"Authorization": f"Bearer {token}"}

        with patch(
            "core.auth.services.token_service.decode_jwt",
            return_value=payload_to_return,
        ) as mock_decode:
            result = TokenService.get_current_access_token_payload(request)

        assert result == payload_to_return
        mock_decode.assert_called_once_with(token=token)

    async def test_get_current_access_token_payload_missing(self):
        request = MagicMock(spec=Request)
        request.cookies = {}
        request.headers = {}

        with pytest.raises(HTTPException) as excinfo:
            TokenService.get_current_access_token_payload(request)

        assert excinfo.value.status_code == 401
        assert "Access Token not found in cookie." in excinfo.value.detail

    async def test_get_current_access_token_payload_invalid_token(self):
        token = "invalid.jwt.token"
        request = MagicMock(spec=Request)
        request.cookies = {"access_token": token}
        request.headers = {}

        error_message = "Signature verification failed"
        with patch(
            "core.auth.services.token_service.decode_jwt",
            side_effect=InvalidTokenError(error_message),
        ) as mock_decode:
            with pytest.raises(HTTPException) as excinfo:
                TokenService.get_current_access_token_payload(request)

        assert excinfo.value.status_code == 401
        assert "Invalid token" in excinfo.value.detail
        assert error_message in excinfo.value.detail
        mock_decode.assert_called_once_with(token=token)

    async def test_validate_token_type_valid(self, token_service: TokenService):
        token_type = TokenService.ACCESS_TOKEN_TYPE
        payload = {TokenService.TOKEN_TYPE_FIELD: token_type}

        result = token_service.validate_token_type(payload, token_type)

        assert result is True

    async def test_validate_token_type_invalid(self, token_service: TokenService):
        payload = {TokenService.TOKEN_TYPE_FIELD: TokenService.ACCESS_TOKEN_TYPE}
        expected_type = TokenService.REFRESH_TOKEN_TYPE

        with pytest.raises(HTTPException) as excinfo:
            token_service.validate_token_type(payload, expected_type)

        assert excinfo.value.status_code == 401
        assert "Invalid token type" in excinfo.value.detail
        assert TokenService.ACCESS_TOKEN_TYPE in excinfo.value.detail
        assert expected_type in excinfo.value.detail

    async def test_validate_token_type_missing(self, token_service: TokenService):
        payload = {"sub": "testuser"}
        expected_type = TokenService.ACCESS_TOKEN_TYPE

        with pytest.raises(HTTPException) as excinfo:
            token_service.validate_token_type(payload, expected_type)

        assert excinfo.value.status_code == 401
        assert "Invalid token type" in excinfo.value.detail
        assert "none" in excinfo.value.detail.lower()
        assert expected_type in excinfo.value.detail
