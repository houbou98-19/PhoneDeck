"""Tests for pair_and_serve. They use real but very short pairing times."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from phonedeck.core.channel import MessageChannel
from phonedeck.core.handler import Handler
from phonedeck.core.pairing import Pairing
from phonedeck.core.secure_channel import Role, SecureChannel
from phonedeck.core.session import pair_and_serve
from phonedeck.platform.base import MediaKey
from phonedeck.protocol.frame import encode_frame
from phonedeck.protocol.message import Message, MessageKind, message_to_frame
from phonedeck.transport.base import TransportClosedError
from phonedeck.transport.memory import InMemoryTransport

WRONG_KEY = bytes(range(0x40, 0x50))


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


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(asyncio.wait_for(scenario(), timeout=5))


class Setup:
    def __init__(self, lifetime: float, phone_key: bytes | None = None) -> None:
        self.pairing = Pairing(lifetime=lifetime)
        self.system = FakeSystem()
        phone_raw, pc_raw = InMemoryTransport.create_pair()
        self.phone_raw = phone_raw
        self.phone_channel = MessageChannel(phone_raw)
        pc_key = self.pairing.take_key()
        self.pc = SecureChannel(MessageChannel(pc_raw), Role.SERVER, pc_key)
        self.phone = SecureChannel(self.phone_channel, Role.CLIENT, phone_key or pc_key)
        self.session = asyncio.ensure_future(
            pair_and_serve(self.pc, self.pairing, Handler(self.system))
        )


def test_a_phone_with_the_key_is_paired_and_served() -> None:
    async def scenario() -> None:
        setup = Setup(lifetime=5)

        await setup.phone.handshake()
        await setup.phone.send(Message(MessageKind.COMMAND, 1, b"lock"))
        response = await setup.phone.receive()
        await setup.phone.close()

        assert response.body == b"\x00"
        assert setup.system.lock_calls == 1
        assert await asyncio.wait_for(setup.session, timeout=1) is True

    run(scenario)


def test_a_phone_with_the_wrong_key_is_not_paired() -> None:
    async def scenario() -> None:
        setup = Setup(lifetime=5, phone_key=WRONG_KEY)

        results = await asyncio.gather(setup.phone.handshake(), return_exceptions=True)

        assert isinstance(results[0], Exception)
        assert await asyncio.wait_for(setup.session, timeout=1) is False
        assert setup.system.lock_calls == 0

    run(scenario)


def test_the_pairing_ends_when_no_phone_connects_in_time() -> None:
    async def scenario() -> None:
        setup = Setup(lifetime=0.2)

        assert await asyncio.wait_for(setup.session, timeout=2) is False
        with pytest.raises(TransportClosedError):
            await setup.phone_channel.receive()  # the computer hung up

    run(scenario)


def test_a_phone_that_is_too_slow_does_not_get_paired() -> None:
    async def scenario() -> None:
        setup = Setup(lifetime=0.2)

        await asyncio.sleep(0.4)  # the key has expired by now
        results = await asyncio.gather(setup.phone.handshake(), return_exceptions=True)

        assert isinstance(results[0], Exception)
        assert await asyncio.wait_for(setup.session, timeout=1) is False

    run(scenario)


def test_a_phone_that_leaves_before_pairing_ends_the_session() -> None:
    async def scenario() -> None:
        setup = Setup(lifetime=5)

        await setup.phone.close()

        assert await asyncio.wait_for(setup.session, timeout=1) is False

    run(scenario)


def test_a_lock_command_in_the_clear_before_pairing_never_runs() -> None:
    async def scenario() -> None:
        setup = Setup(lifetime=5)
        intruder = encode_frame(message_to_frame(Message(MessageKind.COMMAND, 1, b"lock")))

        await setup.phone_raw.send(intruder)

        assert await asyncio.wait_for(setup.session, timeout=1) is False
        assert setup.system.lock_calls == 0

    run(scenario)
