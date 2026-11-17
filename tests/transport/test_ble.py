"""Tests for phonedeck.transport.ble.BleTransport.

The operating system is replaced by FakePeripheral, so no Bluetooth hardware is needed.
The "phone" is played by the test, through FakePeripheral.phone_writes() and
FakePeripheral.phone_disconnects().
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from phonedeck.core.channel import MessageChannel
from phonedeck.protocol.frame import MAX_FRAME_SIZE, encode_frame
from phonedeck.protocol.message import Message, MessageKind, message_to_frame
from phonedeck.transport.base import TransportClosedError, TransportError
from phonedeck.transport.ble import (
    NOTIFY_CHARACTERISTIC_UUID,
    WRITE_CHARACTERISTIC_UUID,
    BleTransport,
)


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run an async test scenario. It fails after 2 seconds instead of hanging forever."""
    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


class FakePeripheral:
    """A pretend BLE stack. It records notifications and lets the test act as the phone."""

    def __init__(self) -> None:
        self.notified: list[bytes] = []
        self.stop_calls = 0
        self._on_write: Callable[[bytes], None] | None = None
        self._on_disconnect: Callable[[], None] | None = None

    # The BlePeripheral interface.

    def set_handlers(
        self, on_write: Callable[[bytes], None], on_disconnect: Callable[[], None]
    ) -> None:
        self._on_write = on_write
        self._on_disconnect = on_disconnect

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        self.stop_calls += 1

    async def notify(self, data: bytes) -> None:
        self.notified.append(data)

    # What the test can do as the phone.

    def phone_writes(self, data: bytes) -> None:
        assert self._on_write is not None, "the transport never registered its handlers"
        self._on_write(data)

    def phone_disconnects(self) -> None:
        assert self._on_disconnect is not None, "the transport never registered its handlers"
        self._on_disconnect()


def make_transport(max_packet_size: int = MAX_FRAME_SIZE) -> tuple[BleTransport, FakePeripheral]:
    peripheral = FakePeripheral()
    return BleTransport(peripheral, max_packet_size), peripheral


# --- The characteristic UUIDs are part of the protocol (the web page uses the same ones). ---
# The service UUID is not fixed: every installation has its own.


def test_the_characteristic_uuids_are_fixed() -> None:
    assert WRITE_CHARACTERISTIC_UUID == "7d2a0002-8c1e-4b6f-9a3d-5e1f0c2b4a10"
    assert NOTIFY_CHARACTERISTIC_UUID == "7d2a0003-8c1e-4b6f-9a3d-5e1f0c2b4a10"


# --- Size. ---


def test_the_default_max_packet_size_is_the_largest_frame() -> None:
    transport, _ = make_transport()

    assert transport.max_packet_size == MAX_FRAME_SIZE


def test_the_max_packet_size_can_be_lowered() -> None:
    transport, _ = make_transport(max_packet_size=20)

    assert transport.max_packet_size == 20


# --- Sending: PC -> phone, as notifications. ---


def test_send_notifies_with_exactly_the_bytes() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        await transport.send(b"\x01\x02\x03")

        assert peripheral.notified == [b"\x01\x02\x03"]

    run(scenario)


def test_each_send_is_one_notification_in_order() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        await transport.send(b"first")
        await transport.send(b"second")

        assert peripheral.notified == [b"first", b"second"]

    run(scenario)


def test_a_packet_of_exactly_the_max_size_is_sent() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport(max_packet_size=20)

        await transport.send(b"x" * 20)

        assert peripheral.notified == [b"x" * 20]

    run(scenario)


def test_a_too_large_packet_is_rejected_and_not_sent() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport(max_packet_size=20)

        with pytest.raises(TransportError):
            await transport.send(b"x" * 21)

        assert peripheral.notified == []

    run(scenario)


# --- Receiving: phone -> PC, as writes. ---


def test_written_packets_are_received_in_order_with_their_boundaries() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        peripheral.phone_writes(b"one")
        peripheral.phone_writes(b"two")
        peripheral.phone_writes(b"three")

        assert await transport.receive() == b"one"
        assert await transport.receive() == b"two"
        assert await transport.receive() == b"three"

    run(scenario)


def test_receive_waits_until_the_phone_writes() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        waiting = asyncio.ensure_future(transport.receive())
        await asyncio.sleep(0)  # let the receive start waiting
        assert not waiting.done()

        peripheral.phone_writes(b"hello")

        assert await waiting == b"hello"

    run(scenario)


# --- The phone disconnects. ---


def test_receive_raises_when_the_phone_disconnects() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        peripheral.phone_disconnects()

        with pytest.raises(TransportClosedError):
            await transport.receive()

    run(scenario)


def test_a_waiting_receive_raises_when_the_phone_disconnects() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()
        waiting = asyncio.ensure_future(transport.receive())
        await asyncio.sleep(0)

        peripheral.phone_disconnects()

        with pytest.raises(TransportClosedError):
            await waiting

    run(scenario)


def test_packets_written_before_a_disconnect_are_still_received() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        peripheral.phone_writes(b"last words")
        peripheral.phone_disconnects()

        assert await transport.receive() == b"last words"
        with pytest.raises(TransportClosedError):
            await transport.receive()

    run(scenario)


def test_receive_keeps_raising_after_the_end_was_reached() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()
        peripheral.phone_disconnects()
        with pytest.raises(TransportClosedError):
            await transport.receive()  # reads the end marker

        with pytest.raises(TransportClosedError):
            await transport.receive()  # must not wait forever for a packet that never comes

    run(scenario)


def test_send_raises_after_the_phone_disconnects() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        peripheral.phone_disconnects()

        with pytest.raises(TransportClosedError):
            await transport.send(b"anyone there?")
        assert peripheral.notified == []

    run(scenario)


# --- Closing from this end. ---


def test_close_stops_the_peripheral_once_even_if_closed_twice() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()

        await transport.close()
        await transport.close()

        assert peripheral.stop_calls == 1

    run(scenario)


def test_close_wakes_a_waiting_receive() -> None:
    async def scenario() -> None:
        transport, _ = make_transport()
        waiting = asyncio.ensure_future(transport.receive())
        await asyncio.sleep(0)

        await transport.close()

        with pytest.raises(TransportClosedError):
            await waiting

    run(scenario)


def test_send_and_receive_raise_after_close() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()
        peripheral.phone_writes(b"not delivered")

        await transport.close()

        with pytest.raises(TransportClosedError):
            await transport.send(b"x")
        with pytest.raises(TransportClosedError):
            await transport.receive()

    run(scenario)


def test_a_write_after_close_is_ignored() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()
        await transport.close()

        peripheral.phone_writes(b"too late")  # must not raise

        with pytest.raises(TransportClosedError):
            await transport.receive()

    run(scenario)


# --- It works under a MessageChannel, the way the real app uses it. ---


def test_a_message_channel_works_on_top_of_it() -> None:
    async def scenario() -> None:
        transport, peripheral = make_transport()
        channel = MessageChannel(transport)
        query = Message(MessageKind.QUERY, 9, b"cpu")
        response = Message(MessageKind.RESPONSE, 9, b"\x00\x25")

        peripheral.phone_writes(encode_frame(message_to_frame(query)))
        assert await channel.receive() == query

        await channel.send(response)
        assert peripheral.notified == [encode_frame(message_to_frame(response))]

    run(scenario)
