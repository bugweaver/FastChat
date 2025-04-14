from datetime import timedelta

from fastapi import Response

from core.config import settings


def set_access_token_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=settings.cookie.access_token_key,
        value=access_token,
        httponly=settings.cookie.httponly,
        secure=settings.cookie.secure,
        samesite=settings.cookie.samesite,
        max_age=int(
            timedelta(
                minutes=settings.auth_jwt.access_token_expire_minutes
            ).total_seconds()
        ),
    )


def set_refresh_token_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.cookie.refresh_token_key,
        value=refresh_token,
        httponly=settings.cookie.httponly,
        secure=settings.cookie.secure,
        samesite=settings.cookie.samesite,
        max_age=int(
            timedelta(days=settings.auth_jwt.refresh_token_expire_days).total_seconds()
        ),
    )


def delete_access_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key="access_token", httponly=True, secure=False, samesite="lax"
    )


def delete_refresh_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key="refresh_token", httponly=True, secure=False, samesite="lax"
    )
