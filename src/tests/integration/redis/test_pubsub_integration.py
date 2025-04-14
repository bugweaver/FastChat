import asyncio
import json
from typing import Any

import pytest


@pytest.mark.asyncio
class TestPubSubManagerWithFakeRedis:
    """
    Integration tests for RedisPubSubManager with FakeAsyncRedis.
    """

    async def test_publish_and_receive_message(self, real_pubsub_manager) -> None:
        """Testing the full cycle of publishing and receiving messages via pub/sub."""
        channel = "test_integration_channel"
        message_received = asyncio.Event()
        received_data = {}

        async def message_handler(data: dict[str, Any] | str) -> None:
            try:
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        pytest.fail(f"Invalid message received: {data}")

                received_data.update(data)
                message_received.set()
            except Exception as e:
                pytest.fail(f"Error in message handler: {e}")

        await real_pubsub_manager.subscribe(channel, message_handler)

        if not real_pubsub_manager._is_running:
            await real_pubsub_manager.start_listener()
            await asyncio.sleep(0.1)

        try:
            test_message = {"key": "value", "test": 123}
            await real_pubsub_manager.publish(channel, test_message)

            await asyncio.sleep(0.1)

            try:
                await asyncio.wait_for(message_received.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                subscription_state = (
                    await real_pubsub_manager._pubsub_client.get_message()
                )
                pytest.fail(
                    "Message not received within timeout."
                    f" Subscription status: {subscription_state}"
                )

            assert received_data == test_message
        finally:
            await real_pubsub_manager.stop_listener()
            await real_pubsub_manager.unsubscribe(channel)
            await asyncio.sleep(0.1)

    async def test_pattern_subscription_receives_messages_from_multiple_channels(
        self, real_pubsub_manager
    ):
        """Test of receiving messages according to a pattern from several channels."""
        pattern = "test:*"
        channels = ["test:1", "test:2", "test:3"]
        received_messages = []
        message_event = asyncio.Event()

        async def pattern_handler(data: dict[str, Any] | str) -> None:
            try:
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        pytest.fail(f"Invalid message received: {data}")

                received_messages.append(data)
                if len(received_messages) >= len(channels):
                    message_event.set()
            except Exception as e:
                pytest.fail(f"Error in pattern handler: {e}")

        await real_pubsub_manager.subscribe(pattern, pattern_handler)

        if not real_pubsub_manager._is_running:
            await real_pubsub_manager.start_listener()
            await asyncio.sleep(0.1)

        try:
            for i, channel in enumerate(channels):
                await real_pubsub_manager.publish(
                    channel, {"channel": channel, "index": i}
                )
                await asyncio.sleep(0.05)

            await asyncio.sleep(0.1)
            try:
                await asyncio.wait_for(message_event.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                subscription_state = (
                    await real_pubsub_manager._pubsub_client.get_message()
                )
                pytest.fail(
                    f"Received {len(received_messages)} of {len(channels)} messages."
                    f" Subscription state: {subscription_state}"
                )

            assert len(received_messages) == len(channels), (
                f"Received {len(received_messages)} of {len(channels)} messages"
            )

            for i, channel in enumerate(channels):
                found = False
                for msg in received_messages:
                    if msg.get("channel") == channel and msg.get("index") == i:
                        found = True
                        break
                assert found, f"Message for channel {channel} with index {i} not found"
        finally:
            await real_pubsub_manager.stop_listener()
            await real_pubsub_manager.unsubscribe(pattern)
            await asyncio.sleep(0.1)
