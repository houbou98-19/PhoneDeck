"""The interface between PhoneDeck and the computer it controls."""

from enum import Enum
from typing import Protocol


class SystemControlError(Exception):
    """The computer could not do what was asked."""


class MediaKey(Enum):
    """What a media key on a keyboard does."""

    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    PREVIOUS = "previous"


class SystemControl(Protocol):
    """What PhoneDeck can read from and do to the computer. Only the slow calls are async."""

    def cpu_percent(self) -> int:
        """CPU load, 0-100."""
        ...

    def ram_percent(self) -> int:
        """Memory in use, 0-100."""
        ...

    def lock_screen(self) -> None:
        """Lock the computer."""
        ...

    def start_spotify(self) -> None:
        """Start Spotify, or bring it up if it runs."""
        ...

    async def spotify_running(self) -> bool:
        """Whether Spotify is running."""
        ...

    async def control_spotify(self, key: MediaKey) -> None:
        """Do what the key says, to Spotify only. Raise SystemControlError if it does not work."""
        ...
