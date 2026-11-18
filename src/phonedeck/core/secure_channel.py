"""SecureChannel: a handshake with the pairing key, then encrypted and authenticated messages.

The protocol is described in docs/protocol.md. The phone runs the same protocol in web/secure.js.
"""

from enum import Enum, IntEnum
from typing import NoReturn

from phonedeck.core.channel import MessageChannel
from phonedeck.protocol.frame import FrameError
from phonedeck.protocol.message import (
    MAX_BODY_SIZE,
    MAX_REQUEST_ID,
    Message,
    MessageError,
    MessageKind,
)
from phonedeck.security.crypto import (
    NONCE_SIZE,
    SEAL_OVERHEAD,
    CryptoError,
    derive_session_keys,
    new_nonce,
    open_sealed,
    seal,
)


class Role(Enum):
    """Which side of the handshake this channel plays."""

    CLIENT = "client"  # the phone
    SERVER = "server"  # the computer


class HandshakeStep(IntEnum):
    """The first byte of a HANDSHAKE body. The values are part of the protocol."""

    CLIENT_HELLO = 1
    SERVER_HELLO = 2
    CLIENT_CONFIRM = 3
    SERVER_CONFIRM = 4


class SecureChannelError(Exception):
    """Raised when a message cannot be trusted, or the channel is used in the wrong state."""


class HandshakeError(SecureChannelError):
    """Raised when the handshake fails."""


def _aad(kind: MessageKind, request_id: int) -> bytes:
    """The part of a message that is sent in the clear but covered by the check."""
    return kind.to_bytes(1, "big") + request_id.to_bytes(2, "big")


class SecureChannel:
    """Wraps a MessageChannel so that messages are encrypted and checked."""

    def __init__(self, channel: MessageChannel, role: Role, pairing_key: bytes) -> None:
        self._channel = channel
        self._role = role
        self._pairing_key = pairing_key
        self._send_key: bytes | None = None
        self._receive_key: bytes | None = None
        self._send_counter = 1  # 0 used by CONFIRM, so data starts at 1
        self._last_received_counter = 0

    async def _receive_step(self, step: HandshakeStep) -> bytes:
        """Receive one HANDSHAKE message of the given step, and return its data."""
        try:
            message = await self._channel.receive()
        except (FrameError, MessageError) as e:
            await self._fail_handshake(f"Failed to receive message: {e}")

        if message.kind != MessageKind.HANDSHAKE:
            await self._fail_handshake(f"Expected a HANDSHAKE message, got {message.kind}")

        if not message.body:
            await self._fail_handshake("The HANDSHAKE message has no body")

        if message.body[0] != step:
            await self._fail_handshake(f"Expected handshake step {step}, got {message.body[0]}")

        return message.body[1:]

    async def handshake(self) -> None:
        """Run this side of the handshake. Raise HandshakeError if it fails."""
        if self._role is Role.SERVER:
            await self._server_handshake()
        else:
            await self._client_handshake()

    async def _server_handshake(self) -> None:
        client_nonce = await self._receive_step(HandshakeStep.CLIENT_HELLO)
        if len(client_nonce) != NONCE_SIZE:
            await self._fail_handshake(
                f"Client nonce must be {NONCE_SIZE} bytes, got {len(client_nonce)}"
            )
        server_nonce = new_nonce()
        await self._channel.send(
            Message(MessageKind.HANDSHAKE, 0, bytes([HandshakeStep.SERVER_HELLO]) + server_nonce)
        )
        keys = derive_session_keys(self._pairing_key, client_nonce, server_nonce)
        await self._check_confirm(
            keys.client_to_server, await self._receive_step(HandshakeStep.CLIENT_CONFIRM)
        )
        await self._channel.send(
            Message(
                MessageKind.HANDSHAKE,
                0,
                bytes([HandshakeStep.SERVER_CONFIRM])
                + seal(keys.server_to_client, 0, _aad(MessageKind.HANDSHAKE, 0), b""),
            )
        )
        self._send_key = keys.server_to_client
        self._receive_key = keys.client_to_server

    async def _client_handshake(self) -> None:
        client_nonce = new_nonce()
        await self._channel.send(
            Message(MessageKind.HANDSHAKE, 0, bytes([HandshakeStep.CLIENT_HELLO]) + client_nonce)
        )
        server_nonce = await self._receive_step(HandshakeStep.SERVER_HELLO)
        if len(server_nonce) != NONCE_SIZE:
            await self._fail_handshake(
                f"Server nonce must be {NONCE_SIZE} bytes, got {len(server_nonce)}"
            )
        keys = derive_session_keys(self._pairing_key, client_nonce, server_nonce)
        await self._channel.send(
            Message(
                MessageKind.HANDSHAKE,
                0,
                bytes([HandshakeStep.CLIENT_CONFIRM])
                + seal(keys.client_to_server, 0, _aad(MessageKind.HANDSHAKE, 0), b""),
            )
        )
        await self._check_confirm(
            keys.server_to_client, await self._receive_step(HandshakeStep.SERVER_CONFIRM)
        )
        self._send_key = keys.client_to_server
        self._receive_key = keys.server_to_client

    async def send(self, message: Message) -> None:
        """Encrypt and send one message. Nothing is sent if it raises."""
        if self._send_key is None:
            raise SecureChannelError("Cannot send a message before the handshake")
        if message.kind == MessageKind.HANDSHAKE:
            raise SecureChannelError("Cannot send a HANDSHAKE message after the handshake")
        if len(message.body) > MAX_BODY_SIZE - SEAL_OVERHEAD:
            raise SecureChannelError(
                f"Message body too long: {len(message.body)} bytes, max is "
                f"{MAX_BODY_SIZE - SEAL_OVERHEAD}"
            )
        if message.request_id < 0 or message.request_id > MAX_REQUEST_ID:
            raise MessageError(f"Request ID must be 0-{MAX_REQUEST_ID}, got {message.request_id}")

        sealed = seal(
            self._send_key, self._send_counter, _aad(message.kind, message.request_id), message.body
        )
        self._send_counter += 1
        await self._channel.send(Message(message.kind, message.request_id, sealed))

    async def receive(self) -> Message:
        """Wait for the next message and decrypt it. An untrustworthy one closes the channel."""
        if self._receive_key is None:
            raise SecureChannelError("Cannot receive a message before the handshake")
        message = await self._channel.receive()
        if message.kind == MessageKind.HANDSHAKE:
            await self._close_with_error("Received a HANDSHAKE message after the handshake")
        try:
            counter, plaintext = open_sealed(
                self._receive_key, _aad(message.kind, message.request_id), message.body
            )
        except CryptoError:
            await self._close_with_error("Message failed authentication check")
        if counter <= self._last_received_counter:
            await self._close_with_error(
                f"Replay: counter {counter} is not larger than last {self._last_received_counter}"
            )
        self._last_received_counter = counter
        return Message(message.kind, message.request_id, plaintext)

    async def close(self) -> None:
        """Close the underlying channel."""
        await self._channel.close()

    async def _close_with_error(self, error: str) -> NoReturn:
        """Close the underlying channel and raise SecureChannelError with the given message."""
        await self._channel.close()
        raise SecureChannelError(error)

    async def _fail_handshake(self, error: str) -> NoReturn:
        """Close the underlying channel and raise HandshakeError with the given message."""
        await self._channel.close()
        raise HandshakeError(error)

    async def _check_confirm(self, key: bytes, body: bytes) -> None:
        """A CONFIRM must open with `key`, with counter 0 and an empty text."""
        try:
            counter, plaintext = open_sealed(key, _aad(MessageKind.HANDSHAKE, 0), body)
        except CryptoError:
            await self._fail_handshake("The CONFIRM failed its authentication check")
        if counter != 0 or plaintext != b"":
            await self._fail_handshake("The CONFIRM has the wrong counter or content")
