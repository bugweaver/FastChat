import logging

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.chat.services.redis_service import get_online_users, is_user_online
from core.models import Chat, Message, User
from core.schemas.chat_schemas import (
    ChatCreatedResponse,
    ChatInfoResponse,
    ChatPartnerInfo,
    ChatSummarySchema,
    LastMessageInfo,
    SenderInfo,
    UserChatsResponse,
)
from repositories import chat_repo, user_repo
from repositories.chat_repo import check_user_in_chat

log = logging.getLogger(__name__)


class ChatService:
    @staticmethod
    async def create_private_chat(
        db: AsyncSession, current_user_id: int, target_user_id: int
    ) -> ChatCreatedResponse:
        if current_user_id == target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create a chat with yourself.",
            )
        target_user = await user_repo.get_user_by_id(db, target_user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Target user not found"
            )
        try:
            chat = await chat_repo.get_or_create_private_chat(
                db, current_user_id, target_user_id
            )
            await db.commit()
            log.info(
                "Private chat %s created or retrieved for users %s and %s",
                chat.id,
                current_user_id,
                target_user_id,
            )
            return ChatCreatedResponse(chat_id=chat.id)
        except Exception as e:
            await db.rollback()
            log.error(
                "Error in create_private_chat for users %s, %s: %s",
                current_user_id,
                target_user_id,
                e,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create or retrieve chat.",
            ) from e

    @staticmethod
    async def get_chat_info(
        db: AsyncSession, chat_id: int, current_user_id: int, redis: Redis
    ) -> ChatInfoResponse:
        chat = await chat_repo.get_chat_by_id(db, chat_id)
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
            )

        is_participant = await check_user_in_chat(db, current_user_id, chat_id)
        if not is_participant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: User not in chat",
            )

        chat_partner_response = None
        if not chat.is_group:
            partner_user = await chat_repo.get_chat_partner(
                db, chat_id, current_user_id
            )
            if partner_user:
                is_online_status = await is_user_online(redis, partner_user.id)
                chat_partner_response = ChatPartnerInfo(
                    id=partner_user.id,
                    username=partner_user.username,
                    avatar=getattr(partner_user, "avatar", None),
                    is_online=is_online_status,
                )
            else:
                log.warning(
                    "Could not find chat partner for private chat %s and user %s",
                    chat_id,
                    current_user_id,
                )

        return ChatInfoResponse(
            id=chat.id,
            name=chat.name,
            is_group=chat.is_group,
            created_at=chat.created_at,
            chat_partner=chat_partner_response,
        )

    @staticmethod
    async def get_user_chats(
        db: AsyncSession, user_id: int, redis: Redis
    ) -> UserChatsResponse:
        try:
            chats_data: list[
                tuple[Chat, Message | None, User | None]
            ] = await chat_repo.get_user_chats_data(db, user_id)
            online_users_ids = await get_online_users(redis)
        except Exception as e:
            log.error(
                "Failed to fetch initial data for get_user_chats user %s: %s",
                user_id,
                e,
                exc_info=True,
            )
            return UserChatsResponse(chats=[])

        chat_summaries: list[ChatSummarySchema] = []
        for chat_orm, last_message_orm, partner_user_orm in chats_data:
            try:
                last_message_info = None
                sender_info_for_last = None

                if last_message_orm:
                    if last_message_orm.sender:
                        try:
                            sender_info_for_last = SenderInfo(
                                id=last_message_orm.sender.id,
                                username=last_message_orm.sender.username,
                                avatar=getattr(last_message_orm.sender, "avatar", None),
                            )
                        except Exception as e_sender:
                            log.warning(
                                "Could not create SenderInfo for sender %s: %s",
                                last_message_orm.sender_id,
                                e_sender,
                            )
                    try:
                        last_message_info = LastMessageInfo(
                            content=last_message_orm.content,
                            timestamp=last_message_orm.created_at,
                            sender=sender_info_for_last,
                        )
                    except Exception as e_last_msg:
                        log.warning(
                            "Could not create LastMessageInfo for message %s: %s",
                            last_message_orm.id,
                            e_last_msg,
                        )
                chat_avatar = None
                is_online = False

                if chat_orm.is_group:
                    chat_name = chat_orm.name if chat_orm.name else "Group Chat"
                    chat_avatar = getattr(chat_orm, "avatar", None)
                elif partner_user_orm:
                    chat_name = partner_user_orm.username
                    chat_avatar = getattr(partner_user_orm, "avatar", None)
                    is_online = partner_user_orm.id in online_users_ids
                else:
                    log.warning(
                        "Private chat %s fetched without a partner user for user %s.",
                        chat_orm.id,
                        user_id,
                    )
                    chat_name = "Private Chat"

                unread_count = 0

                chat_summary = ChatSummarySchema(
                    id=chat_orm.id,
                    name=chat_name,
                    is_group=chat_orm.is_group,
                    last_message=last_message_info,
                    unread_count=unread_count,
                    avatar=chat_avatar,
                    is_online=is_online,
                )
                chat_summaries.append(chat_summary)

            except Exception as e_loop:
                log.error(
                    "Failed to process chat summary for chat %s: %s",
                    chat_orm.id,
                    e_loop,
                    exc_info=True,
                )
                continue

        return UserChatsResponse(chats=chat_summaries)
