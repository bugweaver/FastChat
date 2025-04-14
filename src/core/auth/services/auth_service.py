import logging

from fastapi import HTTPException, Response, status
from fastapi.responses import ORJSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.services.token_service import TokenService
from core.auth.utils.cookies_utils import (
    delete_access_token_cookie,
    delete_refresh_token_cookie,
    set_access_token_cookie,
    set_refresh_token_cookie,
)
from core.auth.utils.password_utils import validate_password
from core.models import User
from core.schemas.token_schemas import TokenInfo
from core.schemas.user_schemas import UserCreate, UserRegister, UserSchema
from repositories.user_repo import create_user, get_user_by_email, get_user_by_username

log = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis
        self.token_service = TokenService(redis)

    async def register_user(self, data: UserRegister) -> UserSchema:
        lower_email = str(data.email).lower()
        user_by_email = await get_user_by_email(db=self.db, email=lower_email)
        if user_by_email:
            log.warning(
                "Registration attempt failed: Email '%s' already exists.", lower_email
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The user with this email already exists.",
            )

        user_by_username = await get_user_by_username(
            db=self.db, username=data.username
        )
        if user_by_username:
            log.warning(
                "Registration attempt failed: Username '%s' already exists.",
                data.username,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The user with this username already exists.",
            )

        try:
            user_create = UserCreate(**data.model_dump(exclude={"confirm_password"}))
            new_user = await create_user(db=self.db, user_create=user_create)
            return UserSchema.model_validate(new_user)
        except IntegrityError as e:
            log.warning(
                "IntegrityError during user creation for username '%s' or email '%s'",
                data.username,
                data.email,
                exc_info=False,
            )
            error_info = str(getattr(e, "orig", e)).lower()
            detail = "Username or email might already be taken."
            if "username" in error_info:
                detail = "Username already taken."
            elif "email" in error_info:
                detail = "Email already registered."

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=detail
            ) from e

        except Exception as e:
            log.error(
                "Registration failed for email %s: %s", data.email, e, exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Registration failed due to a server error.",
            ) from e

    async def login_user(
        self, form_data: OAuth2PasswordRequestForm, response: Response
    ) -> TokenInfo:
        try:
            user = await self.validate_auth_user(form_data.username, form_data.password)

            access_token = self.token_service.create_access_token(user)
            refresh_token = await self.token_service.create_refresh_token(user)

            set_access_token_cookie(response, access_token)
            set_refresh_token_cookie(response, refresh_token)

            log.info("User '%s' logged in successfully.", user.username)
            return TokenInfo(access_token=access_token, refresh_token=refresh_token)
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            log.exception(
                "Unexpected error during login for user '%s': %s", form_data.username, e
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred during login. Please try again later.",
            ) from e

    async def refresh_tokens(self, current_user: User, response: Response) -> dict:
        try:
            await self.token_service.revoke_refresh_token(current_user.id)

            new_access_token = self.token_service.create_access_token(current_user)
            new_refresh_token = await self.token_service.create_refresh_token(
                current_user
            )

            set_access_token_cookie(response, new_access_token)
            set_refresh_token_cookie(response, new_refresh_token)

            token_data = {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
            }
            log.info(
                "Tokens refreshed successfully for user '%s'.", current_user.username
            )
            return token_data
        except Exception as e:
            log.exception(
                "Unexpected error during token refresh for user %s: %s",
                current_user.id,
                e,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to refresh session. Please log in again.",
            ) from e

    async def logout_user(
        self, current_user: User, response: Response
    ) -> ORJSONResponse:
        logout_status = "success"
        detail_message = "Successfully logged out"
        try:
            await self.token_service.revoke_refresh_token(current_user.id)
            log.info("Refresh token revoked for user '%s'.", current_user.username)
        except Exception as e:
            log.error(
                "Error revoking refresh token for user %s during logout: %s",
                current_user.id,
                e,
                exc_info=True,
            )
            logout_status = "warning"
            detail_message = "Logout completed, but server cleanup might be incomplete."
        finally:
            delete_access_token_cookie(response)
            delete_refresh_token_cookie(response)

        result = {
            "detail": detail_message,
            "status": logout_status,
            "user": current_user.username,
        }

        return ORJSONResponse(content=result, status_code=status.HTTP_200_OK)

    async def validate_auth_user(self, username: str, password: str) -> UserSchema:
        """Validates user credentials for login."""
        unauthed_exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

        user = await get_user_by_username(self.db, username)

        if not user:
            log.warning("Login attempt failed: User '%s' not found.", username)
            raise unauthed_exc

        if not user.password:
            log.error(
                "Security Alert: User '%s' has no password set in the database.",
                username,
            )
            raise unauthed_exc

        if not validate_password(
            password, hashed_password=user.password.encode("utf-8")
        ):
            log.warning(
                "Login attempt failed: Invalid password for user '%s'.", username
            )
            raise unauthed_exc

        if not user.is_active:
            log.warning("Login attempt failed: User '%s' is inactive.", username)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )

        log.info("User '%s' successfully validated for login.", username)
        return UserSchema.model_validate(user)

    async def get_ws_token(self, user: User) -> ORJSONResponse:
        """
        Generates a short-lived access token
        suitable for WebSocket authentication.
        """
        try:
            token = self.token_service.create_access_token(
                UserSchema.model_validate(user)
            )
            log.debug("Generated WS token for user '%s'.", user.username)
            return ORJSONResponse(content={"token": token})
        except Exception as e:
            log.exception("Error generating WS token for user %s: %s", user.id, e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not generate WebSocket token.",
            ) from e

    async def get_current_user_info(self, user: User) -> UserSchema:
        """Returns the validated user's information."""
        return UserSchema.model_validate(user)
