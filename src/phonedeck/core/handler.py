"""Handler: turns a request from the phone into a response, using the computer."""

from collections.abc import Callable
from enum import IntEnum

from phonedeck.platform.base import SystemControl, SystemControlError
from phonedeck.protocol.message import Message, MessageError, MessageKind


class ResponseStatus(IntEnum):
    """The first byte of a RESPONSE body. The values are part of the protocol."""

    OK = 0
    UNKNOWN_ACTION = 1
    FAILED = 2


class Handler:
    """Answers COMMAND and QUERY messages.

    The response body is | status (1 byte) | data (the rest) |, and it carries the same
    request_id as the request.

    Actions, by name (the name is the UTF-8 text in the request body):
      QUERY    "cpu"   -> OK, data = 1 byte, percent 0-100
      QUERY    "ram"   -> OK, data = 1 byte, percent 0-100
      COMMAND  "lock"  -> OK, no data
    Anything else (unknown name, or a known name used with the wrong kind) gives
    UNKNOWN_ACTION with no data, and does nothing. The phone never sends something that
    is executed, it only picks a name from this list (an allowlist).

    If the computer fails (SystemControlError) the status is FAILED with no data.

    """

    def __init__(self, system: SystemControl) -> None:
        # The allowlist: a name the phone may send, and what it runs. Nothing else can run.
        self._queries: dict[bytes, Callable[[], int]] = {
            b"cpu": system.cpu_percent,
            b"ram": system.ram_percent,
        }
        self._commands: dict[bytes, Callable[[], None]] = {
            b"lock": system.lock_screen,
        }

    def handle(self, request: Message) -> Message:
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
                percent = read()
            except SystemControlError:
                return self._respond(request, ResponseStatus.FAILED)
            return self._respond(request, ResponseStatus.OK, bytes([percent]))
        elif request.kind == MessageKind.COMMAND:
            run = self._commands.get(name)
            if run is None:
                return self._respond(request, ResponseStatus.UNKNOWN_ACTION)
            try:
                run()
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
