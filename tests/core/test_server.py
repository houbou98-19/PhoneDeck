"""Tests for serve. The server runs in the background while the test plays the phone."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from phonedeck.core.channel import MessageChannel
from phonedeck.core.handler import Handler, ResponseStatus
from phonedeck.core.server import serve
from phonedeck.platform.base import MediaKey
from phonedeck.protocol.frame import PROTOCOL_VERSION, Frame, encode_frame
from phonedeck.protocol.message import Message, MessageKind
from phonedeck.transport.memory import InMemoryTransport


class FakeSystem:
    def __init__(self) -> None:
        self.lock_calls = 0

    def cpu_percent(self) -> int:
        return 37

    def ram_percent(self) -> int:
        return 61

    def lock_screen(self) -> None:
        self.lock_calls += 1

    def start_spotify(self) -> None:
        pass

    async def spotify_running(self) -> bool:
        return False

    async def control_spotify(self, key: MediaKey) -> None:
        pass


class Phone:
    def __init__(
        self, channel: MessageChannel, transport: InMemoryTransport, system: FakeSystem
    ) -> None:
        self.channel = channel
        self.transport = transport
        self.system = system


def run_with_server(scenario: Callable[[Phone], Awaitable[None]]) -> None:
    """Start the server, run the scenario as the phone, then hang up and check the server ends."""

    async def main() -> None:
        phone_transport, pc_transport = InMemoryTransport.create_pair()
        system = FakeSystem()
        server = asyncio.ensure_future(serve(MessageChannel(pc_transport), Handler(system)))
        phone = Phone(MessageChannel(phone_transport), phone_transport, system)
        try:
            await scenario(phone)
        finally:
            await phone.channel.close()
        await asyncio.wait_for(server, timeout=1)  # the server must end by itself

    asyncio.run(asyncio.wait_for(main(), timeout=3))


async def ask(phone: Phone, kind: MessageKind, request_id: int, name: bytes) -> Message:
    await phone.channel.send(Message(kind, request_id, name))
    return await phone.channel.receive()


# --- Normal requests. ---


def test_a_query_is_answered_with_the_same_request_id() -> None:
    async def scenario(phone: Phone) -> None:
        response = await ask(phone, MessageKind.QUERY, 7, b"cpu")

        assert response == Message(MessageKind.RESPONSE, 7, b"\x00\x25")

    run_with_server(scenario)


def test_requests_are_answered_in_order() -> None:
    async def scenario(phone: Phone) -> None:
        first = await ask(phone, MessageKind.QUERY, 1, b"cpu")
        second = await ask(phone, MessageKind.QUERY, 2, b"ram")
        third = await ask(phone, MessageKind.QUERY, 3, b"cpu")

        assert [first.request_id, second.request_id, third.request_id] == [1, 2, 3]
        assert second.body == b"\x00\x3d"

    run_with_server(scenario)


def test_a_lock_command_locks_the_computer() -> None:
    async def scenario(phone: Phone) -> None:
        response = await ask(phone, MessageKind.COMMAND, 4, b"lock")

        assert response.body == bytes([ResponseStatus.OK])
        assert phone.system.lock_calls == 1

    run_with_server(scenario)


def test_an_unknown_action_is_refused_and_nothing_runs() -> None:
    async def scenario(phone: Phone) -> None:
        response = await ask(phone, MessageKind.COMMAND, 5, b"format_disk")

        assert response.body == bytes([ResponseStatus.UNKNOWN_ACTION])
        assert phone.system.lock_calls == 0

    run_with_server(scenario)


# --- Bad input must not stop the server. ---


def test_garbage_bytes_do_not_stop_the_server() -> None:
    async def scenario(phone: Phone) -> None:
        await phone.transport.send(b"garbage")

        response = await ask(phone, MessageKind.QUERY, 8, b"cpu")

        assert response.request_id == 8

    run_with_server(scenario)


def test_an_unknown_message_kind_does_not_stop_the_server() -> None:
    async def scenario(phone: Phone) -> None:
        await phone.transport.send(encode_frame(Frame(PROTOCOL_VERSION, 99, b"\x00\x01")))

        response = await ask(phone, MessageKind.QUERY, 9, b"ram")

        assert response.request_id == 9

    run_with_server(scenario)


@pytest.mark.parametrize("kind", [MessageKind.RESPONSE, MessageKind.HANDSHAKE])
def test_a_kind_the_phone_may_not_send_gets_no_answer_and_does_not_stop_the_server(
    kind: MessageKind,
) -> None:
    async def scenario(phone: Phone) -> None:
        await phone.channel.send(Message(kind, 1, b"cpu"))

        # The first answer we get belongs to the next, valid request: nothing came before it.
        response = await ask(phone, MessageKind.QUERY, 10, b"cpu")

        assert response.request_id == 10

    run_with_server(scenario)


# --- Ending. ---


def test_the_server_ends_when_the_phone_disconnects() -> None:
    async def scenario(phone: Phone) -> None:
        await ask(phone, MessageKind.QUERY, 1, b"cpu")
        # Leaving the scenario hangs up. run_with_server checks that the server then returns.

    run_with_server(scenario)
