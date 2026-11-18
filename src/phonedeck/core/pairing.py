"""Pairing: the one-time key that the QR code carries, valid for a short time and handed out once.

The key and the service UUID sit in the link's fragment (after the #), which a browser never
sends to a server.
"""

import base64
import binascii
import time
import uuid
from collections.abc import Callable

from phonedeck.security.crypto import PAIRING_KEY_SIZE, new_pairing_key

PAIRING_LIFETIME_SECONDS = 60.0


class PairingError(Exception):
    """Raised when the pairing key cannot be used (expired, already used) or a link is bad."""


class Pairing:
    """One pairing offer. Make a new one for every phone that is to connect."""

    def __init__(
        self,
        lifetime: float = PAIRING_LIFETIME_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if lifetime <= 0:
            raise ValueError(f"The lifetime must be above 0 seconds, got {lifetime}")
        self._key = new_pairing_key()
        self._clock = clock
        self._expires_at = clock() + lifetime
        self._taken = False

    @property
    def seconds_left(self) -> float:
        """How long the key is still valid. Never below 0."""
        return max(0.0, self._expires_at - self._clock())

    @property
    def expired(self) -> bool:
        return self.seconds_left == 0.0

    def take_key(self) -> bytes:
        """Hand out the key, once. Raise PairingError if it has expired or was already taken."""
        if self._taken:
            raise PairingError("The pairing key has already been used")
        if self.expired:
            raise PairingError("The pairing key has expired")
        self._taken = True
        return self._key

    def link(self, base_url: str, service_uuid: str) -> str:
        """The address in the QR code: base_url#service_uuid.key (the key in URL-safe base64)."""
        key_text = base64.urlsafe_b64encode(self._key).rstrip(b"=").decode("ascii")
        return f"{base_url}#{service_uuid}.{key_text}"


def parse_pairing_fragment(fragment: str) -> tuple[str, bytes]:
    """Read the part after the # of a link from Pairing.link(): (service UUID, key)."""
    service_text, dot, key_text = fragment.partition(".")
    if not dot:
        raise PairingError("The link has no key (a service UUID, a dot and a key are expected)")
    try:
        service_uuid = str(uuid.UUID(service_text))
    except ValueError as error:
        raise PairingError(f"Not a service UUID: {service_text!r}") from error
    try:
        padded = key_text + "=" * (-len(key_text) % 4)
        key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as error:
        raise PairingError("The key in the link is not valid base64") from error
    if len(key) != PAIRING_KEY_SIZE:
        raise PairingError(f"The key must be {PAIRING_KEY_SIZE} bytes, got {len(key)}")
    return service_uuid, key
