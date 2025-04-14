import asyncio
import logging
from typing import Any, Awaitable, Callable

import redis.asyncio as redis
from redis.asyncio.client import PubSub
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from core.redis.connection import RedisConnectionManager
from core.redis.serialization import deserialize_data, serialize_data

log = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], None | Awaitable[None]]


class RedisPubSubManager:
    """
    Manager for working with Redis Pub/Sub
    with template support and automatic reconnection.
    """

    def __init__(self, redis_url: str, reconnect_delay: float = 5.0) -> None:
        self.publisher = RedisConnectionManager(redis_url, reconnect_delay)
        self.subscriber = RedisConnectionManager(redis_url, reconnect_delay)
        self._stop_event = asyncio.Event()
        self._pubsub_client: PubSub | None = None
        self._listener_task: asyncio.Task | None = None
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._is_running = False
        self._connection_lock = asyncio.Lock()

    async def _get_redis_publisher(self) -> redis.Redis:
        """Returns the client for publishing (without decoding responses)."""
        return await self.publisher.get_client(decode_responses=False)

    async def _get_pubsub_client(self) -> PubSub:
        """Returns an active PubSub client, creating one if necessary."""
        async with self._connection_lock:
            if self._pubsub_client is None:
                log.info("Initializing Redis PubSub listener client...")
                try:
                    listener_redis = await self.subscriber.get_client(
                        decode_responses=True
                    )
                    self._pubsub_client = listener_redis.pubsub(
                        ignore_subscribe_messages=True
                    )
                    log.info("Redis PubSub listener client initialized.")
                except Exception as e:
                    log.exception("Error initializing PubSub listener: %s", e)
                    self._pubsub_client = None
                    raise

            if self._pubsub_client is None:
                log.error(
                    "PubSub client is unexpectedly None after initialization attempt."
                )
                raise ConnectionError("Failed to obtain PubSub client instance.")

            return self._pubsub_client

    async def subscribe(self, channel_or_pattern: str, handler: MessageHandler) -> None:
        """
        Subscribes to a channel or pattern and registers a handler.
        Automatically starts the listener on first subscription.
        """
        if not callable(handler):
            raise TypeError("Handler must be a callable function.")

        log.debug("Attempting to subscribe to '%s'.", channel_or_pattern)
        is_pattern = self._is_pattern(channel_or_pattern)

        await self._subscribe_to_channel(channel_or_pattern, is_pattern)

        if channel_or_pattern not in self._handlers:
            self._handlers[channel_or_pattern] = []
        self._handlers[channel_or_pattern].append(handler)

        if not self._listener_task:
            await self.start_listener()

    async def _subscribe_to_channel(self, channel: str, is_pattern: bool) -> None:
        """Subscribes to a channel or pattern."""
        if channel in self._handlers:
            return

        pubsub = await self._get_pubsub_client()
        self._handlers.setdefault(channel, [])

        try:
            if is_pattern:
                await pubsub.psubscribe(channel)
                log.info("Successfully psubscribed to pattern: %s", channel)
            else:
                await pubsub.subscribe(channel)
                log.info("Successfully subscribed to channel: %s", channel)
        except (RedisConnectionError, RedisTimeoutError, OSError) as e:
            log.error("Failed to subscribe to '%s': %s", channel, e)
            if channel in self._handlers:
                del self._handlers[channel]
            raise ConnectionError(f"Failed to subscribe to '{channel}'") from e

    def _is_pattern(self, channel_or_pattern: str) -> bool:
        """Determines whether a string is a subscription pattern."""
        return (
            "*" in channel_or_pattern
            or "?" in channel_or_pattern
            or ("[" in channel_or_pattern and "]" in channel_or_pattern)
        )

    async def unsubscribe(
        self, channel_or_pattern: str, handler: MessageHandler | None = None
    ) -> None:
        """
        Unsubscribes from a channel/pattern or removes a specific handler.
        """
        if channel_or_pattern not in self._handlers:
            log.warning(
                "Attempted to unsubscribe from '%s', but no subscription found.",
                channel_or_pattern,
            )
            return

        pubsub = self._pubsub_client
        is_pattern = self._is_pattern(channel_or_pattern)

        if handler:
            await self._remove_specific_handler(channel_or_pattern, handler)
        else:
            await self._remove_all_handlers(channel_or_pattern)

        should_unsubscribe = (
            channel_or_pattern not in self._handlers and pubsub is not None
        )
        if should_unsubscribe:
            await self._unsubscribe_from_channel(channel_or_pattern, is_pattern)

        if not self._handlers and self._is_running:
            await self.stop_listener()

    async def _remove_specific_handler(
        self, channel: str, handler: MessageHandler
    ) -> None:
        """Removes a specific handler from a channel."""
        if handler in self._handlers[channel]:
            self._handlers[channel].remove(handler)
            log.info(
                "Handler %s unregistered from '%s'.",
                getattr(handler, "__name__", str(handler)),
                channel,
            )
        else:
            log.warning(
                "Handler %s not found for '%s'.",
                getattr(handler, "__name__", str(handler)),
                channel,
            )

        if not self._handlers[channel]:
            del self._handlers[channel]

    async def _remove_all_handlers(self, channel: str) -> None:
        """Removes all handlers for a channel."""
        del self._handlers[channel]

    async def _unsubscribe_from_channel(self, channel: str, is_pattern: bool) -> None:
        """Unsubscribes from a channel or pattern."""
        if self._pubsub_client is None:
            return

        try:
            if is_pattern:
                await self._pubsub_client.punsubscribe(channel)
            else:
                await self._pubsub_client.unsubscribe(channel)
            log.info("Unsubscribed from '%s'.", channel)
        except (RedisConnectionError, RedisTimeoutError, OSError) as e:
            log.error("Error during unsubscribe from '%s': %s", channel, e)

    async def publish(self, channel: str, message: dict[str, Any]) -> int:
        """
        Publishes a serialized message to the specified Redis channel.
        Returns the number of clients that received the message.
        """
        if not channel:
            log.warning("Publish attempt with empty channel name.")
            return 0
        if not isinstance(message, dict):
            log.warning("Publish attempt with non-dict message type: %s", type(message))
            return 0

        try:
            redis_pub = await self._get_redis_publisher()
            message_bytes = serialize_data(message)

            receivers = await redis_pub.publish(channel, message_bytes)
            log.debug("Published message to '%s'. Receivers: %s.", channel, receivers)
            return receivers if isinstance(receivers, int) else 0
        except (RedisConnectionError, RedisTimeoutError, OSError) as e:
            log.error("Failed to publish message to channel '%s': %s", channel, e)
            self.publisher._redis_client = None
            return 0
        except Exception as e:
            log.exception("Unexpected error publishing to channel '%s': %s", channel, e)
            return 0

    async def _listener_loop(self) -> None:
        """Redis PubSub message listening loop."""
        log.info("Starting Redis PubSub listener loop...")

        try:
            pubsub = await self._get_pubsub_client()
            self._is_running = True

            async for message in pubsub.listen():
                if not self._is_running:
                    break

                if message.get("type") not in ("message", "pmessage"):
                    continue

                await self._process_message(message)

        except asyncio.CancelledError:
            log.info("Redis PubSub listener task cancelled.")
            raise
        except Exception as e:
            log.error("Error in Redis PubSub listener: %s", e)
        finally:
            self._is_running = False
            log.info("Redis PubSub listener loop exited.")

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Processes the received message and calls the appropriate handlers."""
        channel, pattern = self._extract_channel_info(message)
        target = pattern if pattern else channel

        data = await self._extract_message_data(message)
        if data is None:
            return

        if target in self._handlers:
            await self._call_handlers(target, data)

    def _extract_channel_info(self, message: dict[str, Any]) -> tuple[str, str | None]:
        """Extracts channel and pattern information from a message."""
        channel = message.get("channel", "")
        if isinstance(channel, bytes):
            channel = channel.decode("utf-8")

        pattern = message.get("pattern")
        if isinstance(pattern, bytes):
            pattern = pattern.decode("utf-8")

        return channel, pattern

    async def _extract_message_data(
        self, message: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extracts and deserializes message data."""
        data = message.get("data")
        if isinstance(data, bytes):
            try:
                return deserialize_data(data)
            except Exception as e:
                log.error("Failed to deserialize message data: %s", e)
                return None
        return data

    async def _call_handlers(self, target: str, data: dict[str, Any]) -> None:
        """Calls handlers for the specified channel/pattern."""
        for handler in self._handlers.get(target, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                log.error("Error in message handler for '%s': %s", target, e)

    async def start_listener(self) -> None:
        """Starts a Redis PubSub listener task."""
        if self._listener_task is None:
            log.info("Creating listener task...")
            self._listener_task = asyncio.create_task(self._listener_loop())

    async def stop_listener(self) -> None:
        """Stops the PubSub listener."""
        if self._listener_task:
            log.info("Stopping Redis PubSub listener...")
            self._stop_event.set()
            self._is_running = False

            try:
                self._listener_task.cancel()
                await asyncio.wait_for(asyncio.shield(self._listener_task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

            self._listener_task = None
            log.info("Redis PubSub listener stopped.")

    async def close(self) -> None:
        """Stops the listener and closes all connections."""
        log.info("Closing RedisPubSubManager...")
        await self.stop_listener()

        async with self._connection_lock:
            if self._pubsub_client:
                pubsub = self._pubsub_client
                self._pubsub_client = None
                try:
                    await pubsub.unsubscribe()
                    await pubsub.punsubscribe()
                    if pubsub.connection:
                        await pubsub.connection.disconnect()
                    log.info("PubSub client connection closed.")
                except Exception as e:
                    log.error("Error closing PubSub client: %s", e)

        await self.publisher.close()
        await self.subscriber.close()
        log.info("RedisPubSubManager closed.")

    @property
    def listener_task(self) -> asyncio.Task:
        return self._listener_task
