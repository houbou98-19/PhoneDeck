"""The interface between PhoneDeck and the computer it controls."""

from enum import Enum
from typing import Protocol


class SystemControlError(Exception):
    """Raised when the computer could not do what was asked (for example, locking failed)."""


class MediaKey(Enum):
    """What a media key on a keyboard does."""

    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    PREVIOUS = "previous"


class SystemControl(Protocol):
    """What PhoneDeck can read from and do to the computer.

    A real Windows implementation and a fake for tests both satisfy this interface.
    """

    def cpu_percent(self) -> int:
        """CPU load as a whole number, 0-100."""
        ...

    def ram_percent(self) -> int:
        """Memory in use as a whole number, 0-100."""
        ...

    def lock_screen(self) -> None:
        """Lock the computer. Raise SystemControlError if it could not be locked."""
        ...

    def start_spotify(self) -> None:
        """Start Spotify (or bring it up if it runs). Raise SystemControlError if it cannot."""
        ...

    async def spotify_running(self) -> bool:
        """Whether Spotify is running now. Raise SystemControlError if that cannot be read."""
        ...

    async def control_spotify(self, key: MediaKey) -> None:
        """Do what the media key says, to Spotify only (not to whatever else is playing).

        This one is async, since it asks another program and waits for the answer. Raise
        SystemControlError if Spotify is not there or does not accept it.
        """
        ...
