"""SystemControl for Windows: CPU and RAM load, locking, and Spotify.

The private functions that call Windows are small, so the rest can be tested by replacing them.
"""

import ctypes
import os
from ctypes import wintypes

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSession as Session,
)
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
)

from phonedeck.platform.base import MediaKey, SystemControlError


class MEMORYSTATUSEX(ctypes.Structure):
    """What GlobalMemoryStatusEx fills in. The order of the fields matters."""

    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _filetime_to_int(ft: wintypes.FILETIME) -> int:
    """A FILETIME as an integer, in 100-nanosecond steps."""
    return ft.dwLowDateTime + (ft.dwHighDateTime << 32)


def _system_times() -> tuple[int, int, int]:
    """(idle, kernel, user) CPU time since boot, from GetSystemTimes. Kernel includes idle."""
    status = (wintypes.FILETIME * 3)()
    get_system_times = ctypes.WinDLL("kernel32").GetSystemTimes
    get_system_times.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
    get_system_times.restype = wintypes.BOOL
    if not get_system_times(*status):
        raise SystemControlError("Windows could not read CPU times")
    idle = _filetime_to_int(status[0])
    kernel = _filetime_to_int(status[1])
    user = _filetime_to_int(status[2])
    return idle, kernel, user


def _memory_load() -> int:
    """Memory in use as a percent, from GlobalMemoryStatusEx."""
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    get_memory_status = ctypes.WinDLL("kernel32").GlobalMemoryStatusEx
    get_memory_status.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    get_memory_status.restype = wintypes.BOOL
    if not get_memory_status(ctypes.byref(status)):
        raise SystemControlError("Windows could not read memory status")
    return int(status.dwMemoryLoad)


def _lock_workstation() -> bool:
    """LockWorkStation. True if Windows accepted it."""
    lock_workstation = ctypes.WinDLL("user32").LockWorkStation
    lock_workstation.argtypes = []
    lock_workstation.restype = wintypes.BOOL
    return bool(lock_workstation())


def _start_spotify() -> bool:
    """Open the spotify: link, like clicking one in a browser. False if Spotify is not installed."""
    try:
        os.startfile("spotify:")
    except OSError:
        return False
    return True


async def _spotify_session() -> Session | None:
    """Spotify's Windows media session. It exists while Spotify runs, so None means not running."""
    manager = await SessionManager.request_async()
    for session in manager.get_sessions():
        if session.source_app_user_model_id.lower().startswith("spotify"):
            return session
    return None


async def _control_spotify(key: MediaKey) -> bool:
    """Send the key to Spotify's own session. A real media key goes to whichever is current."""
    session = await _spotify_session()
    if session is None:
        return False
    if key == MediaKey.PLAY_PAUSE:
        return bool(await session.try_toggle_play_pause_async())
    if key == MediaKey.NEXT:
        return bool(await session.try_skip_next_async())
    return bool(await session.try_skip_previous_async())


def enable_ansi_colors() -> None:
    """Turn on colour codes in the console, so the QR code is black on white."""
    enable_virtual_terminal_processing = 0x0004
    standard_output = -11
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.SetConsoleMode.restype = wintypes.BOOL

    handle = kernel32.GetStdHandle(standard_output)
    mode = wintypes.DWORD()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        kernel32.SetConsoleMode(handle, mode.value | enable_virtual_terminal_processing)


def cpu_percent_from_times(idle: int, kernel: int, user: int) -> int:
    """CPU load, 0-100, from the time that passed between two samples (later minus earlier)."""
    total = kernel + user
    busy = total - idle
    if total == 0:
        return 0
    percent = round(busy * 100 / total)
    return max(0, min(100, percent))


class WindowsSystemControl:
    """The real computer. cpu_percent() is the load since the previous call, and never waits."""

    def __init__(self) -> None:
        self._last = _system_times()

    def cpu_percent(self) -> int:
        idle, kernel, user = _system_times()
        last_idle, last_kernel, last_user = self._last

        percent = cpu_percent_from_times(idle - last_idle, kernel - last_kernel, user - last_user)
        self._last = (idle, kernel, user)
        return percent

    def ram_percent(self) -> int:
        return _memory_load()

    def lock_screen(self) -> None:
        if not _lock_workstation():
            raise SystemControlError("Windows refused to lock the screen")

    def start_spotify(self) -> None:
        if not _start_spotify():
            raise SystemControlError("Windows could not start Spotify")

    async def spotify_running(self) -> bool:
        return await _spotify_session() is not None

    async def control_spotify(self, key: MediaKey) -> None:
        if not await _control_spotify(key):
            raise SystemControlError("Spotify did not accept the media request (is it running?)")
