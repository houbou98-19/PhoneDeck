"""Tests for phonedeck.security.crypto.

The known values were made with a reference calculation using the `cryptography` library. They
are also the test vectors for the JavaScript version of the same functions (WebCrypto).
"""

import pytest

from phonedeck.security.crypto import (
    COUNTER_SIZE,
    KEY_SIZE,
    MAX_COUNTER,
    NONCE_SIZE,
    PAIRING_KEY_SIZE,
    SEAL_OVERHEAD,
    CryptoError,
    SessionKeys,
    derive_session_keys,
    new_nonce,
    new_pairing_key,
    open_sealed,
    seal,
)

PAIRING_KEY = bytes(range(0x00, 0x10))
CLIENT_NONCE = bytes(range(0x10, 0x20))
SERVER_NONCE = bytes(range(0x20, 0x30))

CLIENT_TO_SERVER = bytes.fromhex("7612f05f0aeb506af3460c89d22ffb40975cab985bab60012ef0a1dc9bf42fa7")
SERVER_TO_CLIENT = bytes.fromhex("a8006f446b6cd43aced41de33a99146d3863fb6279d2ec76f233dc2b9710ed93")


# --- Random values. ---


def test_a_pairing_key_has_the_right_size_and_is_random() -> None:
    first, second = new_pairing_key(), new_pairing_key()

    assert len(first) == PAIRING_KEY_SIZE
    assert first != second


def test_a_nonce_has_the_right_size_and_is_random() -> None:
    first, second = new_nonce(), new_nonce()

    assert len(first) == NONCE_SIZE
    assert first != second


# --- Key derivation. ---


def test_derive_session_keys_gives_the_known_values() -> None:
    keys = derive_session_keys(PAIRING_KEY, CLIENT_NONCE, SERVER_NONCE)

    assert keys == SessionKeys(CLIENT_TO_SERVER, SERVER_TO_CLIENT)


def test_the_two_directions_get_different_keys_of_the_right_size() -> None:
    keys = derive_session_keys(PAIRING_KEY, CLIENT_NONCE, SERVER_NONCE)

    assert keys.client_to_server != keys.server_to_client
    assert len(keys.client_to_server) == KEY_SIZE
    assert len(keys.server_to_client) == KEY_SIZE


def test_the_order_of_the_nonces_matters() -> None:
    swapped = derive_session_keys(PAIRING_KEY, SERVER_NONCE, CLIENT_NONCE)

    assert swapped != derive_session_keys(PAIRING_KEY, CLIENT_NONCE, SERVER_NONCE)


def test_another_nonce_or_pairing_key_gives_other_keys() -> None:
    original = derive_session_keys(PAIRING_KEY, CLIENT_NONCE, SERVER_NONCE)

    assert derive_session_keys(PAIRING_KEY, new_nonce(), SERVER_NONCE) != original
    assert derive_session_keys(PAIRING_KEY, CLIENT_NONCE, new_nonce()) != original
    assert derive_session_keys(new_pairing_key(), CLIENT_NONCE, SERVER_NONCE) != original


@pytest.mark.parametrize(
    ("pairing_key", "client_nonce", "server_nonce"),
    [
        (b"short", CLIENT_NONCE, SERVER_NONCE),
        (PAIRING_KEY + b"x", CLIENT_NONCE, SERVER_NONCE),
        (PAIRING_KEY, b"short", SERVER_NONCE),
        (PAIRING_KEY, CLIENT_NONCE, SERVER_NONCE + b"x"),
        (b"", b"", b""),
    ],
)
def test_derive_session_keys_rejects_wrong_sizes(
    pairing_key: bytes, client_nonce: bytes, server_nonce: bytes
) -> None:
    with pytest.raises(CryptoError):
        derive_session_keys(pairing_key, client_nonce, server_nonce)


# --- Sealing and opening. ---


def test_seal_gives_the_known_value() -> None:
    sealed = seal(CLIENT_TO_SERVER, 1, b"\x02\x00\x07", b"cpu")

    assert sealed.hex() == "00000000000000010b46daaa836606dc0565fe3c401b6f745a45fe"


def test_seal_of_nothing_with_no_aad_gives_the_known_value() -> None:
    assert (
        seal(SERVER_TO_CLIENT, 0, b"", b"").hex()
        == "0000000000000000bf30808957a8accfdc104103239b8b99"
    )


def test_a_sealed_message_is_longer_by_the_counter_and_the_tag() -> None:
    sealed = seal(CLIENT_TO_SERVER, 5, b"", b"hello")

    assert len(sealed) == len(b"hello") + SEAL_OVERHEAD
    assert SEAL_OVERHEAD == COUNTER_SIZE + 16


def test_the_counter_comes_first_in_the_clear() -> None:
    sealed = seal(CLIENT_TO_SERVER, 258, b"", b"x")

    assert sealed[:COUNTER_SIZE] == (258).to_bytes(8, "big")


def test_open_sealed_returns_the_counter_and_the_plaintext() -> None:
    sealed = seal(CLIENT_TO_SERVER, 42, b"aad", b"lock")

    assert open_sealed(CLIENT_TO_SERVER, b"aad", sealed) == (42, b"lock")


def test_open_sealed_reads_the_known_value() -> None:
    sealed = bytes.fromhex("00000000000000010b46daaa836606dc0565fe3c401b6f745a45fe")

    assert open_sealed(CLIENT_TO_SERVER, b"\x02\x00\x07", sealed) == (1, b"cpu")


def test_the_biggest_counter_works() -> None:
    sealed = seal(CLIENT_TO_SERVER, MAX_COUNTER, b"", b"x")

    assert open_sealed(CLIENT_TO_SERVER, b"", sealed)[0] == MAX_COUNTER


def test_the_same_message_with_another_counter_looks_different() -> None:
    assert seal(CLIENT_TO_SERVER, 1, b"", b"x") != seal(CLIENT_TO_SERVER, 2, b"", b"x")


# --- Anything that has been tampered with must be refused. ---


def test_a_changed_byte_in_the_ciphertext_is_refused() -> None:
    sealed = bytearray(seal(CLIENT_TO_SERVER, 1, b"", b"hello"))
    sealed[COUNTER_SIZE] ^= 0x01

    with pytest.raises(CryptoError):
        open_sealed(CLIENT_TO_SERVER, b"", bytes(sealed))


def test_a_changed_tag_is_refused() -> None:
    sealed = bytearray(seal(CLIENT_TO_SERVER, 1, b"", b"hello"))
    sealed[-1] ^= 0x01

    with pytest.raises(CryptoError):
        open_sealed(CLIENT_TO_SERVER, b"", bytes(sealed))


def test_a_changed_counter_is_refused() -> None:
    sealed = bytearray(seal(CLIENT_TO_SERVER, 1, b"", b"hello"))
    sealed[COUNTER_SIZE - 1] ^= 0x01  # counter 1 becomes 0

    with pytest.raises(CryptoError):
        open_sealed(CLIENT_TO_SERVER, b"", bytes(sealed))


def test_the_wrong_aad_is_refused() -> None:
    sealed = seal(CLIENT_TO_SERVER, 1, b"\x02\x00\x07", b"cpu")

    with pytest.raises(CryptoError):
        open_sealed(CLIENT_TO_SERVER, b"\x02\x00\x08", sealed)  # request id 7 changed to 8


def test_the_wrong_key_is_refused() -> None:
    sealed = seal(CLIENT_TO_SERVER, 1, b"", b"hello")

    with pytest.raises(CryptoError):
        open_sealed(SERVER_TO_CLIENT, b"", sealed)  # the other direction's key


@pytest.mark.parametrize("length", [0, 1, SEAL_OVERHEAD - 1])
def test_a_message_that_is_too_short_is_refused(length: int) -> None:
    with pytest.raises(CryptoError):
        open_sealed(CLIENT_TO_SERVER, b"", b"x" * length)


# --- Bad input to seal and open. ---


@pytest.mark.parametrize("key", [b"", b"short", bytes(KEY_SIZE + 1)])
def test_a_key_of_the_wrong_size_is_refused(key: bytes) -> None:
    with pytest.raises(CryptoError):
        seal(key, 1, b"", b"x")
    with pytest.raises(CryptoError):
        open_sealed(key, b"", bytes(SEAL_OVERHEAD))


@pytest.mark.parametrize("counter", [-1, MAX_COUNTER + 1])
def test_a_counter_out_of_range_is_refused(counter: int) -> None:
    with pytest.raises(CryptoError):
        seal(CLIENT_TO_SERVER, counter, b"", b"x")
