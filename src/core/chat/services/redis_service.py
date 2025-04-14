import logging
from typing import Any

from pydantic import BaseModel
from redis.asyncio import Redis

from core.redis.errors import handle_redis_errors
from core.redis.keys import (
    ONLINE_USERS_KEY,
    get_chat_deleted_messages_key,
    get_chat_messages_key,
    get_chat_unique_messages_key,
    get_user_connections_key,
)
from core.redis.serialization import deserialize_data, serialize_data
from core.schemas.redis_schemas import (
    RedisChatSettings,
    RedisConnectionSettings,
    RedisMessage,
    RedisMessageFilter,
)
from core.schemas.user_schemas import UserStatus

log = logging.getLogger(__name__)


@handle_redis_errors(default_return_value=0)
async def publish_message(
    redis: Redis, channel: str, message_payload: dict[str, Any] | BaseModel
) -> int:
    """Publish a message payload (dict or Pydantic model) to a Redis channel."""
    if not channel or not message_payload:
        log.warning("Invalid channel or empty message payload for publishing")
        return 0

    message_bytes = serialize_data(message_payload)
    return await redis.publish(channel, message_bytes)


@handle_redis_errors(default_return_value=False)
async def add_message_to_chat_history(
    redis: Redis,
    chat_id: int | str,
    message_data: dict[str, Any],
    settings: RedisChatSettings,
) -> bool:
    """
    Add a message to chat history in Redis.
    Validates message data using RedisMessage schema.
    Returns True if message was added, False otherwise.
    """
    try:
        message_data["chat_id"] = chat_id
        message = RedisMessage.model_validate(message_data)
    except Exception as e:
        log.warning("Invalid message data for chat %s: %s", chat_id, e)
        return False

    messages_key = get_chat_messages_key(chat_id)
    unique_key = get_chat_unique_messages_key(chat_id)
    deleted_key = get_chat_deleted_messages_key(chat_id)

    is_deleted = await redis.sismember(deleted_key, message.id)
    if is_deleted:
        log.info(
            "Message %s in chat %s is marked as deleted, skipping save.",
            message.id,
            chat_id,
        )
        return False

    was_added_to_unique = await redis.hsetnx(unique_key, message.id, "1")
    if not was_added_to_unique:
        log.info(
            "Message %s already in history for chat %s, skipping.", message.id, chat_id
        )
        return False

    message_bytes = serialize_data(message)

    async with redis.pipeline(transaction=True) as pipe:
        await pipe.lpush(messages_key, message_bytes)
        await pipe.ltrim(messages_key, 0, settings.max_history - 1)
        await pipe.expire(messages_key, settings.ttl)
        await pipe.expire(unique_key, settings.ttl)
        await pipe.expire(deleted_key, settings.deleted_ttl)
        await pipe.execute()

    log.debug("Message %s successfully added to chat %s history.", message.id, chat_id)
    return True


@handle_redis_errors(default_return_value=[])
async def get_chat_history(
    redis: Redis, filter_params: RedisMessageFilter, settings: RedisChatSettings
) -> list[dict[str, Any]]:
    """Get chat history, filtering out deleted messages."""
    chat_id = str(filter_params.chat_id)

    deleted_key = get_chat_deleted_messages_key(chat_id)
    messages_key = get_chat_messages_key(chat_id)

    async with redis.pipeline(transaction=True) as pipe:
        await pipe.smembers(deleted_key)
        await pipe.lrange(
            messages_key,
            filter_params.offset,
            filter_params.offset + filter_params.limit - 1,
        )
        results = await pipe.execute()

    deleted_ids_bytes: set[bytes] | None = results[0]
    messages_bytes_list: set[bytes] | None = results[1]

    deleted_ids: set[str] = (
        {uid.decode() for uid in deleted_ids_bytes} if deleted_ids_bytes else set()
    )

    processed_messages: list[dict[str, Any]] = []
    if messages_bytes_list:
        for msg_bytes in messages_bytes_list:
            msg: RedisMessage | None = deserialize_data(msg_bytes, model=RedisMessage)

            if msg is None or msg.id in deleted_ids:
                continue

            processed_messages.append(msg.model_dump())

            if len(processed_messages) >= filter_params.limit:
                break

    return processed_messages


@handle_redis_errors(default_return_value=False)
async def delete_message_from_redis(
    redis: Redis, chat_id: int | str, message_id: int | str, settings: RedisChatSettings
) -> bool:
    """
    Mark message as deleted and remove its content from the history list.
    Returns True if the message was marked/removed successfully or was already marked.
    """
    messages_key = get_chat_messages_key(chat_id)
    unique_key = get_chat_unique_messages_key(chat_id)
    deleted_key = get_chat_deleted_messages_key(chat_id)

    if await redis.sismember(deleted_key, message_id):
        log.info(
            "Message %s in chat %s is already marked as deleted.",
            message_id,
            chat_id,
        )
        await redis.hdel(unique_key, message_id)
        return True

    message_to_remove_bytes: bytes | None = None
    current_messages_bytes = await redis.lrange(messages_key, 0, -1)
    for msg_bytes in current_messages_bytes:
        msg_data = deserialize_data(msg_bytes)
        if msg_data and msg_data.get("id") == message_id:
            message_to_remove_bytes = msg_bytes
            break

    async with redis.pipeline(transaction=True) as pipe:
        await pipe.hdel(unique_key, message_id)
        await pipe.sadd(deleted_key, message_id)
        await pipe.expire(deleted_key, settings.deleted_ttl)
        if message_to_remove_bytes:
            await pipe.lrem(messages_key, 1, message_to_remove_bytes.decode("utf-8"))
        else:
            await pipe.exists(messages_key)

        results = await pipe.execute()

    sadd_result = results[1]
    lrem_removed_count = results[3] if message_to_remove_bytes else 0

    if sadd_result == 1:
        if lrem_removed_count > 0:
            log.info(
                "Message %s successfully marked as deleted"
                " and removed from list in chat %s.",
                message_id,
                chat_id,
            )
        else:
            log.info(
                "Message %s marked as deleted in chat %s."
                " Content not found/removed from list (possibly already trimmed).",
                message_id,
                chat_id,
            )
        return True
    elif sadd_result == 0:
        log.info(
            "Message %s was already marked as deleted (SADD returned 0) in chat %s.",
            message_id,
            chat_id,
        )
        if message_to_remove_bytes and lrem_removed_count == 0:
            log.warning("Message %s content was found but LREM failed?", message_id)
        return True
    else:
        log.error(
            "Unexpected result from pipeline for deleting message %s in chat %s.",
            message_id,
            chat_id,
        )
        return False


@handle_redis_errors(default_return_value=None)
async def set_online_status(
    redis: Redis, user_status: UserStatus, settings: RedisConnectionSettings
) -> None:
    """Set user online status, manage connection counter, and notify."""
    user_id = user_status.user_id
    connections_key = get_user_connections_key(user_id)
    status_channel = "user_status_changes"

    if user_status.status:
        async with redis.pipeline(transaction=True) as pipe:
            await pipe.incr(connections_key)
            await pipe.expire(connections_key, settings.connection_ttl)
            results = await pipe.execute()

        connections_count = results[0]

        if connections_count == 1:
            added_to_online = await redis.sadd(ONLINE_USERS_KEY, user_id)
            if added_to_online:
                log.info("User %s connected and is now online.", user_id)
                await publish_message(redis, status_channel, user_status)
        else:
            log.debug(
                "User %s added connection (total: %d).", user_id, connections_count
            )

    else:
        current_count_bytes = await redis.get(connections_key)
        if current_count_bytes is None:
            log.debug("User %s disconnect event, but no active counter.", user_id)
            removed = await redis.srem(ONLINE_USERS_KEY, user_id)
            if removed:
                log.info(
                    "User %s removed from online set due to missing counter.", user_id
                )
                await publish_message(redis, status_channel, user_status)
            return

        try:
            current_count = int(current_count_bytes)
        except (ValueError, TypeError):
            log.warning(
                "Invalid connection count for user %s: %s. Resetting state.",
                user_id,
                current_count_bytes,
            )
            current_count = 0

        if current_count <= 1:
            async with redis.pipeline(transaction=True) as pipe:
                await pipe.delete(connections_key)
                await pipe.srem(ONLINE_USERS_KEY, user_id)
                results = await pipe.execute()
            removed = results[1] > 0
            if removed or current_count > 0:
                log.info(
                    "User %s disconnected (last connection) and is now offline.",
                    user_id,
                )
                await publish_message(redis, status_channel, user_status)
            else:
                log.debug("User %s disconnect event, but was already offline.", user_id)
        else:
            await redis.decr(connections_key)
            log.debug(
                "User %s disconnected, remaining connections: %d.",
                user_id,
                current_count - 1,
            )


@handle_redis_errors(default_return_value=False)
async def is_user_online(redis: Redis, user_id: int | str) -> bool:
    """Check user's online status using the online set."""
    result = await redis.sismember(ONLINE_USERS_KEY, user_id)
    return bool(result)


@handle_redis_errors(default_return_value=set())
async def get_online_users(redis: Redis) -> set[str]:
    """Get set of online user IDs (as strings)."""
    result_bytes: set[bytes] | None = await redis.smembers(ONLINE_USERS_KEY)
    return {uid.decode() for uid in result_bytes} if result_bytes else set()


@handle_redis_errors(default_return_value=False)
async def check_redis_health(redis: Redis) -> bool:
    """Check Redis availability using PING."""
    log.debug("Pinging Redis...")
    result = await redis.ping()
    log.debug("Redis PING result: %s", result)
    return result
