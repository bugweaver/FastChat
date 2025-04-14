from typing import AsyncGenerator

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.models import Base, Chat, User
from tests.factories.chat_factory import ChatFactory, MessageFactory
from tests.factories.user_factory import UserFactory

TEST_DATABASE_URL: str = "sqlite+aiosqlite:///:memory:"
engine_test = create_async_engine(TEST_DATABASE_URL, echo=False)

async_session_maker = async_sessionmaker(
    engine_test, class_=AsyncSession, expire_on_commit=False
)


async def override_get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Creates a new session for each request in FastAPI tests."""
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_test_database() -> AsyncGenerator[None, None]:
    """Creates a test database before all tests and deletes it after."""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="session")
async def db_session_for_fixtures() -> AsyncGenerator[AsyncSession, None]:
    """Provides a session for creating session fixtures (with commit)."""
    async with async_session_maker() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def db_session_test_func() -> AsyncGenerator[AsyncSession, None]:
    """Provides a session for one test with automatic rollback."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.rollback()
        except Exception as e:
            await session.rollback()
            raise e


@pytest_asyncio.fixture(scope="session")
async def test_user(db_session_for_fixtures: AsyncSession) -> User:
    """Creates standard test user."""
    session = db_session_for_fixtures
    unique_username: str = "testuser"
    unique_email: str = "testuser@example.com"

    existing_user = await session.scalar(
        select(User).filter_by(username=unique_username)
    )
    if existing_user:
        return existing_user

    user = await UserFactory.create_async(
        session=session, email=unique_email, username=unique_username
    )
    await session.commit()
    return user


@pytest_asyncio.fixture(scope="session")
async def inactive_test_user(db_session_for_fixtures: AsyncSession) -> User:
    """Creates inactive test user."""
    session = db_session_for_fixtures
    unique_username: str = "inactive_user"
    unique_email: str = "inactive@example.com"

    existing_user = await session.scalar(
        select(User).filter_by(username=unique_username)
    )
    if existing_user:
        return existing_user

    user = await UserFactory.create_async(
        session=session, email=unique_email, username=unique_username, is_active=False
    )
    await session.commit()
    return user


@pytest_asyncio.fixture(scope="function")
async def partner_user(db_session_test_func: AsyncSession) -> User:
    """Creates partner test user."""
    user = await UserFactory.create_async(session=db_session_test_func)
    return user


@pytest_asyncio.fixture(scope="function")
async def existing_chat(
    db_session_test_func: AsyncSession, test_user: User, partner_user: User
) -> Chat:
    """Creates a private chat"""
    chat = await ChatFactory.create_private_chat(
        session=db_session_test_func, user1=test_user, user2=partner_user
    )
    return chat


@pytest_asyncio.fixture(scope="function")
async def message_id_in_chat(
    db_session_test_func: AsyncSession, existing_chat: Chat, test_user: User
) -> int:
    """Creates a message and returns its ID."""
    message = await MessageFactory.create_in_chat(
        session=db_session_test_func,
        chat=existing_chat,
        sender=test_user,
        content="Test message for deletion",
    )
    return message.id
