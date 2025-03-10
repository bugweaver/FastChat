from typing import Awaitable, Callable

from fastapi import Depends, Form, HTTPException, Request, status
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.auth.exceptions import CredentialsException, MissingUsernameError
from core.auth.services.token_service import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    TOKEN_TYPE_FIELD,
)
from core.auth.utils.password_utils import validate_password
from core.auth.utils.token_utils import decode_jwt
from core.models import User, db_helper
from core.schemas.user_schemas import UserSchema
from repositories.user_repo import get_user_by_username


async def get_current_user_from_refresh_token(
    request: Request,
    db: AsyncSession = Depends(db_helper.session_getter),
) -> User:
    token = get_current_refresh_token_from_cookie(request)

    try:
        payload = decode_jwt(token)
        username: str = payload.get("sub")
        if username is None:
            raise MissingUsernameError()
        token_type: str = payload.get("type")
        if token_type != "refresh":
            raise InvalidTokenError("Token type is invalid")
    except (InvalidTokenError, MissingUsernameError) as e:
        raise CredentialsException() from e

    user = await get_user_by_username(db, username)
    if not user:
        raise CredentialsException(detail="Пользователь не найден")

    return user


def get_current_refresh_token_from_cookie(request: Request) -> str:
    """получение refresh токена"""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Токен не найден в куки.",
        )
    return token


def get_current_access_token_payload(request: Request) -> dict:
    """получение access токена"""
    token = request.cookies.get("access_token")

    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access Токен не найден в куки.",
        )

    try:
        payload = decode_jwt(token=token)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Неверный токен: {e}",
        ) from e

    return payload


def get_current_refresh_token_payload(request: Request) -> dict:
    """получение refresh токена"""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Токен не найден в куки.",
        )

    try:
        payload = decode_jwt(token=token)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Неверный токен: {e}",
        ) from e

    return payload


def validate_token_type(payload: dict, token_type: str) -> bool:
    """проверка на подходящий токен (используется в разных случаях)"""
    current_token_type = payload.get(TOKEN_TYPE_FIELD)
    if current_token_type == token_type:
        return True
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Неверный тип токена {current_token_type!r}, ожидается: {token_type!r}",
    )


def get_current_auth_user_from_access_token_of_type(
    token_type: str,
) -> Callable[..., Awaitable[User]]:
    """проверка access токена"""

    async def get_auth_user_from_token(
        payload: dict = Depends(get_current_access_token_payload),
        db: AsyncSession = Depends(db_helper.session_getter),
    ) -> User:
        validate_token_type(payload, token_type)
        return await get_user_by_token_sub(payload, db)

    return get_auth_user_from_token


def get_current_auth_user_from_refresh_token_of_type(
    token_type: str,
) -> Callable[..., Awaitable[User]]:
    """проверка refresh токена"""

    async def get_auth_user_from_token(payload: dict, db: AsyncSession) -> User:
        validate_token_type(payload, token_type)
        return await get_user_by_token_sub(payload, db)

    return get_auth_user_from_token


get_current_auth_user = get_current_auth_user_from_access_token_of_type(
    ACCESS_TOKEN_TYPE
)

get_current_auth_user_for_refresh = get_current_auth_user_from_refresh_token_of_type(
    REFRESH_TOKEN_TYPE
)


async def get_user_by_token_sub(
    payload: dict,
    db: AsyncSession,
) -> User:
    """получение пользователя по access токену"""
    username: str | None = payload.get("sub")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный токен (пользователь не найден)",
        )

    return user


async def get_current_active_auth_user(
    user: User = Depends(get_current_auth_user),
) -> User:
    """получение авторизованного пользователя"""
    if user.is_active:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Пользователь неактивен",
    )


async def validate_auth_user_db(
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(db_helper.session_getter),
) -> UserSchema:
    """валидация введенных пользователем данных (используется для входа)"""
    unauthed_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный логин или пароль",
    )

    user = await get_user_by_username(db, username)

    if not user:
        raise unauthed_exc

    if not validate_password(password, hashed_password=user.password.encode("utf-8")):
        raise unauthed_exc

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь неактивен",
        )

    return UserSchema(**user.__dict__)
