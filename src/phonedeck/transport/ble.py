"""A Transport over BLE, for the PC acting as a peripheral (GATT server).

Two characteristics carry the traffic (like two URL paths on one server):
  * the phone WRITES requests to the write characteristic   (like POST)
  * the PC NOTIFIES responses on the notify characteristic  (like a WebSocket push)

This module has no Windows code. The part that talks to the operating system hides behind
BlePeripheral.
"""

import asyncio.queues
import uuid
from collections.abc import Callable
from typing import Protocol

from phonedeck.protocol.frame import MAX_FRAME_SIZE
from phonedeck.transport.base import TransportClosedError, TransportError


def write_characteristic_uuid(service_uuid: str) -> str:
    """UUID of the characteristic the phone WRITES requests to, for this service."""
    uuid_obj = uuid.UUID(service_uuid)
    return str(uuid.uuid5(uuid_obj, "write"))


def notify_characteristic_uuid(service_uuid: str) -> str:
    """UUID of the characteristic the PC NOTIFIES responses on, for this service."""
    uuid_obj = uuid.UUID(service_uuid)
    return str(uuid.uuid5(uuid_obj, "notify"))


class BlePeripheral(Protocol):
    """The operating-system side of BLE: advertise, receive writes, send notifications.

    A real Windows implementation and a fake for tests both satisfy this interface.
    """

    def set_handlers(
        self, on_write: Callable[[bytes], None], on_disconnect: Callable[[], None]
    ) -> None:
        """Say what to call when the phone writes a packet, and when the phone disconnects.

        Both handlers must be called on the asyncio event loop's own thread. If the operating
        system calls from another thread, the implementation has to hand the call over.
        """

    async def start(self) -> None:
        """Start advertising, so the phone can find and connect to the PC."""

    async def stop(self) -> None:
        """Stop advertising and drop any connection."""

    async def notify(self, data: bytes) -> None:
        """Send one notification to the connected phone."""


class BleTransport:
    """Moves packets between the PC and one phone, through a BlePeripheral.

    Behaviour (the tests pin all of it):
      * send(): one call is one notification. Too large -> TransportError, nothing is sent.
      * receive(): one phone write is one packet. Packets keep their order and boundaries.
      * If the phone disconnects, packets already written can still be received first, then
        receive() raises TransportClosedError. send() raises it straight away.
      * close() stops the peripheral (only once, closing twice is fine). It also wakes up a
        receive() that is waiting. After close(), send() and receive() raise
        TransportClosedError, and any later write from the phone is ignored.
    """

    def __init__(self, peripheral: BlePeripheral, max_packet_size: int = MAX_FRAME_SIZE) -> None:
        """Remember the peripheral and register this transport's handlers with it."""
        self._peripheral = peripheral
        self._max_packet_size = max_packet_size
        self._closed = False
        self._disconnected = False

        self._queue: asyncio.queues.Queue[bytes | None] = asyncio.queues.Queue()
        self._peripheral.set_handlers(self._on_write, self._on_disconnect)

    @property
    def max_packet_size(self) -> int:
        """The largest packet, in bytes, that send() accepts."""
        return self._max_packet_size

    async def send(self, packet: bytes) -> None:
        """Send one packet to the phone as one notification."""
        if len(packet) > self._max_packet_size:
            raise TransportError(
                f"Packet too large: {len(packet)} bytes, max is {self._max_packet_size}"
            )
        if self._closed or self._disconnected:
            raise TransportClosedError("Transport is closed")
        await self._peripheral.notify(packet)

    async def receive(self) -> bytes:
        """Wait for the next packet the phone wrote and return it."""
        if self._closed:
            raise TransportClosedError("Transport is closed")
        packet = await self._queue.get()
        if packet is None:
            self._queue.put_nowait(None)
            raise TransportClosedError("Transport is closed")
        return packet

    async def close(self) -> None:
        """Close this end. Closing twice is fine."""
        if self._closed:
            return
        self._closed = True
        await self._peripheral.stop()
        self._queue.put_nowait(None)

    def _on_write(self, data: bytes) -> None:
        """Called by the peripheral when the phone writes a packet."""
        if self._closed or self._disconnected:
            return
        self._queue.put_nowait(data)

    def _on_disconnect(self) -> None:
        """Called by the peripheral when the phone disconnects."""
        if self._closed or self._disconnected:
            return
        self._queue.put_nowait(None)
        self._disconnected = True
