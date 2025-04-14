from typing import List

from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import User
from core.schemas.user_schemas import UserCreate, UserUpdate
from repositories.user_repo import create_user as repo_create_user
from repositories.user_repo import delete_user as repo_delete_user
from repositories.user_repo import (
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    get_users_by_username,
)
from repositories.user_repo import update_user as repo_update_user


class UserService:
    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int) -> User:
        """Getting user by ID"""
        user = await get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return user

    @staticmethod
    async def search_users_by_username(
        db: AsyncSession, username: str, current_user_id: int
    ) -> List[dict]:
        """Search users by name (excluding current user)"""
        users = await get_users_by_username(db, username)
        if not users:
            return []

        result = [
            {"id": user.id, "username": user.username, "avatar": user.avatar}
            for user in users
            if user.id != current_user_id
        ]
        return result

    @staticmethod
    async def create_user(db: AsyncSession, user_data: UserCreate) -> User:
        """Creating a new user"""
        existing_email = await get_user_by_email(db, str(user_data.email))
        if existing_email:
            raise HTTPException(
                status_code=400, detail="Пользователь с таким email уже существует"
            )

        existing_username = await get_user_by_username(db, user_data.username)
        if existing_username:
            raise HTTPException(
                status_code=400, detail="Пользователь с таким именем уже существует"
            )

        return await repo_create_user(db, user_data)

    @staticmethod
    async def update_user(
        db: AsyncSession, user_id: int, user_data: UserUpdate
    ) -> User:
        """Updating user data"""
        return await repo_update_user(db, user_id, user_data)

    @staticmethod
    async def delete_user(db: AsyncSession, user_id: int) -> Response:
        """Deleting a user"""
        return await repo_delete_user(db, user_id)
