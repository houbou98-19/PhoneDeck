"""Tests for the wire framing in phonedeck.protocol.frame.

Wire format (all integers big-endian):

    | version (1 byte) | message_type (1 byte) | length (2 bytes) | payload (length bytes) |

Frame is expected to have the fields: version: int, message_type: int, payload: bytes.
"""

import pytest

from phonedeck.protocol.frame import (
    HEADER_SIZE,
    MAX_FRAME_SIZE,
    MAX_PAYLOAD_SIZE,
    PROTOCOL_VERSION,
    Frame,
    FrameError,
    decode_frame,
    encode_frame,
)

# --- Known bytes: these pin the exact wire format, so it cannot change by accident. ---


def test_encode_produces_expected_bytes() -> None:
    frame = Frame(version=1, message_type=2, payload=b"hi")

    assert encode_frame(frame) == b"\x01\x02\x00\x02hi"


def test_decode_reads_expected_bytes() -> None:
    frame = decode_frame(b"\x01\x02\x00\x02hi")

    assert frame == Frame(version=1, message_type=2, payload=b"hi")


def test_largest_frame_fits_in_one_ble_write() -> None:
    # A BLE GATT value holds at most 512 bytes, so the largest frame must not exceed that.
    frame = Frame(PROTOCOL_VERSION, 0, b"x" * MAX_PAYLOAD_SIZE)

    assert len(encode_frame(frame)) == MAX_FRAME_SIZE == 512


def test_length_field_is_big_endian() -> None:
    # 0x0100 == 256: big-endian puts the high byte first.
    payload = b"x" * 256

    assert encode_frame(Frame(1, 0, payload))[2:4] == b"\x01\x00"


# --- Round trips: decode(encode(x)) must give x back. ---


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"a",
        bytes(range(256)),  # every possible byte value, incl. 0x00 and 0xff
        b"x" * MAX_PAYLOAD_SIZE,  # largest allowed payload
    ],
)
def test_round_trip(payload: bytes) -> None:
    frame = Frame(version=PROTOCOL_VERSION, message_type=7, payload=payload)

    assert decode_frame(encode_frame(frame)) == frame


@pytest.mark.parametrize("message_type", [0, 1, 255])
def test_round_trip_message_type_limits(message_type: int) -> None:
    frame = Frame(PROTOCOL_VERSION, message_type, b"")

    assert decode_frame(encode_frame(frame)) == frame


# --- Bad input to decode: must raise FrameError, never any other exception. ---


@pytest.mark.parametrize(
    ("data", "why"),
    [
        (b"", "empty input"),
        (b"\x01", "shorter than the header"),
        (b"\x01\x02\x00", "one byte short of the header"),
        (b"\x02\x02\x00\x00", "unknown protocol version"),
        (b"\x00\x02\x00\x00", "version zero"),
        (b"\x01\x02\x00\x05hi", "length says 5 but only 2 payload bytes follow"),
        (b"\x01\x02\x00\x01hi", "length says 1 but 2 payload bytes follow (trailing data)"),
        (b"\x01\x02\xff\xff", "length far larger than the allowed maximum"),
        (
            b"\x01\x02" + (MAX_PAYLOAD_SIZE + 1).to_bytes(2, "big") + b"x" * (MAX_PAYLOAD_SIZE + 1),
            "length one above MAX_PAYLOAD_SIZE",
        ),
    ],
)
def test_decode_rejects_invalid_input(data: bytes, why: str) -> None:
    with pytest.raises(FrameError):
        decode_frame(data)


def test_decode_header_only_frame_is_valid() -> None:
    frame = decode_frame(b"\x01\x05\x00\x00")

    assert frame.payload == b""
    assert len(b"\x01\x05\x00\x00") == HEADER_SIZE


# --- Bad input to encode. ---


def test_encode_rejects_too_large_payload() -> None:
    frame = Frame(PROTOCOL_VERSION, 1, b"x" * (MAX_PAYLOAD_SIZE + 1))

    with pytest.raises(FrameError):
        encode_frame(frame)


@pytest.mark.parametrize("message_type", [-1, 256, 1000])
def test_encode_rejects_message_type_that_does_not_fit_in_one_byte(message_type: int) -> None:
    with pytest.raises(FrameError):
        encode_frame(Frame(PROTOCOL_VERSION, message_type, b""))


@pytest.mark.parametrize("version", [-1, 256])
def test_encode_rejects_version_that_does_not_fit_in_one_byte(version: int) -> None:
    with pytest.raises(FrameError):
        encode_frame(Frame(version, 1, b""))
