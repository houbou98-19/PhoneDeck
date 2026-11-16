"""Frame encoding and decoding for the phonedeck protocol."""

from dataclasses import dataclass

PROTOCOL_VERSION = 1
HEADER_SIZE = 4  # version (1) + message type (1) + payload length (2), big-endian
MAX_PAYLOAD_SIZE = 508
MAX_FRAME_SIZE = HEADER_SIZE + MAX_PAYLOAD_SIZE  # 512: the largest value a BLE GATT write can hold


class FrameError(Exception):
    """Raised when bytes cannot be decoded into a valid Frame."""


@dataclass(frozen=True)
class Frame:
    """One message on the wire."""

    version: int
    message_type: int
    payload: bytes


def encode_frame(frame: Frame) -> bytes:
    """Turn a Frame into bytes."""
    if frame.version != PROTOCOL_VERSION:
        raise FrameError(f"Unsupported protocol version: {frame.version}")

    if not (0 <= frame.message_type <= 255):
        raise FrameError(f"Message type must be 0-255, got {frame.message_type}")

    payload_length = len(frame.payload)
    if payload_length > MAX_PAYLOAD_SIZE:
        raise FrameError(f"Payload too large: {payload_length} bytes")

    # Pack the header: version (1 byte), message type (1 byte), payload length (2 bytes, big-endian)
    header = bytes([frame.version, frame.message_type]) + payload_length.to_bytes(2, "big")

    return header + frame.payload


def decode_frame(data: bytes) -> Frame:
    """Turn bytes back into a Frame. Raise FrameError on invalid input."""
    if len(data) < HEADER_SIZE:
        raise FrameError("Data too short to contain a valid header")

    version = data[0]
    message_type = data[1]
    payload_length = int.from_bytes(data[2:HEADER_SIZE], "big")

    if version != PROTOCOL_VERSION:
        raise FrameError(f"Unsupported protocol version: {version}")

    if payload_length > MAX_PAYLOAD_SIZE:
        raise FrameError(f"Payload length exceeds maximum allowed size: {payload_length} bytes")

    if len(data) != HEADER_SIZE + payload_length:
        raise FrameError("Data length does not match header's payload length")

    payload = data[4 : 4 + payload_length]

    return Frame(version, message_type, payload)
