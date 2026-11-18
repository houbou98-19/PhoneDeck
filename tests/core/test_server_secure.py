"""Tests for phonedeck.core.server.serve running over a SecureChannel.

The point of these tests: nothing is ever handled unless the phone has proven that it has the
pairing key. In particular, a lock command that is not authentic must never lock the computer.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from phonedeck.core.channel import MessageChannel
from phonedeck.core.handler import Handler, ResponseStatus
from phonedeck.core.secure_channel import Role, SecureChannel
from phonedeck.core.server import serve
from phonedeck.protocol.frame import encode_frame
from phonedeck.protocol.message import Message, MessageKind, message_to_frame
from phonedeck.transport.memory import InMemoryTransport

KEY = bytes(range(0x00, 0x10))


class FakeSystem:
    """A computer with fixed values that remembers what it was asked to do."""

    def __init__(self) -> None:
        self.lock_calls = 0

    def cpu_percent(self) -> int:
        return 37

    def ram_percent(self) -> int:
        return 61

    def lock_screen(self) -> None:
        self.lock_calls += 1


class FlippingTransport:
    """Wraps a transport. When armed, it changes the last byte of the next packet it sends."""

    def __init__(self, inner: InMemoryTransport) -> None:
        self._inner = inner
        self.armed = False

    @property
    def max_packet_size(self) -> int:
        return self._inner.max_packet_size

    async def send(self, packet: bytes) -> None:
        if self.armed:
            self.armed = False
            packet = packet[:-1] + bytes([packet[-1] ^ 0x01])
        await self._inner.send(packet)

    async def receive(self) -> bytes:
        return await self._inner.receive()

    async def close(self) -> None:
        await self._inner.close()


@dataclass
class Session:
    phone: SecureChannel
    phone_raw: InMemoryTransport  # sends straight to the computer, like an intruder could
    flipper: FlippingTransport
    system: FakeSystem
    server: "asyncio.Future[None]"


def run_session(scenario: Callable[[Session], Awaitable[None]]) -> None:
    """Connect a phone (a handshake has been done), start the server, run the scenario."""

    async def main() -> None:
        phone_raw, pc_raw = InMemoryTransport.create_pair()
        flipper = FlippingTransport(phone_raw)
        phone = SecureChannel(MessageChannel(flipper), Role.CLIENT, KEY)
        pc = SecureChannel(MessageChannel(pc_raw), Role.SERVER, KEY)
        await asyncio.gather(phone.handshake(), pc.handshake())
        system = FakeSystem()
        server = asyncio.ensure_future(serve(pc, Handler(system)))
        session = Session(phone, phone_raw, flipper, system, server)
        try:
            await scenario(session)
        finally:
            await phone.close()
        await asyncio.wait_for(server, timeout=1)  # the server must end by itself

    asyncio.run(asyncio.wait_for(main(), timeout=3))


async def ask(session: Session, kind: MessageKind, request_id: int, name: bytes) -> Message:
    await session.phone.send(Message(kind, request_id, name))
    return await session.phone.receive()


# --- Authentic requests are answered. ---


def test_a_query_over_the_secure_channel_is_answered() -> None:
    async def scenario(session: Session) -> None:
        response = await ask(session, MessageKind.QUERY, 7, b"cpu")

        assert response == Message(MessageKind.RESPONSE, 7, b"\x00\x25")

    run_session(scenario)


def test_an_authentic_lock_command_locks_the_computer() -> None:
    async def scenario(session: Session) -> None:
        response = await ask(session, MessageKind.COMMAND, 1, b"lock")

        assert response.body == bytes([ResponseStatus.OK])
        assert session.system.lock_calls == 1

    run_session(scenario)


def test_several_requests_in_a_row_are_answered_in_order() -> None:
    async def scenario(session: Session) -> None:
        first = await ask(session, MessageKind.QUERY, 1, b"cpu")
        second = await ask(session, MessageKind.QUERY, 2, b"ram")
        third = await ask(session, MessageKind.QUERY, 3, b"cpu")

        assert [first.request_id, second.request_id, third.request_id] == [1, 2, 3]
        assert second.body == b"\x00\x3d"

    run_session(scenario)


# --- Anything that is not authentic must never run, and ends the session. ---


def test_a_lock_command_in_the_clear_never_runs() -> None:
    async def scenario(session: Session) -> None:
        intruder = encode_frame(message_to_frame(Message(MessageKind.COMMAND, 1, b"lock")))
        await session.phone_raw.send(intruder)

        await asyncio.wait_for(session.server, timeout=1)  # the session ends by itself

        assert session.system.lock_calls == 0

    run_session(scenario)


def test_a_tampered_lock_command_never_runs() -> None:
    async def scenario(session: Session) -> None:
        session.flipper.armed = True  # one byte is changed on the way to the computer

        await session.phone.send(Message(MessageKind.COMMAND, 1, b"lock"))

        await asyncio.wait_for(session.server, timeout=1)
        assert session.system.lock_calls == 0

    run_session(scenario)


# --- Harmless bad input does not end the session. ---


def test_garbage_bytes_do_not_end_the_session() -> None:
    async def scenario(session: Session) -> None:
        await session.phone_raw.send(b"garbage")

        response = await ask(session, MessageKind.QUERY, 8, b"cpu")

        assert response.request_id == 8

    run_session(scenario)


# --- Ending. ---


@pytest.mark.parametrize("name", [b"format_disk", b"LOCK"])
def test_an_authentic_but_unknown_action_is_refused_and_nothing_runs(name: bytes) -> None:
    async def scenario(session: Session) -> None:
        response = await ask(session, MessageKind.COMMAND, 5, name)

        assert response.body == bytes([ResponseStatus.UNKNOWN_ACTION])
        assert session.system.lock_calls == 0

    run_session(scenario)


def test_the_server_ends_when_the_phone_disconnects() -> None:
    async def scenario(session: Session) -> None:
        await ask(session, MessageKind.QUERY, 1, b"cpu")
        # Leaving the scenario hangs up. run_session checks that the server then returns.

    run_session(scenario)
