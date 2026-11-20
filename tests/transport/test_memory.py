"""Tests for InMemoryTransport. Tests that could hang use wait_for, so they fail after 1 second."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from phonedeck.protocol.frame import MAX_FRAME_SIZE
from phonedeck.transport.base import Transport, TransportClosedError, TransportError
from phonedeck.transport.memory import InMemoryTransport


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Run an async test scenario. It fails after 2 seconds instead of hanging forever."""
    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


# --- Sending and receiving. ---


def test_a_sent_packet_arrives_unchanged() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()

        await a.send(b"hello")

        assert await b.receive() == b"hello"

    run(scenario)


def test_packets_travel_in_both_directions() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()

        await a.send(b"to b")
        await b.send(b"to a")

        assert await b.receive() == b"to b"
        assert await a.receive() == b"to a"

    run(scenario)


def test_packet_boundaries_are_kept() -> None:
    # Two sends are two receives. They are never merged or split. (This is "packet-oriented".)
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()

        await a.send(b"hello")
        await a.send(b"world")

        assert await b.receive() == b"hello"
        assert await b.receive() == b"world"

    run(scenario)


def test_packets_arrive_in_the_order_they_were_sent() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()
        sent = [bytes([i]) for i in range(100)]

        for packet in sent:
            await a.send(packet)
        received = [await b.receive() for _ in sent]

        assert received == sent

    run(scenario)


def test_an_empty_packet_is_delivered_as_an_empty_packet() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()

        await a.send(b"")

        assert await b.receive() == b""

    run(scenario)


def test_receive_waits_until_a_packet_arrives() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()
        receiver = asyncio.create_task(b.receive())
        await asyncio.sleep(0)  # give the receiver a chance to start waiting

        assert not receiver.done()  # nothing was sent, so it must still be waiting
        await a.send(b"late")

        assert await asyncio.wait_for(receiver, timeout=1) == b"late"

    run(scenario)


# --- Packet size. ---


def test_default_max_packet_size_is_the_largest_frame() -> None:
    a, b = InMemoryTransport.create_pair()

    assert a.max_packet_size == MAX_FRAME_SIZE
    assert b.max_packet_size == MAX_FRAME_SIZE


def test_both_ends_report_a_custom_max_packet_size() -> None:
    a, b = InMemoryTransport.create_pair(max_packet_size=20)

    assert a.max_packet_size == 20
    assert b.max_packet_size == 20


def test_a_packet_of_exactly_max_size_is_accepted() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair(max_packet_size=20)

        await a.send(b"x" * 20)

        assert await b.receive() == b"x" * 20

    run(scenario)


def test_a_too_large_packet_is_rejected() -> None:
    async def scenario() -> None:
        a, _ = InMemoryTransport.create_pair(max_packet_size=20)

        with pytest.raises(TransportError):
            await a.send(b"x" * 21)

    run(scenario)


# --- Closing. ---


def test_sending_after_closing_this_end_raises() -> None:
    async def scenario() -> None:
        a, _ = InMemoryTransport.create_pair()
        await a.close()

        with pytest.raises(TransportClosedError):
            await a.send(b"too late")

    run(scenario)


def test_receiving_after_closing_this_end_raises() -> None:
    async def scenario() -> None:
        a, _ = InMemoryTransport.create_pair()
        await a.close()

        with pytest.raises(TransportClosedError):
            await a.receive()

    run(scenario)


def test_sending_to_a_closed_peer_raises() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()
        await b.close()

        with pytest.raises(TransportClosedError):
            await a.send(b"nobody is listening")

    run(scenario)


def test_packets_sent_before_the_peer_closed_are_still_delivered() -> None:
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()
        await a.send(b"last words")
        await a.close()

        assert await b.receive() == b"last words"
        with pytest.raises(TransportClosedError):  # then the closed end shows
            await b.receive()

    run(scenario)


def test_a_waiting_receive_is_woken_up_when_the_peer_closes() -> None:
    # The hardest one: b is already waiting when a closes. It must not wait forever.
    async def scenario() -> None:
        a, b = InMemoryTransport.create_pair()
        receiver = asyncio.create_task(b.receive())
        await asyncio.sleep(0)  # let the receiver start waiting

        await a.close()

        with pytest.raises(TransportClosedError):
            await asyncio.wait_for(receiver, timeout=1)

    run(scenario)


def test_closing_twice_is_fine() -> None:
    async def scenario() -> None:
        a, _ = InMemoryTransport.create_pair()

        await a.close()
        await a.close()

    run(scenario)


# --- The interface. ---


def test_in_memory_transport_is_a_transport() -> None:
    # mypy checks this assignment: it fails if InMemoryTransport does not fit the interface.
    a, _ = InMemoryTransport.create_pair()
    transport: Transport = a

    assert transport.max_packet_size == MAX_FRAME_SIZE
