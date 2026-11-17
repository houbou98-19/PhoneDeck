"""The interface between PhoneDeck and the computer it controls."""

from typing import Protocol


class SystemControlError(Exception):
    """Raised when the computer could not do what was asked (for example, locking failed)."""


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
