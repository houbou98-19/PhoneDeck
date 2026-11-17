"""SystemControl for Windows: read CPU and RAM load, and lock the screen.

The three functions that call Windows (through ctypes) are small and private. The rest is
plain Python, so it can be tested by replacing those three.
"""

import ctypes
from ctypes import wintypes

from phonedeck.platform.base import SystemControlError


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
