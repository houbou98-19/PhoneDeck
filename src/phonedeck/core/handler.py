"""Handler: turns a request from the phone into a response, using the computer."""

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
        self._system = system

    def handle(self, request: Message) -> Message:
        """Answer one request.

        Raise MessageError if the request is not a COMMAND or a QUERY, since those are the
        only kinds the phone may ask with.
        """
        kind = request.kind
        name = request.body
        if kind == MessageKind.QUERY:
            if name == b"cpu":
                percent = self._system.cpu_percent()
                return Message(
                    MessageKind.RESPONSE,
                    request_id=request.request_id,
                    body=bytes([ResponseStatus.OK, percent]),
                )
            elif name == b"ram":
                percent = self._system.ram_percent()
                return Message(
                    MessageKind.RESPONSE,
                    request_id=request.request_id,
                    body=bytes([ResponseStatus.OK, percent]),
                )
            else:
                return Message(
                    MessageKind.RESPONSE,
                    request_id=request.request_id,
                    body=bytes([ResponseStatus.UNKNOWN_ACTION]),
                )
        elif kind == MessageKind.COMMAND:
            if name == b"lock":
                try:
                    self._system.lock_screen()
                except SystemControlError:
                    return Message(
                        MessageKind.RESPONSE,
                        request_id=request.request_id,
                        body=bytes([ResponseStatus.FAILED]),
                    )
                return Message(
                    MessageKind.RESPONSE,
                    request_id=request.request_id,
                    body=bytes([ResponseStatus.OK]),
                )
            else:
                return Message(
                    MessageKind.RESPONSE,
                    request_id=request.request_id,
                    body=bytes([ResponseStatus.UNKNOWN_ACTION]),
                )
        else:
            raise MessageError(f"Unexpected message kind: {kind}")
