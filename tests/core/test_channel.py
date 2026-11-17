"""Tests for phonedeck.core.channel.MessageChannel.

Two channels are connected through an in-memory transport pair, so no hardware is needed.
Tests that send "raw" bytes use the transport directly, to act like a misbehaving other end.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from phonedeck.core.channel import MessageChannel
from phonedeck.protocol.frame import PROTOCOL_VERSION, Frame, FrameError, encode_frame
from phonedeck.protocol.message import MAX_BODY_SIZE, Message, MessageError, MessageKind
from phonedeck.transport.base import TransportClosedError, TransportError
from phonedeck.transport.memory import InMemoryTransport


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run an async test scenario. It fails after 2 seconds instead of hanging forever."""
    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


def make_channels() -> tuple[MessageChannel, MessageChannel]:
    transport_a, transport_b = InMemoryTransport.create_pair()
    return MessageChannel(transport_a), MessageChannel(transport_b)


# --- Messages travel from one channel to the other. ---


def test_a_message_arrives_unchanged() -> None:
    async def scenario() -> None:
        a, b = make_channels()
        message = Message(MessageKind.COMMAND, 7, b"open:notepad")

        await a.send(message)

        assert await b.receive() == message

    run(scenario)


def test_messages_travel_in_both_directions() -> None:
    async def scenario() -> None:
        a, b = make_channels()
        query = Message(MessageKind.QUERY, 1, b"cpu")
        response = Message(MessageKind.RESPONSE, 1, b"\x00\x2a")

        await a.send(query)
        assert await b.receive() == query
        await b.send(response)
        assert await a.receive() == response

    run(scenario)


def test_messages_arrive_in_order() -> None:
    async def scenario() -> None:
        a, b = make_channels()
        sent = [Message(MessageKind.QUERY, i, b"ram") for i in range(20)]

        for message in sent:
            await a.send(message)
        received = [await b.receive() for _ in sent]

        assert received == sent

    run(scenario)


def test_the_largest_message_fits_in_one_packet() -> None:
    async def scenario() -> None:
        a, b = make_channels()
        message = Message(MessageKind.RESPONSE, 65535, b"x" * MAX_BODY_SIZE)

        await a.send(message)

        assert await b.receive() == message

    run(scenario)


# --- Too large for the transport. ---


def test_a_message_too_large_for_the_transport_is_rejected() -> None:
    # The frame is 4 (header) + 2 (request id) + body. With a 20 byte transport:
    # a 14 byte body gives exactly 20 (fits), a 15 byte body gives 21 (too large).
    async def scenario() -> None:
        transport_a, transport_b = InMemoryTransport.create_pair(max_packet_size=20)
        a, b = MessageChannel(transport_a), MessageChannel(transport_b)
        fits = Message(MessageKind.COMMAND, 1, b"x" * 14)
        too_large = Message(MessageKind.COMMAND, 1, b"x" * 15)

        await a.send(fits)
        assert await b.receive() == fits
        with pytest.raises(TransportError):
            await a.send(too_large)

    run(scenario)


# --- The other end sends something invalid. ---


def test_receive_raises_frame_error_for_garbage_bytes() -> None:
    async def scenario() -> None:
        transport_a, transport_b = InMemoryTransport.create_pair()
        b = MessageChannel(transport_b)

        await transport_a.send(b"garbage")

        with pytest.raises(FrameError):
            await b.receive()

    run(scenario)


def test_receive_raises_message_error_for_an_unknown_message_kind() -> None:
    async def scenario() -> None:
        transport_a, transport_b = InMemoryTransport.create_pair()
        b = MessageChannel(transport_b)
        valid_frame_but_unknown_kind = Frame(PROTOCOL_VERSION, 99, b"\x00\x01")

        await transport_a.send(encode_frame(valid_frame_but_unknown_kind))

        with pytest.raises(MessageError):
            await b.receive()

    run(scenario)


def test_the_channel_still_works_after_an_invalid_packet() -> None:
    async def scenario() -> None:
        transport_a, transport_b = InMemoryTransport.create_pair()
        a, b = MessageChannel(transport_a), MessageChannel(transport_b)
        good = Message(MessageKind.QUERY, 3, b"cpu")

        await transport_a.send(b"garbage")
        await a.send(good)

        with pytest.raises(FrameError):
            await b.receive()
        assert await b.receive() == good

    run(scenario)


# --- Closing. ---


def test_receive_raises_when_the_other_end_closes() -> None:
    async def scenario() -> None:
        a, b = make_channels()

        await a.close()

        with pytest.raises(TransportClosedError):
            await b.receive()

    run(scenario)


def test_send_raises_after_closing() -> None:
    async def scenario() -> None:
        a, _ = make_channels()
        await a.close()

        with pytest.raises(TransportClosedError):
            await a.send(Message(MessageKind.QUERY, 1, b""))

    run(scenario)
