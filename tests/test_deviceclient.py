"""Tests for the device client."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import nullcontext
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from aiomqtt import Client, Message

from letpot.deviceclient import LetPotDeviceClient
from letpot.exceptions import LetPotFeatureException
from letpot.models import TemperatureUnit

from . import AUTHENTICATION, DEVICE_STATUS_GARDEN


class MockMessagesIterator:
    """A simple iterator which waits for messages in a queue."""

    def __init__(self, queue=None):
        self.queue = queue or asyncio.Queue()
        self.next_call_count = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.next_call_count += 1
        item = await self.queue.get()
        if item is StopAsyncIteration:
            raise StopAsyncIteration
        return item


@pytest.fixture
async def device_client() -> LetPotDeviceClient:
    """Fixture for device client."""
    return LetPotDeviceClient(AUTHENTICATION)


@pytest_asyncio.fixture()
async def mock_aiomqtt() -> AsyncGenerator[MagicMock]:
    """Mock a aiomqtt.Client."""

    with patch("letpot.deviceclient.aiomqtt.Client") as mock_client_class:
        client = MagicMock(spec=Client)
        client.messages = MockMessagesIterator()

        mock_client_class.return_value.__aenter__.return_value = client

        yield mock_client_class


async def test_subscribe_setup_shutdown(
    device_client: LetPotDeviceClient, mock_aiomqtt: MagicMock
) -> None:
    """Test subscribing/unsubscribing creates a client and shuts it down."""
    device = "LPH21ABCD"

    # Test subscribing sets up a client + subscription
    await device_client.subscribe(device, lambda _: None)
    assert device_client._client is not None
    assert (
        device_client._connected is not None
        and device_client._connected.result() is True
    )

    # Test unsubscribing cancels the subscription + shuts down client
    await device_client.unsubscribe(device)
    assert device_client._client is None
    assert device_client._client_task.cancelled()


async def test_subscribe_multiple(
    device_client: LetPotDeviceClient, mock_aiomqtt: MagicMock
) -> None:
    """Test multiple subscriptions use one client and shuts down only when all are done."""
    device1 = "LPH21ABCD"
    device2 = "LPH21DEFG"

    await device_client.subscribe(device1, lambda _: None)
    await device_client.subscribe(device2, lambda _: None)
    assert device_client._client is not None
    assert device_client._client.subscribe.call_count == 2  # type: ignore[attr-defined]
    # Check number of calls on message queue. Nothing is sent so 1 call = 1 client.
    assert device_client._client.messages.next_call_count == 1  # type: ignore[attr-defined]

    await device_client.unsubscribe(device1)
    assert device_client._client.unsubscribe.call_count == 1  # type: ignore[attr-defined]
    assert device_client._client is not None

    await device_client.unsubscribe(device2)
    assert device_client._client is None
    assert device_client._client_task.cancelled()


async def test_subscribe_callback(
    device_client: LetPotDeviceClient, mock_aiomqtt: MagicMock
) -> None:
    """Test subscription receiving a status update passing it to the callback."""
    device1 = "LPH21ABCD"
    device2 = "LPH21DEFG"
    callback1 = MagicMock()
    callback2 = MagicMock()

    await device_client.subscribe(device1, callback1)
    await device_client.subscribe(device2, callback2)

    assert device_client._client is not None
    device_client._handle_message(
        Message(
            topic=f"{device1}/data",
            payload=b"4d0001126201000101010100000f000f1e01f4000000",
            qos=0,
            retain=False,
            mid=1,
            properties=None,
        )
    )
    # Only device1 should be called
    assert callback1.call_count == 1
    assert not callback2.called

    device_client._handle_message(
        Message(
            topic=f"{device2}/data",
            payload=b"4d0001126201000101010100000f000f1e01f4000000",
            qos=0,
            retain=False,
            mid=1,
            properties=None,
        )
    )
    # Only device2 should be called, device1 should be same as before
    assert callback1.call_count == 1
    assert callback2.call_count == 1

    # Shutdown gracefully
    await device_client.unsubscribe(device1)
    await device_client.unsubscribe(device2)


def test_clients_do_not_share_internal_state() -> None:
    """Test that mutable connection state is scoped per client instance."""
    client1 = LetPotDeviceClient(AUTHENTICATION)
    client2 = LetPotDeviceClient(AUTHENTICATION)

    callback = MagicMock()
    client1._topics.append("LPH21ABCD/data")
    client1._device_callbacks["LPH21ABCD"] = callback

    assert client2._topics == []
    assert client2._device_callbacks == {}


async def test_reconnect_reestablishes_connection(
    device_client: LetPotDeviceClient, mock_aiomqtt: MagicMock
) -> None:
    """Test that reconnect cancels the old connection and creates a new one."""
    device = "LPH21ABCD"

    await device_client.subscribe(device, lambda _: None)
    assert device_client._client is not None
    old_task = device_client._client_task

    await device_client.reconnect()

    # Old task should be cancelled
    assert old_task.cancelled()
    # New connection should be established
    assert device_client._client is not None
    assert device_client._client_task is not old_task
    # Topics should still be registered
    assert f"{device}/data" in device_client._topics

    await device_client.unsubscribe(device)


async def test_reconnect_noop_when_no_topics(
    device_client: LetPotDeviceClient, mock_aiomqtt: MagicMock
) -> None:
    """Test that reconnect does nothing when there are no active subscriptions."""
    await device_client.reconnect()
    assert device_client._client is None
    assert device_client._client_task is None


async def test_connect_retries_on_non_mqtt_exception(
    device_client: LetPotDeviceClient,
) -> None:
    """Test that _connect retries on non-MqttError exceptions instead of crashing."""
    attempt_count = 0
    retried = asyncio.Event()
    _real_sleep = asyncio.sleep

    with patch("letpot.deviceclient.aiomqtt.Client") as mock_client_class:
        # side_effect on the AsyncMock __aenter__ to track and raise
        def track_and_raise(*_args, **_kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count >= 2:
                retried.set()
            raise ConnectionError("Network unreachable")

        mock_client_class.return_value.__aenter__ = AsyncMock(
            side_effect=track_and_raise
        )

        async def instant_sleep(_seconds):
            await _real_sleep(0)

        with patch("letpot.deviceclient.asyncio.sleep", side_effect=instant_sleep):
            device_client._connected = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(device_client._connect())

            # Wait for the retry loop to have made at least 2 attempts
            async with asyncio.timeout(2):
                await retried.wait()

            assert attempt_count >= 2
            assert not task.done(), "_connect task should still be running"

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.parametrize(
    ("serial", "expected_result"),
    [
        (
            "LPH21GHIJ",
            pytest.raises(LetPotFeatureException, match="missing required feature"),
        ),
        ("LPH62GHIJ", nullcontext()),
    ],
)
async def test_requires_feature_one(
    device_client: LetPotDeviceClient,
    mock_aiomqtt: MagicMock,
    serial: str,
    expected_result,
) -> None:
    """Test the requires_feature annotation requiring one feature."""
    # Prepare device client and mock status for use in call
    await device_client.subscribe(serial, lambda _: None)
    device_client._device_status_last[serial] = DEVICE_STATUS_GARDEN

    with expected_result:
        await device_client.set_temperature_unit(serial, TemperatureUnit.CELSIUS)

    await device_client.unsubscribe(serial)


@pytest.mark.parametrize(
    ("serial", "expected_result"),
    [
        (
            "IGS01JKLM",
            pytest.raises(LetPotFeatureException, match="missing required feature"),
        ),
        ("LPH21JKLM", nullcontext()),
        ("LPH62JKLM", nullcontext()),
    ],
)
async def test_requires_feature_or(
    device_client: LetPotDeviceClient,
    mock_aiomqtt: MagicMock,
    serial: str,
    expected_result,
) -> None:
    """Test the requires_feature annotation requiring any of n features."""
    # Prepare device client and mock status for use in call
    await device_client.subscribe(serial, lambda _: None)
    device_client._device_status_last[serial] = DEVICE_STATUS_GARDEN

    with expected_result:
        await device_client.set_light_brightness(serial, 500)

    await device_client.unsubscribe(serial)
