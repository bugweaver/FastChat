import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from core.config import settings


def encode_jwt(
    payload: dict,
    private_key: str = settings.auth_jwt.private_key_path.read_text(),
    algorithm: str = settings.auth_jwt.algorithm,
    expire_timedelta: timedelta | None = None,
    expire_minutes: int = settings.auth_jwt.access_token_expire_minutes,
) -> str:
    to_encode = payload.copy()
    now = datetime.now(timezone.utc)
    if expire_timedelta:
        expire = now + expire_timedelta
    else:
        expire = now + timedelta(minutes=expire_minutes)
    to_encode.update(exp=expire, iat=now, jti=str(uuid.uuid4()))
    return jwt.encode(to_encode, private_key, algorithm=algorithm)


def decode_jwt(
    token: str | bytes,
    public_key: str = settings.auth_jwt.public_key_path.read_text(),
    algorithm: str = settings.auth_jwt.algorithm,
) -> dict[str, Any]:
    return jwt.decode(token, public_key, algorithms=[algorithm])


# def decode_jwt_ws(
#     token: str,
#     public_key: str = settings.auth_jwt.public_key_path.read_text(),
#     algorithm: str = settings.auth_jwt.algorithm,
# ):
#     try:
#         return jwt.decode(token, public_key, algorithms=[algorithm])
#     except jwt.ExpiredSignatureError:
#         raise ValueError("Токен просрочен")
#     except jwt.JWTError:
#         raise ValueError("Невалидный токен")
