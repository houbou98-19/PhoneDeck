"""Handler: turns a request from the phone into a response, using the computer."""

from collections.abc import Awaitable, Callable
from enum import IntEnum
from functools import partial

from phonedeck.platform.base import MediaKey, SystemControl, SystemControlError
from phonedeck.protocol.message import Message, MessageError, MessageKind


class ResponseStatus(IntEnum):
    """The first byte of a RESPONSE body. The values are part of the protocol."""

    OK = 0
    UNKNOWN_ACTION = 1
    FAILED = 2


def _awaitable[T](function: Callable[[], T]) -> Callable[[], Awaitable[T]]:
    """Wrap a quick, ordinary function so it can be awaited like the ones that really wait."""

    async def call() -> T:
        return function()

    return call


class Handler:
    """Answers COMMAND and QUERY messages.

    The response body is | status (1 byte) | data (the rest) |, and it carries the same
    request_id as the request.

    Actions, by name (the name is the UTF-8 text in the request body):
      QUERY    "cpu"   -> OK, data = 1 byte, percent 0-100
      QUERY    "ram"   -> OK, data = 1 byte, percent 0-100
      QUERY    "spotify" -> OK, data = 1 byte: 1 if Spotify runs, otherwise 0
      COMMAND  "lock"  -> OK, no data
      COMMAND  "spotify" -> OK, no data (Spotify is started, or brought up if it runs)
      COMMAND  "media_play_pause", "media_next", "media_previous" -> OK, no data (done to
               Spotify only, FAILED if Spotify is not there)
    Anything else (unknown name, or a known name used with the wrong kind) gives
    UNKNOWN_ACTION with no data, and does nothing. The phone never sends something that
    is executed, it only picks a name from this list (an allowlist).

    If the computer fails (SystemControlError) the status is FAILED with no data.

    """

    def __init__(self, system: SystemControl) -> None:
        # The allowlist: a name the phone may send, and what it runs. Nothing else can run.
        # Every entry can be awaited. The quick ones (plain functions) are wrapped by _awaitable,
        # the ones that really wait for another program (media) are async already.
        async def spotify_runs() -> bytes:
            return bytes([await system.spotify_running()])  # 1 if it runs, otherwise 0

        self._queries: dict[bytes, Callable[[], Awaitable[bytes]]] = {
            b"cpu": _awaitable(lambda: bytes([system.cpu_percent()])),
            b"ram": _awaitable(lambda: bytes([system.ram_percent()])),
            b"spotify": spotify_runs,
        }
        self._commands: dict[bytes, Callable[[], Awaitable[None]]] = {
            b"lock": _awaitable(system.lock_screen),
            b"spotify": _awaitable(system.start_spotify),
            b"media_play_pause": partial(system.control_spotify, MediaKey.PLAY_PAUSE),
            b"media_next": partial(system.control_spotify, MediaKey.NEXT),
            b"media_previous": partial(system.control_spotify, MediaKey.PREVIOUS),
        }

    async def handle(self, request: Message) -> Message:
        """Answer one request.

        Raise MessageError if the request is not a COMMAND or a QUERY, since those are the
        only kinds the phone may ask with.
        """
        name = request.body
        if request.kind == MessageKind.QUERY:
            read = self._queries.get(name)
            if read is None:
                return self._respond(request, ResponseStatus.UNKNOWN_ACTION)
            try:
                data = await read()
            except SystemControlError:
                return self._respond(request, ResponseStatus.FAILED)
            return self._respond(request, ResponseStatus.OK, data)
        elif request.kind == MessageKind.COMMAND:
            run = self._commands.get(name)
            if run is None:
                return self._respond(request, ResponseStatus.UNKNOWN_ACTION)
            try:
                await run()
            except SystemControlError:
                return self._respond(request, ResponseStatus.FAILED)
            return self._respond(request, ResponseStatus.OK)
        else:
            raise MessageError(f"Unexpected message kind: {request.kind}")

    @staticmethod
    def _respond(request: Message, status: ResponseStatus, data: bytes = b"") -> Message:
        """A RESPONSE to this request: the status byte, then the data."""
        return Message(
            MessageKind.RESPONSE,
            request_id=request.request_id,
            body=bytes([status]) + data,
        )
