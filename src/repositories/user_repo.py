from typing import Sequence

from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.utils.password_utils import hash_password
from core.models import User
from core.schemas.user_schemas import UserCreate, UserUpdate


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """Get user by ID."""
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """Get user by username."""
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    return result.scalars().first()


async def get_users_by_username(
    db: AsyncSession, username: str
) -> Sequence[User] | None:
    """
    Search for users by username (including partial matches).
    """
    query = select(User).where(User.username.ilike(f"%{username}%"))
    result = await db.execute(query)
    return result.scalars().all()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Get user by email."""
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    return result.scalars().first()


async def get_user_by_token_sub(payload: dict, db: AsyncSession) -> User:
    """Getting user by subject from token"""
    username: str | None = payload.get("sub")
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный токен (пользователь не найден)",
        )

    return user


async def get_users(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> Sequence[User]:
    """Get users with pagination."""
    query = select(User).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


async def create_user(db: AsyncSession, user_create: UserCreate) -> User:
    """Create new user with password hashing."""
    try:
        hashed_password = hash_password(user_create.password)

        db_user = User(
            email=str(user_create.email),
            username=user_create.username,
            password=hashed_password.decode("utf-8"),
            first_name=user_create.first_name,
            last_name=user_create.last_name,
        )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}") from e


async def update_user(
    db: AsyncSession, user_id: int, user_update: UserUpdate
) -> User | None:
    """Update user by ID."""
    db_user = await get_user_by_id(db, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    for key, value in user_update.model_dump(exclude_unset=True).items():
        setattr(db_user, key, value)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


async def delete_user(db: AsyncSession, user_id: int) -> Response:
    """Delete user by ID."""
    db_user = await get_user_by_id(db, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(db_user)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
