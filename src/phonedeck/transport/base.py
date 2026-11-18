"""The Transport interface: whole packets between two ends, one send() is one receive()."""

from typing import Protocol


class TransportError(Exception):
    """Raised when a packet cannot be sent or received."""


class TransportClosedError(TransportError):
    """Raised when the transport is closed, by this end or by the other end."""


class Transport(Protocol):
    """Anything that can move packets: BLE, an in-memory fake, a wire."""

    @property
    def max_packet_size(self) -> int:
        """The largest packet, in bytes, that send() accepts."""

    async def send(self, packet: bytes) -> None:
        """Send one packet. Raise TransportError if it is too large."""

    async def receive(self) -> bytes:
        """Wait for the next packet and return it."""

    async def close(self) -> None:
        """Close this end. Closing twice is fine."""
