from datetime import datetime
from typing import Any

import factory

from core.models import Chat, ChatParticipant, Message

from .base import AsyncSQLAlchemyModelFactory


class ChatFactory(AsyncSQLAlchemyModelFactory):
    """Factory for creating chat instances."""

    class Meta:
        model = Chat
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    is_group = False
    last_message_at = factory.LazyFunction(datetime.now)

    @classmethod
    async def build_async(cls, **kwargs):
        """Creates a chat instance without saving it to the database."""
        return cls._meta.model(**kwargs)

    @classmethod
    async def create_private_chat(cls, session, user1, user2, **kwargs):
        """Creates a private chat between two users."""
        chat = await cls.create_async(session=session, **kwargs)

        link1 = ChatParticipant(user_id=user1.id, chat_id=chat.id)
        link2 = ChatParticipant(user_id=user2.id, chat_id=chat.id)
        session.add_all([link1, link2])
        await session.flush()
        await session.refresh(chat, attribute_names=["participants"])

        chat.partner_user_in_test = user2

        return chat


class ChatParticipantFactory(AsyncSQLAlchemyModelFactory):
    """Factory for creating connections between users and chats."""

    class Meta:
        model = ChatParticipant
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    @classmethod
    async def build_async(cls, **kwargs):
        """Creates a chat participant instance without saving it to the database."""
        return cls._meta.model(**kwargs)


class MessageFactory(AsyncSQLAlchemyModelFactory):
    """Factory for creating messages."""

    class Meta:
        model = Message
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    content = factory.Faker("text", max_nb_chars=200)
    created_at = factory.LazyFunction(datetime.now)

    @classmethod
    async def build_async(cls, **kwargs):
        """Creates a message instance without saving it to the database."""
        return cls._meta.model(**kwargs)

    @classmethod
    async def create_in_chat(cls, session, chat, sender, **kwargs: dict[str, Any]):
        """
        Creates a message in the specified
        chat from the specified sender.
        """
        message = await cls.create_async(
            session=session, chat_id=chat.id, sender_id=sender.id, **kwargs
        )
        chat.last_message_at = message.created_at
        await session.flush()

        return message
