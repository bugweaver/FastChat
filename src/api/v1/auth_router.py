from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import ORJSONResponse

from core.auth.dependencies import get_auth_service
from core.auth.forms import CustomOAuth2PasswordRequestForm
from core.auth.services.auth_service import AuthService
from core.auth.validation.auth_validation import (
    get_current_active_auth_user,
    get_current_user_from_refresh_token,
)
from core.models import User
from core.schemas.token_schemas import TokenInfo
from core.schemas.user_schemas import UserRegister, UserSchema

router = APIRouter(tags=["JWT"])


@router.post("/register", response_model=UserSchema)
async def register(
    data: UserRegister,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserSchema:
    """
    Register a new user.
    The password is hashed before saving the user to the database.
    """
    return await auth_service.register_user(data)


@router.post("/login", response_model=TokenInfo)
async def login(
    response: Response,
    form_data: Annotated[CustomOAuth2PasswordRequestForm, Depends()],
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenInfo:
    """
    Authenticates a user using their credentials
    and generates JWT tokens.
    """
    return await auth_service.login_user(form_data, response)


@router.post("/refresh")
async def refresh(
    response: Response,
    current_user: User = Depends(get_current_user_from_refresh_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenInfo:
    """
    Invalidates the current refresh token
    and generates new access and refresh tokens.
    """
    token_data_dict = await auth_service.refresh_tokens(current_user, response)
    return TokenInfo(**token_data_dict)


@router.get("/users/me")
async def auth_user_check_self_info(
    user: User = Depends(get_current_active_auth_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserSchema:
    """
    Retrieves details of the currently logged-in user
    based on their access token.
    """
    return await auth_service.get_current_user_info(user)


@router.post("/logout")
async def logout(
    response: Response,
    current_user: User = Depends(get_current_user_from_refresh_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> ORJSONResponse:
    """
    Removes refresh token from cookies
    and revokes the user's current refresh token in Redis.
    """
    return await auth_service.logout_user(current_user, response)


@router.get("/token-for-ws")
async def get_token_for_ws(
    user: User = Depends(get_current_active_auth_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> ORJSONResponse:
    return await auth_service.get_ws_token(user)
