"""SecureChannel: the handshake, and messages that are encrypted and checked.

A SecureChannel sits on top of a MessageChannel. Before the handshake nothing can be sent or
received. After it, send() and receive() work like on a MessageChannel, but the body of every
message is encrypted, and nothing that is not authentic gets through.

The same protocol runs on the phone (the CLIENT, in JavaScript) and on the computer (the SERVER,
here), so the tests run both roles in Python against each other.

THE HANDSHAKE. Four HANDSHAKE messages, all with request_id 0. The body of each is
| step (1 byte, a HandshakeStep) | data |

  1. CLIENT_HELLO    client -> server   data: the client's nonce (NONCE_SIZE bytes, in the clear)
  2. SERVER_HELLO    server -> client   data: the server's nonce (NONCE_SIZE bytes, in the clear)
     Both sides now run derive_session_keys(pairing_key, client_nonce, server_nonce).
  3. CLIENT_CONFIRM  client -> server   data: seal(client_to_server, counter 0, aad, b"")
  4. SERVER_CONFIRM  server -> client   data: seal(server_to_client, counter 0, aad, b"")
     Here aad is the one every sealed message uses, see _aad() below.

Step 3 proves to the server that the client has the pairing key, and step 4 proves it the other
way. A side that gets a wrong message (the wrong step, a nonce of the wrong size, anything
that is not a HANDSHAKE, garbage, a confirm that does not open or has the wrong counter) closes
the underlying channel and raises HandshakeError. If the transport closes during the handshake,
TransportClosedError is raised as it is. After step 4 each side sends with its own direction's
key (the client with client_to_server, the server with server_to_client).

AFTER THE HANDSHAKE. send(message) turns the body into
    seal(send_key, counter, aad, body)   with aad = _aad(message.kind, message.request_id)
and sends Message(kind, request_id, that). The counters start at 1 (0 was used by the confirm)
and go up by one for every message sent. receive() does the opposite, with open_sealed().

  * The kind and request id are visible but authenticated (they are the aad): change one on the
    way, and the message is refused.
  * receive() refuses a counter that is not larger than the last one it accepted (a replay).
  * Anything that fails (a message that does not open, a replay, a HANDSHAKE message, a message in
    the clear) closes the underlying channel and raises SecureChannelError. After that, every
    call raises TransportClosedError, because the channel is closed.
  * Garbage (FrameError) and unknown kinds (MessageError) from the layer below are not hidden:
    they pass through, and the channel stays usable, like on a MessageChannel.
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
    """The additional authenticated data of a message: the kind (1 byte), then the request id
    (2 bytes, big-endian). It is not encrypted, but a change to it breaks the check.
    """
    return kind.to_bytes(1, "big") + request_id.to_bytes(2, "big")


class SecureChannel:
    """Wraps a MessageChannel so that messages are encrypted and checked. See the module text."""

    def __init__(self, channel: MessageChannel, role: Role, pairing_key: bytes) -> None:
        """Remember the channel, the role, and the pairing key."""
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
        """Encrypt and send one message.

        Raise SecureChannelError if the handshake is not done, if the kind is HANDSHAKE, or if
        the body is longer than MAX_BODY_SIZE - SEAL_OVERHEAD (then nothing is sent). A bad
        request id raises MessageError, as on a MessageChannel.
        """
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
        """Wait for the next message, check it, decrypt it, and return it.

        Raise SecureChannelError if the handshake is not done, or if the message is not
        trustworthy (see the module text; the channel is then closed).
        """
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
        """Check the data of a CONFIRM: it must open with `key`, with counter 0 and no text."""
        try:
            counter, plaintext = open_sealed(key, _aad(MessageKind.HANDSHAKE, 0), body)
        except CryptoError:
            await self._fail_handshake("The CONFIRM failed its authentication check")
        if counter != 0 or plaintext != b"":
            await self._fail_handshake("The CONFIRM has the wrong counter or content")
