"""The cryptographic building blocks of the handshake. Pure functions, no I/O, no state.

How the pieces fit together (the design is in docs/decisions.md):

  * The computer makes a random PAIRING KEY and shows it in a QR code. The phone scans it. The
    key never travels over Bluetooth.
  * Each side makes a random NONCE and sends it in the clear in the handshake.
  * Both sides run derive_session_keys(pairing_key, client_nonce, server_nonce) and get the
    same two session keys, one for each direction.
  * Every later message is sealed with AES-GCM under the key of its direction. The message
    kind and request id are not hidden, but they are "additional authenticated data": if
    anyone changes them, opening the message fails.

Nothing here is invented. It only calls the vetted `cryptography` library (HKDF and AES-GCM),
and the phone's web page does the same with the browser's WebCrypto.
"""

import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PAIRING_KEY_SIZE = 16
NONCE_SIZE = 16  # bytes
KEY_SIZE = 32  # bytes: AES-256
COUNTER_SIZE = 8  # bytes: a message counter, sent in the clear in front of every sealed message
TAG_SIZE = 16  # bytes: the AES-GCM authentication tag
SEAL_OVERHEAD = COUNTER_SIZE + TAG_SIZE  # how much longer a sealed message is than its plaintext
MAX_COUNTER = 2**64 - 1

HKDF_INFO = b"phonedeck v1 session"


class CryptoError(Exception):
    """Raised for a bad key, a bad size, or a message that fails its authentication check."""


@dataclass(frozen=True)
class SessionKeys:
    """The two keys of one session. Each direction has its own, so a counter never repeats."""

    client_to_server: bytes  # the phone seals with this, the computer opens with it
    server_to_client: bytes  # the computer seals with this, the phone opens with it


def new_pairing_key() -> bytes:
    """A fresh random pairing key, PAIRING_KEY_SIZE bytes. Hint: secrets.token_bytes."""
    return secrets.token_bytes(PAIRING_KEY_SIZE)


def new_nonce() -> bytes:
    """A fresh random nonce, NONCE_SIZE bytes."""
    return secrets.token_bytes(NONCE_SIZE)


def derive_session_keys(
    pairing_key: bytes, client_nonce: bytes, server_nonce: bytes
) -> SessionKeys:
    """Turn the pairing key and the two nonces into the two session keys."""
    if len(pairing_key) != PAIRING_KEY_SIZE:
        raise CryptoError(f"Pairing key must be {PAIRING_KEY_SIZE} bytes, got {len(pairing_key)}")
    if len(client_nonce) != NONCE_SIZE:
        raise CryptoError(f"Client nonce must be {NONCE_SIZE} bytes, got {len(client_nonce)}")
    if len(server_nonce) != NONCE_SIZE:
        raise CryptoError(f"Server nonce must be {NONCE_SIZE} bytes, got {len(server_nonce)}")
    key_material = HKDF(
        algorithm=hashes.SHA256(),
        length=2 * KEY_SIZE,
        salt=client_nonce + server_nonce,
        info=HKDF_INFO,
    ).derive(pairing_key)

    return SessionKeys(
        client_to_server=key_material[:KEY_SIZE],
        server_to_client=key_material[KEY_SIZE:],
    )


def seal(key: bytes, counter: int, aad: bytes, plaintext: bytes) -> bytes:
    """Encrypt and authenticate one message."""
    if len(key) != KEY_SIZE:
        raise CryptoError(f"Key must be {KEY_SIZE} bytes, got {len(key)}")
    if not (0 <= counter <= MAX_COUNTER):
        raise CryptoError(f"Counter must be 0..{MAX_COUNTER}, got {counter}")
    aesgcm = AESGCM(key)
    nonce = counter.to_bytes(12, "big")
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    return counter.to_bytes(COUNTER_SIZE, "big") + ciphertext


def open_sealed(key: bytes, aad: bytes, sealed: bytes) -> tuple[int, bytes]:
    """Check and decrypt a message made by seal(). Return (counter, plaintext)."""
    if len(key) != KEY_SIZE:
        raise CryptoError(f"Key must be {KEY_SIZE} bytes, got {len(key)}")
    if len(sealed) < SEAL_OVERHEAD:
        raise CryptoError(
            f"Sealed message must be at least {SEAL_OVERHEAD} bytes, got {len(sealed)}"
        )
    counter_bytes = sealed[:COUNTER_SIZE]
    ciphertext = sealed[COUNTER_SIZE:]
    counter = int.from_bytes(counter_bytes, "big")
    nonce = counter.to_bytes(12, "big")
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
    except InvalidTag as e:
        raise CryptoError("Authentication check failed") from e
    return counter, plaintext
