"""Messages: the meaning carried inside a Frame."""

from dataclasses import dataclass
from enum import IntEnum

from phonedeck.protocol.frame import MAX_PAYLOAD_SIZE, PROTOCOL_VERSION, Frame

REQUEST_ID_SIZE = 2
MAX_REQUEST_ID = 0xFFFF
MAX_BODY_SIZE = MAX_PAYLOAD_SIZE - REQUEST_ID_SIZE


class MessageError(Exception):
    """Raised when a Message cannot be built from, or turned into, a Frame."""


class MessageKind(IntEnum):
    """What a message means. The value is stored in Frame.message_type."""

    COMMAND = 1  # phone -> PC: run a named action
    QUERY = 2  # phone -> PC: ask for a value
    RESPONSE = 3  # PC -> phone: answer to a COMMAND or QUERY
    HANDSHAKE = 4  # both ways: reserved for the secure handshake


@dataclass(frozen=True)
class Message:
    """One message."""

    kind: MessageKind
    request_id: int
    body: bytes


def message_to_frame(message: Message) -> Frame:
    """Put a Message into a Frame."""
    if not (0 <= message.request_id <= MAX_REQUEST_ID):
        raise MessageError(f"Request ID must be 0-{MAX_REQUEST_ID}, got {message.request_id}")

    if len(message.body) > MAX_BODY_SIZE:
        raise MessageError(f"Body too large: {len(message.body)} bytes")

    payload = message.request_id.to_bytes(REQUEST_ID_SIZE, "big") + message.body
    return Frame(version=PROTOCOL_VERSION, message_type=message.kind.value, payload=payload)


def frame_to_message(frame: Frame) -> Message:
    """Read a Message out of a Frame. Raise MessageError on invalid input."""
    if frame.message_type not in MessageKind:
        raise MessageError(f"Unknown message type: {frame.message_type}")

    if len(frame.payload) < REQUEST_ID_SIZE:
        raise MessageError("Payload too short to contain a request ID")

    request_id = int.from_bytes(frame.payload[:REQUEST_ID_SIZE], "big")
    body = frame.payload[REQUEST_ID_SIZE:]

    return Message(kind=MessageKind(frame.message_type), request_id=request_id, body=body)
