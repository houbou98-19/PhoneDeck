"""Tests for phonedeck.core.handler.Handler.

The computer is replaced by FakeSystem, so no real CPU is read and nothing is ever locked.
"""

import pytest

from phonedeck.core.handler import Handler, ResponseStatus
from phonedeck.platform.base import SystemControlError
from phonedeck.protocol.message import Message, MessageError, MessageKind


class FakeSystem:
    """A computer that reports fixed values and remembers what it was asked to do."""

    def __init__(self, cpu: int = 37, ram: int = 61, lock_fails: bool = False) -> None:
        self._cpu = cpu
        self._ram = ram
        self._lock_fails = lock_fails
        self.lock_calls = 0

    def cpu_percent(self) -> int:
        return self._cpu

    def ram_percent(self) -> int:
        return self._ram

    def lock_screen(self) -> None:
        self.lock_calls += 1
        if self._lock_fails:
            raise SystemControlError("could not lock")


def ask(handler: Handler, kind: MessageKind, name: bytes, request_id: int = 1) -> Message:
    return handler.handle(Message(kind, request_id, name))


# --- The status values are part of the protocol, so they are pinned. ---


def test_status_values_are_fixed() -> None:
    assert int(ResponseStatus.OK) == 0
    assert int(ResponseStatus.UNKNOWN_ACTION) == 1
    assert int(ResponseStatus.FAILED) == 2


# --- Queries. ---


def test_query_cpu_answers_with_the_cpu_percent() -> None:
    response = ask(Handler(FakeSystem(cpu=37)), MessageKind.QUERY, b"cpu")

    assert response.kind == MessageKind.RESPONSE
    assert response.body == b"\x00\x25"  # status OK, then 37 as one byte


def test_query_ram_answers_with_the_ram_percent() -> None:
    response = ask(Handler(FakeSystem(ram=61)), MessageKind.QUERY, b"ram")

    assert response.body == b"\x00\x3d"  # status OK, then 61 as one byte


@pytest.mark.parametrize("percent", [0, 100])
def test_percent_edge_values_fit_in_one_byte(percent: int) -> None:
    response = ask(Handler(FakeSystem(cpu=percent)), MessageKind.QUERY, b"cpu")

    assert response.body == bytes([ResponseStatus.OK, percent])


# --- Commands. ---


def test_command_lock_locks_the_computer_once() -> None:
    system = FakeSystem()

    response = ask(Handler(system), MessageKind.COMMAND, b"lock")

    assert system.lock_calls == 1
    assert response.kind == MessageKind.RESPONSE
    assert response.body == b"\x00"  # status OK and no data


# --- A response belongs to its request. ---


@pytest.mark.parametrize("request_id", [0, 1, 513, 65535])
def test_the_response_copies_the_request_id(request_id: int) -> None:
    response = ask(Handler(FakeSystem()), MessageKind.QUERY, b"cpu", request_id)

    assert response.request_id == request_id


# --- The allowlist: only known names with the right kind do anything. ---


def test_an_unknown_name_is_refused() -> None:
    system = FakeSystem()

    response = ask(Handler(system), MessageKind.COMMAND, b"format_disk")

    assert response.body == bytes([ResponseStatus.UNKNOWN_ACTION])
    assert system.lock_calls == 0


def test_a_command_name_sent_as_a_query_does_not_run() -> None:
    system = FakeSystem()

    response = ask(Handler(system), MessageKind.QUERY, b"lock")

    assert response.body == bytes([ResponseStatus.UNKNOWN_ACTION])
    assert system.lock_calls == 0


def test_a_query_name_sent_as_a_command_is_refused() -> None:
    response = ask(Handler(FakeSystem()), MessageKind.COMMAND, b"cpu")

    assert response.body == bytes([ResponseStatus.UNKNOWN_ACTION])


@pytest.mark.parametrize("name", [b"", b"LOCK", b"lock ", b"\xff\xfe", b"lock\x00"])
def test_odd_names_are_refused_not_crashed_on(name: bytes) -> None:
    system = FakeSystem()

    response = ask(Handler(system), MessageKind.COMMAND, name)

    assert response.body == bytes([ResponseStatus.UNKNOWN_ACTION])
    assert system.lock_calls == 0


# --- The computer fails. ---


def test_a_failing_computer_gives_status_failed() -> None:
    response = ask(Handler(FakeSystem(lock_fails=True)), MessageKind.COMMAND, b"lock")

    assert response.kind == MessageKind.RESPONSE
    assert response.body == bytes([ResponseStatus.FAILED])


# --- Kinds the phone may not ask with. ---


@pytest.mark.parametrize("kind", [MessageKind.RESPONSE, MessageKind.HANDSHAKE])
def test_only_commands_and_queries_are_accepted(kind: MessageKind) -> None:
    with pytest.raises(MessageError):
        Handler(FakeSystem()).handle(Message(kind, 1, b"cpu"))
