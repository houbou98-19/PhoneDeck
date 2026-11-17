"""An in-memory Transport for tests and demos: no hardware needed."""

import asyncio.queues
from typing import Self

from phonedeck.protocol.frame import MAX_FRAME_SIZE
from phonedeck.transport.base import TransportClosedError, TransportError


class InMemoryTransport:
    """One end of a pair of connected in-memory transports.

    Make a connected pair with create_pair(). What one end sends, the other end receives.
    """

    def __init__(self, max_packet_size: int):
        self._max_packet_size = max_packet_size
        self._closed = False
        self._other: Self | None = None
        self._queue: asyncio.queues.Queue[bytes | None] = asyncio.queues.Queue()

    @classmethod
    def create_pair(cls, max_packet_size: int = MAX_FRAME_SIZE) -> tuple[Self, Self]:
        """Make two connected ends. Both report the same max_packet_size."""
        end1 = cls(max_packet_size=max_packet_size)
        end2 = cls(max_packet_size=max_packet_size)
        end1._other = end2
        end2._other = end1
        return end1, end2

    @property
    def max_packet_size(self) -> int:
        """The largest packet, in bytes, that send() accepts."""
        return self._max_packet_size

    async def send(self, packet: bytes) -> None:
        """Send a packet to the other end.

        Raise TransportError if it is too large, or if the transport is closed.
        """
        if len(packet) > self._max_packet_size:
            raise TransportError(
                f"Packet too large: {len(packet)} bytes, max is {self._max_packet_size}"
            )
        if not self._other:
            raise TransportClosedError("Transport is closed")
        await self._other._queue.put(packet)

    async def receive(self) -> bytes:
        """Wait for the next packet from the other end and return it.

        Raise TransportClosedError if the other end is closed or if this end is closed.
        """
        if self._closed:
            raise TransportClosedError("Transport is closed")
        packet = await self._queue.get()
        if packet is None:
            self._closed = True
            raise TransportClosedError("Transport is closed")
        return packet

    async def close(self) -> None:
        """Close this end."""
        if self._closed:
            return
        self._closed = True
        other = self._other
        self._other = None
        if other is not None:
            other._other = None
            await other._queue.put(None)
