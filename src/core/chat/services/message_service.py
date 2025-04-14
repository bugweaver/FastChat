import logging
from datetime import datetime, timezone
from typing import Any, Sequence

import pydantic
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.chat_repo import check_user_in_chat

from core.chat.services.redis_service import (
    add_message_to_chat_history,
    delete_message_from_redis,
    get_chat_history,
    publish_message,
)
from core.models import Message
from core.redis.keys import get_chat_message_channel, get_message_deleted_channel
from core.schemas.chat_schemas import (
    MessageSchema,
    MessagesListResponse,
)
from core.schemas.redis_schemas import (
    RedisChatSettings,
    RedisMessage,
    RedisMessageFilter,
)
from repositories import chat_repo

DEFAULT_CHAT_SETTINGS = RedisChatSettings()
log = logging.getLogger(__name__)


class MessageService:
    @staticmethod
    async def create_message(
        db: AsyncSession,
        content: str,
        sender_id: int,
        chat_id: int,
        reply_to_id: int | None = None,
        redis: Redis | None = None,
    ) -> dict[str, Any]:
        """Creates a message, saves to DB, updates cache, and publishes via Pub/Sub."""
        try:
            chat = await chat_repo.get_chat_by_id(db, chat_id)
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
                )

            is_participant = await check_user_in_chat(db, sender_id, chat_id)
            if not is_participant:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Sender is not a participant of this chat",
                )

            if reply_to_id:
                reply_message = await chat_repo.get_message_by_id(db, reply_to_id)
                if not reply_message:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Message to reply to not found",
                    )
                if reply_message.chat_id != chat_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot reply to a message from a different chat",
                    )

            message_orm = await chat_repo.create_message(
                db, content, sender_id, chat_id, reply_to_id
            )
            await db.flush()
            await db.refresh(message_orm, attribute_names=["sender"])

            if not message_orm.sender:
                log.error(
                    "Failed to load sender for created message %s", message_orm.id
                )
                raise HTTPException(
                    status_code=500, detail="Failed processing created message"
                )

            await db.commit()
            log.info(
                "Message %s created by user %s in chat %s",
                message_orm.id,
                sender_id,
                chat_id,
            )

            message_schema = MessageSchema.model_validate(message_orm)
            message_data = message_schema.model_dump(mode="json")

            if redis:
                try:
                    await add_message_to_chat_history(
                        redis, chat_id, message_data, DEFAULT_CHAT_SETTINGS
                    )
                    log.debug(
                        "Added message %s to Redis cache for chat %s",
                        message_orm.id,
                        chat_id,
                    )
                except Exception as e_redis:
                    log.warning(
                        "Failed to add message %s to Redis cache: %s",
                        message_orm.id,
                        e_redis,
                    )

            if redis:
                try:
                    channel = get_chat_message_channel(chat_id)
                    payload = {"type": "new_message", "data": message_data}
                    await publish_message(redis, channel, payload)
                    log.debug(
                        "Published new message %s to channel %s",
                        message_orm.id,
                        channel,
                    )
                except Exception as e_pubsub:
                    log.warning(
                        "Failed to publish new message %s via Pub/Sub: %s",
                        message_orm.id,
                        e_pubsub,
                    )

            return message_data

        except HTTPException as http_exc:
            await db.rollback()
            raise http_exc
        except Exception as e:
            await db.rollback()
            log.exception(
                "Error creating message by user %s in chat %s: %s",
                sender_id,
                chat_id,
                e,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while creating the message.",
            ) from e

    @staticmethod
    async def delete_message(
        db: AsyncSession,
        message_id: int,
        current_user_id: int,
        redis: Redis,
    ) -> None:
        """
        Deletes message from DB, updates cache,
        and publishes deletion via Pub/Sub.
        """
        try:
            message_orm = await chat_repo.get_message_by_id(db, message_id)
            if not message_orm:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
                )
            if message_orm.sender_id != current_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User cannot delete this message",
                )

            chat_id_for_redis = message_orm.chat_id

            deleted_in_db = await chat_repo.delete_message(
                db, message_id, current_user_id
            )
            if not deleted_in_db:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete message from database.",
                )

            await db.commit()
            log.info(
                "Message %s deleted from DB by user %s", message_id, current_user_id
            )

            try:
                await delete_message_from_redis(
                    redis, chat_id_for_redis, message_id, DEFAULT_CHAT_SETTINGS
                )
                log.debug(
                    "Marked message %s as deleted in Redis cache for chat %s",
                    message_id,
                    chat_id_for_redis,
                )
            except Exception as e_redis:
                log.error(
                    "Error deleting message %s from Redis cache: %s",
                    message_id,
                    e_redis,
                )

            try:
                channel = get_message_deleted_channel(chat_id_for_redis)
                payload = {
                    "type": "message_deleted",
                    "message_id": message_id,
                    "chat_id": chat_id_for_redis,
                    "deleted_at": datetime.now(timezone.utc).isoformat(),
                }
                await publish_message(redis, channel, payload)
                log.debug(
                    "Published message deletion event for %s to channel %s",
                    message_id,
                    channel,
                )
            except Exception as e_pubsub:
                log.warning(
                    "Failed to publish message deletion %s via Pub/Sub: %s",
                    message_id,
                    e_pubsub,
                )

        except HTTPException as http_exc:
            await db.rollback()
            raise http_exc
        except Exception as e:
            await db.rollback()
            log.exception(
                "Error deleting message %s by user %s: %s",
                message_id,
                current_user_id,
                e,
            )
            raise HTTPException(
                status_code=500, detail="An error occurred while deleting the message."
            ) from e

    @staticmethod
    async def get_chat_messages(
        db: AsyncSession, chat_id: int, user_id: int, redis: Redis
    ) -> MessagesListResponse:
        """Retrieves chat messages, prioritizing cache, then DB."""
        try:
            chat = await chat_repo.get_chat_by_id(db, chat_id)
            if not chat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
                )

            is_participant = await check_user_in_chat(db, user_id, chat_id)
            if not is_participant:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not have access to this chat's messages",
                )
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e_initial:
            log.exception(
                "Error during initial checks for get_chat_messages "
                "chat %s, user %s: %s",
                chat_id,
                user_id,
                e_initial,
            )
            raise HTTPException(
                status_code=500, detail="Error checking chat access"
            ) from e_initial

        messages_from_cache: list[MessageSchema] = []
        cache_read_error = False
        try:
            filter_params = RedisMessageFilter(
                chat_id=chat_id, limit=DEFAULT_CHAT_SETTINGS.max_history
            )
            cached_messages_dicts = await get_chat_history(
                redis, filter_params, DEFAULT_CHAT_SETTINGS
            )

            if cached_messages_dicts:
                log.debug(
                    "Cache hit for chat %s. Found %s raw messages.",
                    chat_id,
                    len(cached_messages_dicts),
                )
                valid_cached_messages = []
                for msg_dict in cached_messages_dicts:
                    try:
                        msg_schema = MessageSchema.model_validate(msg_dict)
                        valid_cached_messages.append(msg_schema)
                    except pydantic.ValidationError as e_validate:
                        log.warning(
                            "Invalid message data in Redis cache"
                            " for chat %s, msg_id=%s: %s",
                            chat_id,
                            msg_dict.get("id"),
                            e_validate,
                        )
                if valid_cached_messages:
                    messages_from_cache = sorted(
                        valid_cached_messages, key=lambda m: m.created_at
                    )
                    log.debug(
                        "Successfully validated %s messages from cache for chat %s.",
                        len(messages_from_cache),
                        chat_id,
                    )

        except Exception as e_redis:
            log.error(
                "Failed to get messages from Redis cache for chat %s: %s",
                chat_id,
                e_redis,
                exc_info=True,
            )
            cache_read_error = True

        if messages_from_cache and not cache_read_error:
            return MessagesListResponse(messages=messages_from_cache)

        log.info("Cache miss or error for chat %s. Fetching from database.", chat_id)
        try:
            db_orm_messages: Sequence[
                Message
            ] = await chat_repo.get_recent_chat_messages(
                db, chat_id, limit=DEFAULT_CHAT_SETTINGS.max_history
            )

            messages_for_response: list[MessageSchema] = []
            messages_to_cache: list[dict[str, Any]] = []

            for msg_orm in db_orm_messages:
                try:
                    message_schema = MessageSchema.model_validate(msg_orm)
                    messages_for_response.append(message_schema)
                    messages_to_cache.append(message_schema.model_dump(mode="json"))
                except pydantic.ValidationError as e_validate:
                    log.error(
                        "Failed to validate message %s from DB for chat %s: %s",
                        msg_orm.id,
                        chat_id,
                        e_validate,
                    )

            if messages_to_cache:
                log.debug(
                    "Attempting to populate Redis cache for chat %s with %s messages.",
                    chat_id,
                    len(messages_to_cache),
                )
                cache_populated = True
                for msg_data in reversed(messages_to_cache):
                    try:
                        RedisMessage.model_validate(msg_data)
                        await add_message_to_chat_history(
                            redis, chat_id, msg_data, DEFAULT_CHAT_SETTINGS
                        )
                    except Exception as e_redis_add:
                        cache_populated = False
                        log.warning(
                            "Failed to add message %s to Redis cache for chat %s: %s",
                            msg_data.get("id"),
                            chat_id,
                            e_redis_add,
                        )
                    except pydantic.ValidationError as e:
                        log.error("Invalid message data: %s", e)
                if cache_populated:
                    log.info("Successfully populated Redis cache for chat %s.", chat_id)

            return MessagesListResponse(messages=messages_for_response)

        except Exception as e_db:
            log.exception(
                "Failed to get messages from DB for chat %s: %s", chat_id, e_db
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An error occurred while retrieving messages from the database.",
            ) from e_db
