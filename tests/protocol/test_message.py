"""Tests for phonedeck.protocol.message.

A Message lives inside a Frame:

    Frame.message_type = MessageKind (1 byte)
    Frame.payload      = | request_id (2 bytes, big-endian) | body (the rest) |

Message is expected to have the fields: kind: MessageKind, request_id: int, body: bytes.
"""

import pytest

from phonedeck.protocol.frame import PROTOCOL_VERSION, Frame, decode_frame, encode_frame
from phonedeck.protocol.message import (
    MAX_BODY_SIZE,
    MAX_REQUEST_ID,
    Message,
    MessageError,
    MessageKind,
    frame_to_message,
    message_to_frame,
)

# --- Known values: these pin the exact layout, so it cannot change by accident. ---


def test_message_kind_values_are_fixed() -> None:
    # These numbers are part of the wire format. Changing one breaks every old client.
    assert int(MessageKind.COMMAND) == 1
    assert int(MessageKind.QUERY) == 2
    assert int(MessageKind.RESPONSE) == 3
    assert int(MessageKind.HANDSHAKE) == 4


def test_message_to_frame_produces_expected_frame() -> None:
    message = Message(kind=MessageKind.COMMAND, request_id=0x0102, body=b"lock")

    assert message_to_frame(message) == Frame(PROTOCOL_VERSION, 1, b"\x01\x02lock")


def test_frame_to_message_reads_expected_frame() -> None:
    frame = Frame(PROTOCOL_VERSION, 3, b"\x00\x07\x00ok")

    assert frame_to_message(frame) == Message(MessageKind.RESPONSE, 7, b"\x00ok")


def test_request_id_is_big_endian() -> None:
    # 256 == 0x0100: the high byte comes first.
    frame = message_to_frame(Message(MessageKind.QUERY, 256, b""))

    assert frame.payload[:2] == b"\x01\x00"


# --- Round trips. ---


@pytest.mark.parametrize("kind", list(MessageKind))
def test_round_trip_for_every_kind(kind: MessageKind) -> None:
    message = Message(kind, 1, b"body")

    assert frame_to_message(message_to_frame(message)) == message


@pytest.mark.parametrize("request_id", [0, 1, 255, 256, MAX_REQUEST_ID])
def test_round_trip_request_id_limits(request_id: int) -> None:
    message = Message(MessageKind.QUERY, request_id, b"cpu")

    assert frame_to_message(message_to_frame(message)) == message


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"x",
        bytes(range(256)),  # every possible byte value
        b"x" * MAX_BODY_SIZE,  # largest allowed body
    ],
)
def test_round_trip_bodies(body: bytes) -> None:
    message = Message(MessageKind.RESPONSE, 42, body)

    assert frame_to_message(message_to_frame(message)) == message


def test_round_trip_through_bytes_on_the_wire() -> None:
    # The whole stack: Message -> Frame -> bytes -> Frame -> Message.
    message = Message(MessageKind.COMMAND, 9, b"open:notepad")

    wire_bytes = encode_frame(message_to_frame(message))

    assert frame_to_message(decode_frame(wire_bytes)) == message


# --- Bad input when building a frame. ---


@pytest.mark.parametrize("request_id", [-1, MAX_REQUEST_ID + 1, 100_000])
def test_message_to_frame_rejects_request_id_that_does_not_fit_in_two_bytes(
    request_id: int,
) -> None:
    with pytest.raises(MessageError):
        message_to_frame(Message(MessageKind.QUERY, request_id, b""))


def test_message_to_frame_rejects_too_large_body() -> None:
    message = Message(MessageKind.COMMAND, 1, b"x" * (MAX_BODY_SIZE + 1))

    with pytest.raises(MessageError):
        message_to_frame(message)


# --- Bad input when reading a frame: must raise MessageError, never anything else. ---


@pytest.mark.parametrize("message_type", [0, 5, 99, 255])
def test_frame_to_message_rejects_unknown_kind(message_type: int) -> None:
    with pytest.raises(MessageError):
        frame_to_message(Frame(PROTOCOL_VERSION, message_type, b"\x00\x01"))


@pytest.mark.parametrize("payload", [b"", b"\x01"])
def test_frame_to_message_rejects_payload_shorter_than_request_id(payload: bytes) -> None:
    with pytest.raises(MessageError):
        frame_to_message(Frame(PROTOCOL_VERSION, int(MessageKind.QUERY), payload))


def test_frame_to_message_accepts_empty_body() -> None:
    message = frame_to_message(Frame(PROTOCOL_VERSION, int(MessageKind.QUERY), b"\x00\x05"))

    assert message == Message(MessageKind.QUERY, 5, b"")
