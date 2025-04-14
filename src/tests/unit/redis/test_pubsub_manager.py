import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from core.redis.pubsub_manager import RedisPubSubManager
from core.redis.serialization import serialize_data

pytestmark = pytest.mark.asyncio


class TestRedisPubSubConnection:
    """Тесты для логики подключения RedisPubSubManager."""

    async def test_get_redis_client_connects_once(
        self, pubsub_manager, patch_redis_from_url, mock_redis_client
    ):
        """Test that _get_redis_publisher creates a connection only once."""
        mock_redis_client.reset_mock()
        patch_redis_from_url.reset_mock()
        pubsub_manager.publisher._redis_client = None

        client1 = await pubsub_manager._get_redis_publisher()
        client2 = await pubsub_manager._get_redis_publisher()

        assert client1 is client2
        patch_redis_from_url.assert_called_once()
        client1.ping.assert_awaited()

    async def test_get_pubsub_client_connects_once(self, mock_redis_client):
        """Ensures that the PubSub client is created only once."""
        mock_pubsub = AsyncMock()
        mock_redis_client.pubsub = MagicMock(return_value=mock_pubsub)

        manager = RedisPubSubManager("redis://mockhost:6379")
        manager.subscriber._redis_client = mock_redis_client

        pubsub1 = await manager._get_pubsub_client()

        mock_redis_client.pubsub.reset_mock()

        pubsub2 = await manager._get_pubsub_client()

        assert pubsub1 is pubsub2
        mock_redis_client.pubsub.assert_not_called()

    async def test_get_redis_client_connection_error(
        self, pubsub_manager, patch_redis_from_url
    ):
        """Test connection error handling in _get_redis_publisher."""
        patch_redis_from_url.side_effect = RedisConnectionError("Failed")
        pubsub_manager.publisher._redis_client = None

        with pytest.raises(ConnectionError):
            await pubsub_manager._get_redis_publisher()

        assert pubsub_manager.publisher._redis_client is None


class TestRedisPubSubSubscription:
    """Tests for subscribe/unsubscribe functionality."""

    async def test_subscribe_to_channel_starts_listener(
        self, pubsub_manager, mock_pubsub
    ):
        """Test that subscribing to a channel launches a listener."""
        handler = AsyncMock()
        channel = "test_channel"
        pubsub_manager._pubsub_client = mock_pubsub
        pubsub_manager._listener_task = None
        pubsub_manager._is_running = False

        await pubsub_manager.subscribe(channel, handler)

        assert channel in pubsub_manager._handlers
        assert handler in pubsub_manager._handlers[channel]
        mock_pubsub.subscribe.assert_awaited_once_with(channel)
        assert pubsub_manager._listener_task is not None

        if pubsub_manager._listener_task:
            await pubsub_manager.stop_listener()

    async def test_subscribe_to_pattern_uses_psubscribe(
        self, pubsub_manager, mock_pubsub
    ):
        """Test that pattern subscription uses psubscribe."""
        handler = AsyncMock()
        pattern = "test_pattern:*"
        pubsub_manager._pubsub_client = mock_pubsub
        pubsub_manager._listener_task = None
        pubsub_manager._is_running = False

        await pubsub_manager.subscribe(pattern, handler)
        await asyncio.sleep(0)

        mock_pubsub.psubscribe.assert_awaited_once_with(pattern)
        mock_pubsub.subscribe.assert_not_awaited()
        assert handler in pubsub_manager._handlers[pattern]
        assert pubsub_manager._listener_task is not None

        if pubsub_manager._listener_task:
            await pubsub_manager.stop_listener()

    async def test_unsubscribe_handler_only_keeps_other_handlers(
        self, pubsub_manager, mock_pubsub
    ):
        """Test of unsubscribing a specific handler while keeping the rest."""
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        channel = "channel_multi"
        pubsub_manager._pubsub_client = mock_pubsub

        await pubsub_manager.subscribe(channel, handler1)
        await pubsub_manager.subscribe(channel, handler2)
        mock_pubsub.subscribe.reset_mock()
        mock_pubsub.unsubscribe.reset_mock()

        await pubsub_manager.unsubscribe(channel, handler1)

        assert handler1 not in pubsub_manager._handlers[channel]
        assert handler2 in pubsub_manager._handlers[channel]
        mock_pubsub.unsubscribe.assert_not_awaited()

    async def test_unsubscribe_last_handler_removes_channel(
        self, pubsub_manager, mock_pubsub
    ):
        """
        Test unsubscribing the last handler,
        which results in unsubscribing from the channel.
        """
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        channel = "channel_multi"
        pubsub_manager._pubsub_client = mock_pubsub

        await pubsub_manager.subscribe(channel, handler1)
        await pubsub_manager.subscribe(channel, handler2)
        mock_pubsub.subscribe.reset_mock()
        mock_pubsub.unsubscribe.reset_mock()

        await pubsub_manager.unsubscribe(channel, handler1)
        await pubsub_manager.unsubscribe(channel, handler2)

        assert channel not in pubsub_manager._handlers
        mock_pubsub.unsubscribe.assert_awaited_with(channel)


class TestRedisPubSubPublishing:
    """Tests for publication functionality."""

    async def test_publish_message_serializes_and_returns_receivers(
        self, pubsub_manager, mock_redis_client
    ):
        """Test of publishing a message with correct serialization."""
        pubsub_manager.publisher._redis_client = mock_redis_client
        channel = "publish_channel"
        message = {"data": "value", "id": 123}
        expected_bytes = serialize_data(message)

        receivers = await pubsub_manager.publish(channel, message)

        assert receivers == 1
        mock_redis_client.publish.assert_awaited_once_with(channel, expected_bytes)

    async def test_publish_handles_connection_error_gracefully(
        self, pubsub_manager, mock_redis_client
    ):
        """Test handling connection error when publishing."""
        pubsub_manager.publisher._redis_client = mock_redis_client
        mock_redis_client.publish.side_effect = RedisConnectionError("Pub failed")

        receivers = await pubsub_manager.publish("channel", {"data": 1})

        assert receivers == 0
        assert pubsub_manager.publisher._redis_client is None


class TestRedisPubSubListenerAndCleanup:
    """Tests for the listener loop and cleanup functionality."""

    async def test_listener_loop_processes_message_and_calls_handler(
        self, pubsub_manager, mock_pubsub
    ):
        """Test that listener correctly processes the message and calls handler."""
        channel = "data_channel"
        handler = AsyncMock()
        message_data = {"key": "value"}
        message_bytes = serialize_data(message_data)
        pubsub_message = {"type": "message", "channel": channel, "data": message_bytes}

        async def mock_listen_generator():
            yield pubsub_message
            await asyncio.sleep(0.01)
            pubsub_manager._is_running = False

        mock_pubsub.listen.return_value = mock_listen_generator()
        pubsub_manager._pubsub_client = mock_pubsub

        await pubsub_manager.subscribe(channel, handler)

        try:
            await asyncio.wait_for(pubsub_manager._listener_task, timeout=0.2)
        except asyncio.TimeoutError:
            pytest.fail("Listener task did not finish in time")
        except asyncio.CancelledError:
            pass

        handler.assert_awaited_once_with(message_data)

    async def test_close_properly_shuts_down_all_resources(
        self, pubsub_manager, mock_redis_client, mock_pubsub
    ):
        """Test that close correctly releases all resources."""
        publisher_mock = AsyncMock()
        subscriber_mock = AsyncMock()

        original_publisher = pubsub_manager.publisher
        original_subscriber = pubsub_manager.subscriber

        pubsub_manager.publisher = publisher_mock
        pubsub_manager.subscriber = subscriber_mock
        pubsub_manager._pubsub_client = mock_pubsub

        handler = AsyncMock()
        await pubsub_manager.subscribe("channel_to_close", handler)
        listener_task = pubsub_manager._listener_task
        assert listener_task is not None and not listener_task.done()

        await pubsub_manager.close()

        assert listener_task.cancelled()
        assert pubsub_manager._listener_task is None
        assert not pubsub_manager._is_running
        mock_pubsub.unsubscribe.assert_awaited()
        mock_pubsub.punsubscribe.assert_awaited()
        publisher_mock.close.assert_awaited_once()
        subscriber_mock.close.assert_awaited_once()

        pubsub_manager.publisher = original_publisher
        pubsub_manager.subscriber = original_subscriber
