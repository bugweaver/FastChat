from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.forms import CustomOAuth2PasswordRequestForm
from core.auth.services.token_service import (
    create_access_token,
    create_refresh_token,
    revoke_refresh_token,
)
from core.auth.utils.password_utils import hash_password
from core.auth.validation.auth_validation import (
    get_current_active_auth_user,
    get_current_user_from_refresh_token,
    validate_auth_user_db,
)
from core.config import settings
from core.dependencies import get_redis, oauth2_scheme
from core.models import User, db_helper
from core.schemas.token_schemas import TokenInfo
from core.schemas.user_schemas import UserRegister, UserSchema
from repositories.user_repo import get_user_by_email

router = APIRouter(prefix="", tags=["JWT"])


@router.post("/register", response_model=UserSchema)
async def register(
    data: UserRegister,
    db: AsyncSession = Depends(db_helper.session_getter),
) -> UserSchema:
    """
    description: |
        **Register a new user.**

        This endpoint allows a new user to register by providing their details.
        The password is hashed before saving the user to the database.
        If a user with the provided email already exists, an exception is raised.

    ### Arguments
    - `data` (*UserRegister*): The registration data provided by the user.

    - `db` (*AsyncSession*): The database session dependency.

    ### Returns
    - `UserSchema`: The newly registered user's data.

    ### Raises
    - `HTTPException`: If a user with the given email already exists.
    """
    user = await get_user_by_email(db=db, email=str(data.email))
    if user:
        raise HTTPException(
            status_code=400, detail="The user with this email already exists."
        )

    user_data = data.model_dump(exclude={"confirm_password"})
    hashed_password_bytes = hash_password(user_data["password"])
    user_data["password"] = hashed_password_bytes.decode("utf-8")

    new_user = User(**user_data)
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    user_schema = UserSchema.model_validate(new_user)
    return user_schema


@router.post("/login", response_model=TokenInfo)
async def login(
    response: Response,
    form_data: Annotated[CustomOAuth2PasswordRequestForm, Depends()],
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(db_helper.session_getter),
) -> TokenInfo:
    """
    description: |
        **Log in a user and generate access and refresh tokens.**

        This endpoint authenticates a user using their credentials
        and generates JWT tokens.

    ### Arguments
    - `response` (*Response*): The HTTP response object to set cookies.

    - `form_data` (*CustomOAuth2PasswordRequestForm*): The login credentials
    provided by the user.

    - `redis` (*Redis*): Redis connection for storing refresh tokens.

    - `db` (*AsyncSession*): The database session dependency.

    ### Returns
    `TokenInfo`: The access and refresh tokens for the authenticated user.

    ### Raises
    `HTTPException`: If authentication fails or the user does not exist.
    """
    user = await validate_auth_user_db(form_data.username, form_data.password, db)

    access_token = create_access_token(user)
    refresh_token = await create_refresh_token(user, redis)

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=int(
            timedelta(
                minutes=settings.auth_jwt.access_token_expire_minutes
            ).total_seconds()
        ),
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=int(
            timedelta(days=settings.auth_jwt.refresh_token_expire_days).total_seconds()
        ),
    )

    return TokenInfo(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh")
async def refresh(
    current_user: UserSchema = Depends(get_current_user_from_refresh_token),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    """
    description: |
        **Refresh access and refresh tokens.**

        This endpoint invalidates the current refresh token
        and generates new access and refresh tokens.

    ## Arguments:
    - `current_user` (`UserSchema`): The currently authenticated user
                                       from the refresh token.

    - `redis` (`Redis`): Redis connection for managing token storage.

    ## Returns:
    `JSONResponse`: A JSON response containing the new access and refresh tokens.

    ## Raises:
    `HTTPException`: If the refresh token is invalid or expired.
    """
    await revoke_refresh_token(current_user.id, redis)

    new_access_token = create_access_token(current_user)
    new_refresh_token = await create_refresh_token(current_user, redis)

    token_data = {"access_token": new_access_token, "refresh_token": new_refresh_token}
    response = JSONResponse(content=token_data)

    response.set_cookie(
        key="access_token",
        value=new_access_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=int(settings.auth_jwt.access_token_expire_minutes * 60),
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=int(
            timedelta(days=settings.auth_jwt.refresh_token_expire_days).total_seconds()
        ),
    )

    return response


@router.get("/users/me", dependencies=[Depends(oauth2_scheme)])
async def auth_user_check_self_info(
    user: User = Depends(get_current_active_auth_user),
) -> UserSchema:
    """
    description: |
        **Get information about the currently authenticated user.**

        This endpoint retrieves details of the currently logged-in user
        based on their access token.

    ## Arguments:
    - `user` (`User`): The current active authenticated user.

    ## Returns:
    `UserSchema`: The user's information in schema format.

    ## Raises:
    `HTTPException`: If authentication fails or the user is inactive.
    """
    return UserSchema.model_validate(user)


@router.post("/logout")
async def logout(
    response: Response,
    current_user: UserSchema = Depends(get_current_user_from_refresh_token),
    redis: Redis = Depends(get_redis),
) -> JSONResponse:
    """
    description: |
        **Log out a user by revoking their refresh token and clearing cookies.**

        This endpoint removes both access and refresh tokens from cookies
        and revokes the user's current refresh token in Redis.

    ## Arguments:
    - `response` (`Response`): The HTTP response object to delete cookies.

    - `current_user` (`UserSchema`): The currently authenticated user.

    - `redis` (`Redis`): Redis connection for managing token storage.

    ## Returns:
    `JSONResponse`: A JSON response indicating successful logout.
    """
    await revoke_refresh_token(current_user.id, redis)

    response.delete_cookie(
        key="access_token", httponly=True, secure=False, samesite="lax"
    )
    response.delete_cookie(
        key="refresh_token", httponly=True, secure=False, samesite="lax"
    )
    return JSONResponse(
        content={
            "detail": "Успешный выход",
            "status": "success",
            "user": current_user.username,
        },
        status_code=200,
    )
