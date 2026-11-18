"""Tests for phonedeck.core.pairing. A fake clock moves time without waiting."""

import pytest

from phonedeck.core.pairing import (
    PAIRING_LIFETIME_SECONDS,
    Pairing,
    PairingError,
    parse_pairing_fragment,
)
from phonedeck.security.crypto import PAIRING_KEY_SIZE

SERVICE = "277cedef-a9df-4ddf-bfd3-ee550dd20035"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_the_default_lifetime_is_sixty_seconds() -> None:
    assert PAIRING_LIFETIME_SECONDS == 60.0


# --- The key and how long it lasts. ---


def test_a_pairing_hands_out_a_random_key_of_the_right_size() -> None:
    first, second = Pairing().take_key(), Pairing().take_key()

    assert len(first) == PAIRING_KEY_SIZE
    assert first != second


def test_a_new_pairing_has_all_of_its_time_left() -> None:
    pairing = Pairing(lifetime=60, clock=FakeClock())

    assert pairing.seconds_left == 60
    assert not pairing.expired


def test_the_time_left_goes_down_and_the_key_expires_after_the_lifetime() -> None:
    clock = FakeClock()
    pairing = Pairing(lifetime=60, clock=clock)

    clock.advance(59)
    assert pairing.seconds_left == pytest.approx(1)
    assert not pairing.expired

    clock.advance(1)
    assert pairing.seconds_left == 0
    assert pairing.expired


def test_the_time_left_is_never_negative() -> None:
    clock = FakeClock()
    pairing = Pairing(lifetime=60, clock=clock)

    clock.advance(10_000)

    assert pairing.seconds_left == 0


@pytest.mark.parametrize("lifetime", [0, -1])
def test_a_lifetime_of_zero_or_less_is_refused(lifetime: float) -> None:
    with pytest.raises(ValueError):
        Pairing(lifetime=lifetime)


# --- The key can be taken once, and only while it is valid. ---


def test_the_key_can_be_taken_only_once() -> None:
    pairing = Pairing(clock=FakeClock())
    pairing.take_key()

    with pytest.raises(PairingError):
        pairing.take_key()


def test_an_expired_key_cannot_be_taken() -> None:
    clock = FakeClock()
    pairing = Pairing(lifetime=60, clock=clock)

    clock.advance(60)

    with pytest.raises(PairingError):
        pairing.take_key()


def test_the_key_can_be_taken_right_up_to_the_end_of_its_time() -> None:
    clock = FakeClock()
    pairing = Pairing(lifetime=60, clock=clock)

    clock.advance(59.9)

    assert len(pairing.take_key()) == PAIRING_KEY_SIZE


# --- The link that the QR code holds. ---


def test_the_link_holds_the_service_uuid_and_the_key_in_the_fragment() -> None:
    pairing = Pairing()

    link = pairing.link("https://example.org/", SERVICE)

    assert link.startswith("https://example.org/#" + SERVICE + ".")


def test_the_link_gives_back_the_same_values_when_read() -> None:
    pairing = Pairing()
    link = pairing.link("https://example.org/", SERVICE)

    service, key = parse_pairing_fragment(link.split("#", 1)[1])

    assert service == SERVICE
    assert key == pairing.take_key()


def test_the_key_in_the_link_is_url_safe_and_has_no_padding() -> None:
    for _ in range(50):  # random keys, so try several
        key_text = Pairing().link("x", SERVICE).split(".")[-1]
        assert "=" not in key_text
        assert "+" not in key_text
        assert "/" not in key_text


# --- Reading a link that is not right. ---


@pytest.mark.parametrize(
    "fragment",
    [
        "",
        SERVICE,  # no key at all
        SERVICE + ".",  # an empty key
        "not-a-uuid.AAECAwQFBgcICQoLDA0ODw",
        SERVICE + ".AAECAwQFBgcICQoLDA0ODw" + "AA",  # a key that is too long
        SERVICE + ".AAEC",  # a key that is too short
        SERVICE + ".!!!!",  # not base64
    ],
)
def test_a_bad_fragment_is_refused(fragment: str) -> None:
    with pytest.raises(PairingError):
        parse_pairing_fragment(fragment)


def test_a_service_uuid_in_capitals_is_read_as_lowercase() -> None:
    link = Pairing().link("x", SERVICE.upper())

    service, _ = parse_pairing_fragment(link.split("#", 1)[1])

    assert service == SERVICE
