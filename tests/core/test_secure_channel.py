"""Tests for SecureChannel.

TapTransport sits between the phone (CLIENT) and the computer (SERVER) and plays the attacker:
it can change, repeat or drop the next packet. The raw channels let a test send what a
SecureChannel never would.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import pytest

from phonedeck.core.channel import MessageChannel
from phonedeck.core.secure_channel import (
    HandshakeError,
    HandshakeStep,
    Role,
    SecureChannel,
    SecureChannelError,
)
from phonedeck.protocol.frame import HEADER_SIZE, MAX_FRAME_SIZE, decode_frame, encode_frame
from phonedeck.protocol.message import (
    MAX_BODY_SIZE,
    REQUEST_ID_SIZE,
    Message,
    MessageKind,
    frame_to_message,
    message_to_frame,
)
from phonedeck.security.crypto import NONCE_SIZE, SEAL_OVERHEAD
from phonedeck.transport.base import TransportClosedError
from phonedeck.transport.memory import InMemoryTransport

KEY = bytes(range(0x00, 0x10))
WRONG_KEY = bytes(range(0x10, 0x20))


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Fail after 2 seconds instead of hanging forever."""
    asyncio.run(asyncio.wait_for(scenario(), timeout=2))


class TapTransport:
    """Records every sent packet, and can rewrite the next one."""

    def __init__(self, inner: InMemoryTransport) -> None:
        self._inner = inner
        self.sent: list[bytes] = []
        self._rewrite: Callable[[bytes], list[bytes]] | None = None

    def rewrite_next(self, rewrite: Callable[[bytes], list[bytes]]) -> None:
        self._rewrite = rewrite

    @property
    def max_packet_size(self) -> int:
        return self._inner.max_packet_size

    async def send(self, packet: bytes) -> None:
        self.sent.append(packet)
        rewrite, self._rewrite = self._rewrite, None
        for out in rewrite(packet) if rewrite else [packet]:
            await self._inner.send(out)

    async def receive(self) -> bytes:
        return await self._inner.receive()

    async def close(self) -> None:
        await self._inner.close()


@dataclass
class Pair:
    client: SecureChannel
    server: SecureChannel
    client_channel: MessageChannel  # the plain channel under the client
    server_channel: MessageChannel  # the plain channel under the server
    client_tap: TapTransport
    server_tap: TapTransport
    client_raw: InMemoryTransport
    server_raw: InMemoryTransport


def make_pair(client_key: bytes = KEY, server_key: bytes = KEY) -> Pair:
    client_raw, server_raw = InMemoryTransport.create_pair()
    client_tap, server_tap = TapTransport(client_raw), TapTransport(server_raw)
    client_channel, server_channel = MessageChannel(client_tap), MessageChannel(server_tap)
    return Pair(
        client=SecureChannel(client_channel, Role.CLIENT, client_key),
        server=SecureChannel(server_channel, Role.SERVER, server_key),
        client_channel=client_channel,
        server_channel=server_channel,
        client_tap=client_tap,
        server_tap=server_tap,
        client_raw=client_raw,
        server_raw=server_raw,
    )


async def connected() -> Pair:
    pair = make_pair()
    await asyncio.gather(pair.client.handshake(), pair.server.handshake())
    return pair


def parse(packet: bytes) -> Message:
    return frame_to_message(decode_frame(packet))


def raw_packet(message: Message) -> bytes:
    return encode_frame(message_to_frame(message))


def flip(packet: bytes, index: int, mask: int = 0x01) -> bytes:
    changed = bytearray(packet)
    changed[index] ^= mask
    return bytes(changed)


# --- The protocol values are fixed. ---


def test_the_handshake_step_values_are_fixed() -> None:
    assert int(HandshakeStep.CLIENT_HELLO) == 1
    assert int(HandshakeStep.SERVER_HELLO) == 2
    assert int(HandshakeStep.CLIENT_CONFIRM) == 3
    assert int(HandshakeStep.SERVER_CONFIRM) == 4


def test_the_handshake_messages_have_the_agreed_shape() -> None:
    async def scenario() -> None:
        pair = await connected()
        hello, reply = parse(pair.client_tap.sent[0]), parse(pair.server_tap.sent[0])
        client_confirm, server_confirm = (
            parse(pair.client_tap.sent[1]),
            parse(pair.server_tap.sent[1]),
        )

        for message in (hello, reply, client_confirm, server_confirm):
            assert message.kind == MessageKind.HANDSHAKE
            assert message.request_id == 0
        assert (hello.body[0], len(hello.body)) == (HandshakeStep.CLIENT_HELLO, 1 + NONCE_SIZE)
        assert (reply.body[0], len(reply.body)) == (HandshakeStep.SERVER_HELLO, 1 + NONCE_SIZE)
        assert hello.body[1:] != reply.body[1:]  # two different random nonces
        assert (client_confirm.body[0], len(client_confirm.body)) == (
            HandshakeStep.CLIENT_CONFIRM,
            1 + SEAL_OVERHEAD,
        )
        assert (server_confirm.body[0], len(server_confirm.body)) == (
            HandshakeStep.SERVER_CONFIRM,
            1 + SEAL_OVERHEAD,
        )

    run(scenario)


# --- Normal use after the handshake. ---


@pytest.mark.parametrize("kind", [MessageKind.COMMAND, MessageKind.QUERY, MessageKind.RESPONSE])
def test_a_message_arrives_unchanged_in_both_directions(kind: MessageKind) -> None:
    async def scenario() -> None:
        pair = await connected()
        to_server = Message(kind, 7, b"open:notepad")
        to_client = Message(kind, 65535, b"\x00\x25")

        await pair.client.send(to_server)
        assert await pair.server.receive() == to_server
        await pair.server.send(to_client)
        assert await pair.client.receive() == to_client

    run(scenario)


def test_messages_arrive_in_order() -> None:
    async def scenario() -> None:
        pair = await connected()
        sent = [Message(MessageKind.QUERY, i, b"ram") for i in range(20)]

        for message in sent:
            await pair.client.send(message)
        received = [await pair.server.receive() for _ in sent]

        assert received == sent

    run(scenario)


def test_the_same_message_sent_twice_looks_different_on_the_wire() -> None:
    async def scenario() -> None:
        pair = await connected()
        message = Message(MessageKind.QUERY, 1, b"cpu")

        await pair.client.send(message)
        await pair.client.send(message)

        assert pair.client_tap.sent[2] != pair.client_tap.sent[3]  # [0] and [1] are the handshake

    run(scenario)


def test_nothing_readable_travels_over_the_wire() -> None:
    async def scenario() -> None:
        pair = await connected()

        await pair.client.send(Message(MessageKind.COMMAND, 1, b"lock"))
        await pair.server.receive()
        await pair.server.send(Message(MessageKind.RESPONSE, 1, b"a private answer"))
        await pair.client.receive()

        wire = b"".join(pair.client_tap.sent + pair.server_tap.sent)
        assert b"lock" not in wire
        assert b"a private answer" not in wire
        assert KEY not in wire
        # The packet is the plain one plus the counter and the tag.
        expected = HEADER_SIZE + REQUEST_ID_SIZE + len(b"lock") + SEAL_OVERHEAD
        assert len(pair.client_tap.sent[2]) == expected

    run(scenario)


def test_the_largest_body_fits_in_one_ble_write() -> None:
    async def scenario() -> None:
        pair = await connected()
        message = Message(MessageKind.RESPONSE, 1, b"x" * (MAX_BODY_SIZE - SEAL_OVERHEAD))

        await pair.client.send(message)

        assert await pair.server.receive() == message
        assert len(pair.client_tap.sent[2]) == MAX_FRAME_SIZE

    run(scenario)


def test_a_body_that_is_too_large_is_refused_and_nothing_is_sent() -> None:
    async def scenario() -> None:
        pair = await connected()
        sent_before = len(pair.client_tap.sent)

        with pytest.raises(SecureChannelError):
            await pair.client.send(
                Message(MessageKind.RESPONSE, 1, b"x" * (MAX_BODY_SIZE - SEAL_OVERHEAD + 1))
            )

        assert len(pair.client_tap.sent) == sent_before

    run(scenario)


def test_nothing_can_be_sent_or_received_before_the_handshake() -> None:
    async def scenario() -> None:
        pair = make_pair()

        with pytest.raises(SecureChannelError):
            await pair.client.send(Message(MessageKind.QUERY, 1, b"cpu"))
        with pytest.raises(SecureChannelError):
            await pair.client.receive()
        assert pair.client_tap.sent == []

    run(scenario)


def test_a_handshake_message_cannot_be_sent_as_data() -> None:
    async def scenario() -> None:
        pair = await connected()

        with pytest.raises(SecureChannelError):
            await pair.client.send(Message(MessageKind.HANDSHAKE, 0, b"\x01"))

    run(scenario)


# --- A handshake that must fail. ---


def test_a_wrong_pairing_key_fails_the_handshake() -> None:
    async def scenario() -> None:
        pair = make_pair(client_key=KEY, server_key=WRONG_KEY)

        client_result, server_result = await asyncio.gather(
            pair.client.handshake(), pair.server.handshake(), return_exceptions=True
        )

        assert isinstance(server_result, HandshakeError)
        assert isinstance(client_result, HandshakeError | TransportClosedError)

    run(scenario)


def test_a_command_in_the_clear_before_the_handshake_is_refused() -> None:
    async def scenario() -> None:
        pair = make_pair()
        await pair.client_channel.send(Message(MessageKind.COMMAND, 1, b"lock"))

        with pytest.raises(HandshakeError):
            await pair.server.handshake()
        with pytest.raises(TransportClosedError):  # the server hung up on the intruder
            await pair.client_channel.receive()

    run(scenario)


def test_a_hello_with_a_nonce_of_the_wrong_size_is_refused() -> None:
    async def scenario() -> None:
        pair = make_pair()
        hello = bytes([HandshakeStep.CLIENT_HELLO]) + b"short"
        await pair.client_channel.send(Message(MessageKind.HANDSHAKE, 0, hello))

        with pytest.raises(HandshakeError):
            await pair.server.handshake()

    run(scenario)


def test_the_wrong_handshake_step_is_refused() -> None:
    async def scenario() -> None:
        pair = make_pair()
        confirm_first = bytes([HandshakeStep.CLIENT_CONFIRM]) + bytes(NONCE_SIZE)
        await pair.client_channel.send(Message(MessageKind.HANDSHAKE, 0, confirm_first))

        with pytest.raises(HandshakeError):
            await pair.server.handshake()

    run(scenario)


def test_garbage_during_the_handshake_is_refused() -> None:
    async def scenario() -> None:
        pair = make_pair()
        await pair.client_raw.send(b"garbage")

        with pytest.raises(HandshakeError):
            await pair.server.handshake()

    run(scenario)


def test_the_client_refuses_a_wrong_reply_from_the_server() -> None:
    async def scenario() -> None:
        pair = make_pair()

        async def evil_server() -> None:
            await pair.server_channel.receive()  # the hello
            wrong = bytes([HandshakeStep.SERVER_CONFIRM]) + bytes(NONCE_SIZE)
            await pair.server_channel.send(Message(MessageKind.HANDSHAKE, 0, wrong))

        client_result, _ = await asyncio.gather(
            pair.client.handshake(), evil_server(), return_exceptions=True
        )

        assert isinstance(client_result, HandshakeError)

    run(scenario)


# --- An attacker after the handshake. The connection must be closed. ---


async def assert_closed_after_refusing(receiver: SecureChannel, other: SecureChannel) -> None:
    """The receiver refuses the message, then both sides see a closed channel."""
    with pytest.raises(SecureChannelError):
        await receiver.receive()
    with pytest.raises(TransportClosedError):
        await receiver.receive()
    with pytest.raises(TransportClosedError):
        await other.receive()


def test_a_changed_byte_in_the_body_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()
        pair.client_tap.rewrite_next(lambda packet: [flip(packet, len(packet) - 1)])

        await pair.client.send(Message(MessageKind.COMMAND, 1, b"lock"))

        await assert_closed_after_refusing(pair.server, pair.client)

    run(scenario)


def test_a_changed_request_id_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()
        request_id_low_byte = HEADER_SIZE + 1
        pair.client_tap.rewrite_next(lambda packet: [flip(packet, request_id_low_byte)])

        await pair.client.send(Message(MessageKind.COMMAND, 1, b"lock"))

        await assert_closed_after_refusing(pair.server, pair.client)

    run(scenario)


def test_a_changed_message_kind_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()
        kind_byte = 1  # in the frame header; this turns COMMAND (1) into QUERY (2)
        pair.client_tap.rewrite_next(lambda packet: [flip(packet, kind_byte, mask=0x03)])

        await pair.client.send(Message(MessageKind.COMMAND, 1, b"lock"))

        await assert_closed_after_refusing(pair.server, pair.client)

    run(scenario)


def test_a_repeated_message_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()
        message = Message(MessageKind.COMMAND, 1, b"lock")
        pair.client_tap.rewrite_next(lambda packet: [packet, packet])  # the attacker repeats it

        await pair.client.send(message)

        assert await pair.server.receive() == message  # the first one is fine
        await assert_closed_after_refusing(pair.server, pair.client)

    run(scenario)


def test_an_old_message_cannot_be_replayed_later() -> None:
    async def scenario() -> None:
        pair = await connected()
        await pair.client.send(Message(MessageKind.COMMAND, 1, b"lock"))
        await pair.client.send(Message(MessageKind.QUERY, 2, b"cpu"))
        await pair.server.receive()
        await pair.server.receive()
        old_packet = pair.client_tap.sent[2]  # the first data message ([0] and [1] are handshake)

        await pair.client_raw.send(old_packet)  # the attacker sends it again, much later

        await assert_closed_after_refusing(pair.server, pair.client)

    run(scenario)


def test_a_command_in_the_clear_after_the_handshake_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()

        await pair.client_raw.send(raw_packet(Message(MessageKind.COMMAND, 1, b"lock")))

        await assert_closed_after_refusing(pair.server, pair.client)

    run(scenario)


def test_a_message_reflected_back_to_its_sender_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()
        await pair.client.send(Message(MessageKind.QUERY, 1, b"cpu"))
        assert await pair.server.receive() == Message(MessageKind.QUERY, 1, b"cpu")
        mine = pair.client_tap.sent[2]

        await pair.server_raw.send(mine)  # the attacker sends the client's own message back to it

        await assert_closed_after_refusing(pair.client, pair.server)

    run(scenario)


def test_a_handshake_message_after_the_handshake_is_refused() -> None:
    async def scenario() -> None:
        pair = await connected()
        hello = bytes([HandshakeStep.SERVER_HELLO]) + bytes(NONCE_SIZE)

        await pair.server_raw.send(raw_packet(Message(MessageKind.HANDSHAKE, 0, hello)))

        await assert_closed_after_refusing(pair.client, pair.server)

    run(scenario)
