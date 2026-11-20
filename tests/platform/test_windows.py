"""Tests for the Windows platform code. Calls into Windows are replaced, so nothing is locked.

The last section calls the real, read-only functions and runs on Windows only.
"""

import asyncio
import sys
import time

import pytest

from phonedeck.platform import windows
from phonedeck.platform.base import MediaKey, SystemControl, SystemControlError
from phonedeck.platform.windows import WindowsSystemControl, cpu_percent_from_times

# --- The percent calculation (a pure function). ---


@pytest.mark.parametrize(
    ("idle", "kernel", "user", "expected"),
    [
        (100, 100, 0, 0),  # all idle time: 0 % busy
        (0, 50, 50, 100),  # no idle time: 100 % busy
        (50, 100, 0, 50),  # half the time idle
        (50, 100, 50, 67),  # busy = 150 - 50 = 100 of 150 = 66.7, rounds to 67
        (1, 3, 0, 67),  # same ratio, small numbers
    ],
)
def test_cpu_percent_from_times(idle: int, kernel: int, user: int, expected: int) -> None:
    assert cpu_percent_from_times(idle, kernel, user) == expected


def test_no_time_passed_gives_zero_not_a_crash() -> None:
    assert cpu_percent_from_times(0, 0, 0) == 0


@pytest.mark.parametrize(("idle", "kernel", "user"), [(200, 100, 0), (-5, 10, 10), (0, -10, 5)])
def test_odd_counters_are_clamped_to_0_100(idle: int, kernel: int, user: int) -> None:
    assert 0 <= cpu_percent_from_times(idle, kernel, user) <= 100


# --- The class, with the Windows calls replaced. ---


def fake_clock(
    monkeypatch: pytest.MonkeyPatch, samples: list[tuple[int, int, int]]
) -> list[tuple[int, int, int]]:
    """Make _system_times() return the given samples, one per call. Return the unused rest."""
    remaining = list(samples)
    monkeypatch.setattr(windows, "_system_times", lambda: remaining.pop(0))
    return remaining


def test_cpu_percent_compares_with_the_previous_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, [(100, 300, 100), (150, 400, 150)])  # at creation, then at the call
    control = WindowsSystemControl()

    # Differences: idle 50, kernel 100, user 50 -> busy 100 of 150 -> 67 %.
    assert control.cpu_percent() == 67


def test_each_cpu_call_measures_since_the_call_before(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(
        monkeypatch,
        [
            (0, 0, 0),  # at creation
            (50, 100, 0),  # first call: 50 idle of 100 -> 50 %
            (150, 200, 0),  # second call: since the first, 100 idle of 100 -> 0 %
        ],
    )
    control = WindowsSystemControl()

    assert control.cpu_percent() == 50
    assert control.cpu_percent() == 0


def test_cpu_percent_is_zero_if_no_time_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_clock(monkeypatch, [(10, 20, 5), (10, 20, 5)])
    control = WindowsSystemControl()

    assert control.cpu_percent() == 0


def test_ram_percent_is_the_memory_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_memory_load", lambda: 61)

    assert WindowsSystemControl().ram_percent() == 61


def test_lock_screen_asks_windows_to_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def accepting_lock() -> bool:
        calls.append("lock")
        return True

    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_lock_workstation", accepting_lock)

    WindowsSystemControl().lock_screen()

    assert calls == ["lock"]


def test_lock_screen_raises_if_windows_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_lock_workstation", lambda: False)

    with pytest.raises(SystemControlError):
        WindowsSystemControl().lock_screen()


def test_start_spotify_asks_windows_to_start_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def accepting_start() -> bool:
        calls.append("spotify")
        return True

    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_start_spotify", accepting_start)

    WindowsSystemControl().start_spotify()

    assert calls == ["spotify"]


def test_start_spotify_raises_if_windows_cannot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_start_spotify", lambda: False)

    with pytest.raises(SystemControlError):
        WindowsSystemControl().start_spotify()


@pytest.mark.parametrize("has_session", [True, False])
def test_spotify_runs_when_it_has_a_media_session(
    monkeypatch: pytest.MonkeyPatch, has_session: bool
) -> None:
    async def find_session() -> object | None:
        return object() if has_session else None

    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_spotify_session", find_session)

    assert asyncio.run(WindowsSystemControl().spotify_running()) is has_session


@pytest.mark.parametrize("key", list(MediaKey))
def test_control_spotify_passes_the_key_to_the_media_session(
    monkeypatch: pytest.MonkeyPatch, key: MediaKey
) -> None:
    received: list[MediaKey] = []

    async def accepting_session(received_key: MediaKey) -> bool:
        received.append(received_key)
        return True

    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_control_spotify", accepting_session)

    asyncio.run(WindowsSystemControl().control_spotify(key))

    assert received == [key]


def test_control_spotify_raises_if_spotify_does_not_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refusing_session(key: MediaKey) -> bool:
        return False

    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))
    monkeypatch.setattr(windows, "_control_spotify", refusing_session)

    with pytest.raises(SystemControlError):
        asyncio.run(WindowsSystemControl().control_spotify(MediaKey.NEXT))


def test_it_fits_the_system_control_interface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "_system_times", lambda: (0, 0, 0))

    _: SystemControl = WindowsSystemControl()  # mypy checks that it fits


# --- The real Windows functions (read-only, never locks). ---

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")


@on_windows
def test_real_system_times_are_three_growing_counters() -> None:
    first = windows._system_times()
    time.sleep(0.05)
    second = windows._system_times()

    assert len(first) == 3
    assert all(isinstance(value, int) for value in first)
    assert all(later >= earlier for earlier, later in zip(first, second, strict=True))
    assert first[1] >= first[0]  # the kernel time includes the idle time


@on_windows
def test_real_ram_percent_is_a_percent() -> None:
    percent = WindowsSystemControl().ram_percent()

    assert isinstance(percent, int)
    assert 0 < percent <= 100


@on_windows
def test_real_cpu_percent_is_a_percent() -> None:
    control = WindowsSystemControl()
    time.sleep(0.2)

    percent = control.cpu_percent()

    assert isinstance(percent, int)
    assert 0 <= percent <= 100


@on_windows
def test_enabling_ansi_colours_does_not_fail_even_when_there_is_no_console() -> None:
    windows.enable_ansi_colors()  # under pytest the output is captured, so there is no console
