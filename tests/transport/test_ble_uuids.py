"""Tests for the characteristic UUIDs. The web page derives the same ones, so they are pinned."""

import uuid

import pytest

from phonedeck.transport.ble import notify_characteristic_uuid, write_characteristic_uuid

SERVICE_A = "7d2a0001-8c1e-4b6f-9a3d-5e1f0c2b4a10"
SERVICE_B = "11111111-2222-4333-8444-555555555555"


# --- The pinned values (the protocol). ---


@pytest.mark.parametrize(
    ("service", "write", "notify"),
    [
        (SERVICE_A, "716749bc-88a2-58d3-a999-fb7483ff6ff3", "37831094-ceff-5940-bdc6-b04c098bf841"),
        (SERVICE_B, "ce82801f-da76-579c-bf27-d2bc78fa0c6b", "f106132c-6a0b-5dad-9153-a6da4406c37f"),
    ],
)
def test_known_values(service: str, write: str, notify: str) -> None:
    assert write_characteristic_uuid(service) == write
    assert notify_characteristic_uuid(service) == notify


# --- The properties. ---


def test_the_same_service_always_gives_the_same_uuids() -> None:
    assert write_characteristic_uuid(SERVICE_A) == write_characteristic_uuid(SERVICE_A)
    assert notify_characteristic_uuid(SERVICE_A) == notify_characteristic_uuid(SERVICE_A)


def test_write_and_notify_are_different() -> None:
    assert write_characteristic_uuid(SERVICE_A) != notify_characteristic_uuid(SERVICE_A)


def test_different_services_give_different_uuids() -> None:
    assert write_characteristic_uuid(SERVICE_A) != write_characteristic_uuid(SERVICE_B)
    assert notify_characteristic_uuid(SERVICE_A) != notify_characteristic_uuid(SERVICE_B)


def test_the_result_is_a_lowercase_version_5_uuid() -> None:
    for value in (write_characteristic_uuid(SERVICE_A), notify_characteristic_uuid(SERVICE_A)):
        assert uuid.UUID(value).version == 5
        assert value == value.lower()


def test_capital_letters_in_the_service_uuid_make_no_difference() -> None:
    assert write_characteristic_uuid(SERVICE_A.upper()) == write_characteristic_uuid(SERVICE_A)
    assert notify_characteristic_uuid(SERVICE_A.upper()) == notify_characteristic_uuid(SERVICE_A)


@pytest.mark.parametrize("bad", ["", "not a uuid", "7d2a0001"])
def test_a_service_that_is_not_a_uuid_raises_value_error(bad: str) -> None:
    with pytest.raises(ValueError):
        write_characteristic_uuid(bad)
    with pytest.raises(ValueError):
        notify_characteristic_uuid(bad)
