import logging
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import desc, func, select, exists
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    aliased,
    selectinload,
)
from sqlalchemy.sql import and_

from core.models import Chat, ChatParticipant, Message, User

log = logging.getLogger(__name__)


async def get_private_chat_between_users(
    db: AsyncSession, user1_id: int, user2_id: int
) -> Chat | None:
    p1 = aliased(ChatParticipant)
    p2 = aliased(ChatParticipant)
    query = (
        select(Chat)
        .join(p1, p1.chat_id == Chat.id)  # type: ignore
        .join(p2, p2.chat_id == Chat.id)
        .where(Chat.is_group.is_(False), p1.user_id == user1_id, p2.user_id == user2_id)
    )
    result = await db.execute(query)
    return result.scalars().first()


async def create_private_chat(db: AsyncSession, user1_id: int, user2_id: int) -> Chat:
    """Creates a chat and participants within the current session"""
    new_chat = Chat(is_group=False)
    db.add(new_chat)
    await db.flush()

    participants = [
        ChatParticipant(chat_id=new_chat.id, user_id=user1_id),
        ChatParticipant(chat_id=new_chat.id, user_id=user2_id),
    ]
    db.add_all(participants)
    await db.flush()
    return new_chat


async def get_or_create_private_chat(
    db: AsyncSession, user1_id: int, user2_id: int
) -> Chat:
    """Gets or creates a private chat."""
    existing_chat = await get_private_chat_between_users(db, user1_id, user2_id)
    if existing_chat:
        return existing_chat
    return await create_private_chat(db, user1_id, user2_id)


async def delete_message(db: AsyncSession, message_id: int, user_id: int) -> bool:
    """Marks a message for deletion in the session, returns True if found."""
    query = select(Message).where(
        Message.id == message_id, Message.sender_id == user_id
    )
    result = await db.execute(query)
    message = result.scalar_one_or_none()
    if not message:
        return False

    await db.delete(message)
    await db.flush()
    return True


async def create_message(
    db: AsyncSession,
    content: str,
    sender_id: int,
    chat_id: int,
    reply_to_id: int | None = None,
) -> Message:
    """Creates a message and updates the last_message_at of the chat in the session."""
    message = Message(
        content=content,
        sender_id=sender_id,
        chat_id=chat_id,
        reply_to_id=reply_to_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(message)
    await db.flush()
    await db.refresh(message, attribute_names=["sender"])

    try:
        chat = await get_chat_by_id(db, chat_id)
        if chat:
            chat.last_message_at = message.created_at
            await db.flush()
    except Exception as e:
        log.error("Failed to update last_message_at for chat %d: %s", chat_id, e)

    return message


async def get_chat_by_id(db: AsyncSession, chat_id: int) -> Chat | None:
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    return result.scalar_one_or_none()


async def get_message_by_id(db: AsyncSession, message_id: int) -> Message | None:
    stmt = (
        select(Message)
        .where(Message.id == message_id)
        .options(selectinload(Message.sender))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_recent_chat_messages(
    db: AsyncSession, chat_id: int, limit: int = 100
) -> Sequence[Message]:
    """
    Retrieves the most recent messages for a given chat,
    eagerly loading the sender information.
    """
    try:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id)
            .options(selectinload(Message.sender))
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        messages = result.scalars().all()
        return messages[::-1]
    except SQLAlchemyError as e:
        log.error(
            "Database error fetching recent messages for chat %d: %s",
            chat_id,
            e,
            exc_info=True,
        )
        return []


async def get_user_chats_data(
    db: AsyncSession, user_id: int
) -> list[tuple[Chat, Message | None, User | None]]:
    """
    Fetches chats for a user, including the last message (with sender)
    and the chat partner (for private chats).
    """
    try:
        last_message_subquery = (
            select(Message.chat_id, func.max(Message.created_at).label("last_msg_time"))
            .group_by(Message.chat_id)
            .subquery("last_message_subquery")
        )

        user_chats_subquery = (
            select(ChatParticipant.chat_id)
            .where(ChatParticipant.user_id == user_id)
            .distinct()
            .subquery("user_chats_subquery")
        )

        stmt = (
            select(Chat, Message, User)
            .join(user_chats_subquery, Chat.id == user_chats_subquery.c.chat_id)
            .outerjoin(
                last_message_subquery, Chat.id == last_message_subquery.c.chat_id
            )
            .outerjoin(
                Message,
                and_(
                    Chat.id == Message.chat_id,
                    Message.created_at == last_message_subquery.c.last_msg_time,
                ),
            )
            .outerjoin(
                ChatParticipant,
                and_(
                    Chat.id == ChatParticipant.chat_id,
                    ChatParticipant.user_id != user_id,
                ),
            )
            .outerjoin(
                User, and_(User.id == ChatParticipant.user_id, Chat.is_group.is_(False))
            )
            .options(
                selectinload(Message.sender),
                selectinload(Chat.participants).selectinload(ChatParticipant.user),
            )
            .order_by(
                desc(last_message_subquery.c.last_msg_time), desc(Chat.created_at)
            )
            .group_by(Chat.id, Message.id, User.id)
        )
        result = await db.execute(stmt)
        raw_results = result.tuples().all()
        final_result = []
        processed_chat_ids = set()

        for chat_orm, last_message_orm, partner_user_orm in raw_results:
            if chat_orm.id not in processed_chat_ids:
                actual_partner = partner_user_orm if not chat_orm.is_group else None
                final_result.append((chat_orm, last_message_orm, actual_partner))
                processed_chat_ids.add(chat_orm.id)

        return final_result

    except SQLAlchemyError as e:
        log.error(
            "Database error fetching chats data for user %d: %s",
            user_id,
            e,
            exc_info=True,
        )
        return []


async def get_chat_partner(
    db: AsyncSession, chat_id: int, current_user_id: int
) -> User | None:
    """Finds the other participant in a private chat."""
    stmt = (
        select(User)
        .join(ChatParticipant, User.id == ChatParticipant.user_id)
        .where(
            ChatParticipant.chat_id == chat_id,
            ChatParticipant.user_id != current_user_id,
        )
        .limit(1)
    )
    try:
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        log.error(
            "Database error finding partner for chat %d, user %d: %s",
            chat_id,
            current_user_id,
            e,
            exc_info=True,
        )
        return None


async def check_user_in_chat(db: AsyncSession, user_id: int, chat_id: int) -> bool:
    """
    Checks if a user is a participant in a given chat using an optimized EXISTS query.
    """
    try:
        query = select(
            exists().where(
                and_(
                    ChatParticipant.user_id == user_id,
                    ChatParticipant.chat_id == chat_id,
                )
            )
        )
        result = await db.execute(query)
        is_participant = result.scalar()
        return bool(is_participant)
    except Exception as e:
        log.error(
            "Error checking user %d participation in chat %d: %s",
            user_id,
            chat_id,
            e,
            exc_info=True,
        )
        return False
