import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from repositories.user_repo import get_user_by_username


def encode_jwt(
    payload: dict,
    private_key: str = settings.auth_jwt.private_key_path.read_text(),
    algorithm: str = settings.auth_jwt.algorithm,
    expire_minutes: int | None = None,
    expire_timedelta: timedelta | None = None,
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


async def verify_token_ws(token: str, db: AsyncSession) -> int | None:
    try:
        payload = decode_jwt(token)
        username = payload.get("sub")
        if not username:
            return None
        user = await get_user_by_username(db, username)
        return user.id if user else None
    except Exception:
        return None
