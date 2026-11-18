"""MessageChannel: send and receive Messages over a Transport."""

from typing import Protocol

from phonedeck.protocol.frame import decode_frame, encode_frame
from phonedeck.protocol.message import Message, frame_to_message, message_to_frame
from phonedeck.transport.base import Transport


class Channel(Protocol):
    """Anything that can send and receive Messages: a MessageChannel, or a SecureChannel."""

    async def send(self, message: Message) -> None:
        """Send one message."""

    async def receive(self) -> Message:
        """Wait for the next message and return it."""

    async def close(self) -> None:
        """Close the channel."""


class MessageChannel:
    """Wraps a Transport so that callers deal in Messages, not bytes.

    Sending:   Message -> Frame -> bytes -> Transport.send
    Receiving: Transport.receive -> bytes -> Frame -> Message
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def send(self, message: Message) -> None:
        """Send one message.

        Errors from the layers below (MessageError, FrameError, TransportError) are not hidden.
        """
        frame = message_to_frame(message)
        encoded = encode_frame(frame)
        await self._transport.send(encoded)

    async def receive(self) -> Message:
        """Wait for the next message and return it.

        Raise FrameError or MessageError if the other end sent something invalid.
        The channel stays usable afterwards: the next call reads the next packet.
        """
        packet = await self._transport.receive()
        decoded_frame = decode_frame(packet)
        message = frame_to_message(decoded_frame)
        return message

    async def close(self) -> None:
        """Close the underlying transport."""
        await self._transport.close()
