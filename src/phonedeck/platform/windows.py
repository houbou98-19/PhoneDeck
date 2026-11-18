"""SystemControl for Windows: read CPU and RAM load, lock the screen, and control Spotify.

The functions that call Windows (mostly through ctypes) are small and private. The rest is
plain Python, so it can be tested by replacing those.
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
    """The form that Windows fills in for GlobalMemoryStatusEx (the order of fields matters)."""

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
    """Convert a Windows FILETIME to an integer (number of 100-nanosecond intervals)."""
    return ft.dwLowDateTime + (ft.dwHighDateTime << 32)


def _system_times() -> tuple[int, int, int]:
    """Return (idle, kernel, user): CPU time since boot, as three growing counters.

    Windows: kernel32.GetSystemTimes. Note that the kernel time INCLUDES the idle time.
    """
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
    """Return how much memory is in use, as a percent (0-100).

    Windows: kernel32.GlobalMemoryStatusEx, the dwMemoryLoad field of MEMORYSTATUSEX.
    """
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    get_memory_status = ctypes.WinDLL("kernel32").GlobalMemoryStatusEx
    get_memory_status.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
    get_memory_status.restype = wintypes.BOOL
    if not get_memory_status(ctypes.byref(status)):
        raise SystemControlError("Windows could not read memory status")
    return int(status.dwMemoryLoad)


def _lock_workstation() -> bool:
    """Lock the computer. Return True if Windows accepted it, False if it refused.

    Windows: user32.LockWorkStation (it returns 0 on failure).
    """
    lock_workstation = ctypes.WinDLL("user32").LockWorkStation
    lock_workstation.argtypes = []
    lock_workstation.restype = wintypes.BOOL
    return bool(lock_workstation())


def _start_spotify() -> bool:
    """Start Spotify. Return True if Windows started it, False if it could not.

    Windows: os.startfile("spotify:") hands the address to whatever program is registered for the
    spotify: scheme, which is what happens when a spotify: link is clicked in a browser. If Spotify
    is not installed nothing is registered, and Windows raises OSError.
    """
    try:
        os.startfile("spotify:")
    except OSError:
        return False
    return True


async def _spotify_session() -> Session | None:
    """Spotify's media session, or None if Spotify is not running.

    Windows keeps a media session for every program that plays media (Spotify, a browser tab...).
    Spotify's session appears when Spotify starts and goes away when it closes, so it also tells
    whether Spotify runs.
    """
    manager = await SessionManager.request_async()
    for session in manager.get_sessions():
        if session.source_app_user_model_id.lower().startswith("spotify"):
            return session
    return None


async def _control_spotify(key: MediaKey) -> bool:
    """Do what the media key says, to Spotify's own media session. Return whether it worked.

    A media key on the keyboard goes to whichever session Windows thinks is current, which is not
    always Spotify, so this asks Spotify's session directly. False means that Spotify has no
    session (it is not running) or that it did not accept the request.
    """
    session = await _spotify_session()
    if session is None:
        return False
    if key == MediaKey.PLAY_PAUSE:
        return bool(await session.try_toggle_play_pause_async())
    if key == MediaKey.NEXT:
        return bool(await session.try_skip_next_async())
    return bool(await session.try_skip_previous_async())


def enable_ansi_colors() -> None:
    """Make the Windows console understand colour codes, so that the QR code is black on white.

    Windows: kernel32.SetConsoleMode with ENABLE_VIRTUAL_TERMINAL_PROCESSING. Windows Terminal
    and the VS Code terminal already do, an older console window does not until asked. If the
    output is not a console (a file, a pipe), there is nothing to do.
    """
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
    """Turn the CPU time that passed between two samples into a load percent, 0-100.

    The three numbers are differences between two samples (later minus earlier).
    The kernel time includes the idle time, so: total = kernel + user, busy = total - idle.
    Round to the nearest whole number. If no time passed (total is 0), the answer is 0.
    Never return below 0 or above 100, even if the counters behave oddly.
    """
    total = kernel + user
    busy = total - idle
    if total == 0:
        return 0
    percent = round(busy * 100 / total)
    return max(0, min(100, percent))


class WindowsSystemControl:
    """The real computer. Satisfies phonedeck.platform.base.SystemControl.

    cpu_percent() answers with the load since the PREVIOUS call (the first call: since the
    object was created). It never waits or sleeps, since it runs inside the event loop.
    If no time passed since the previous call, it answers 0.
    """

    def __init__(self) -> None:
        self._last = _system_times()

    def cpu_percent(self) -> int:
        """CPU load as a whole number, 0-100, since the previous call."""
        idle, kernel, user = _system_times()
        last_idle, last_kernel, last_user = self._last

        percent = cpu_percent_from_times(idle - last_idle, kernel - last_kernel, user - last_user)
        self._last = (idle, kernel, user)
        return percent

    def ram_percent(self) -> int:
        """Memory in use as a whole number, 0-100."""
        return _memory_load()

    def lock_screen(self) -> None:
        """Lock the computer. Raise SystemControlError if Windows refuses."""
        if not _lock_workstation():
            raise SystemControlError("Windows refused to lock the screen")

    def start_spotify(self) -> None:
        """Start Spotify. Raise SystemControlError if Windows cannot (is it installed?)."""
        if not _start_spotify():
            raise SystemControlError("Windows could not start Spotify")

    async def spotify_running(self) -> bool:
        """Whether Spotify is running (it has a media session)."""
        return await _spotify_session() is not None

    async def control_spotify(self, key: MediaKey) -> None:
        """Play/pause, next or previous, on Spotify. Raise SystemControlError if it did not work."""
        if not await _control_spotify(key):
            raise SystemControlError("Spotify did not accept the media request (is it running?)")
