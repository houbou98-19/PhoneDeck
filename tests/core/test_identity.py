"""Tests for load_or_create_service_uuid. Each test uses its own tmp_path."""

import uuid
from pathlib import Path

import pytest

from phonedeck.core.identity import load_or_create_service_uuid


def test_the_first_call_makes_a_random_uuid(tmp_path: Path) -> None:
    value = load_or_create_service_uuid(tmp_path / "service_uuid")

    assert uuid.UUID(value).version == 4
    assert value == value.lower()


def test_the_uuid_is_saved_as_text(tmp_path: Path) -> None:
    path = tmp_path / "service_uuid"

    value = load_or_create_service_uuid(path)

    assert path.read_text().strip() == value


def test_later_calls_return_the_same_uuid(tmp_path: Path) -> None:
    path = tmp_path / "service_uuid"

    first = load_or_create_service_uuid(path)
    second = load_or_create_service_uuid(path)

    assert first == second


def test_missing_folders_are_made(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "service_uuid"

    value = load_or_create_service_uuid(path)

    assert path.read_text().strip() == value


def test_different_installations_get_different_uuids(tmp_path: Path) -> None:
    one = load_or_create_service_uuid(tmp_path / "one")
    two = load_or_create_service_uuid(tmp_path / "two")

    assert one != two


def test_an_existing_uuid_is_read_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "service_uuid"
    path.write_text("7d2a0001-8c1e-4b6f-9a3d-5e1f0c2b4a10\n")

    assert load_or_create_service_uuid(path) == "7d2a0001-8c1e-4b6f-9a3d-5e1f0c2b4a10"


def test_spaces_and_capitals_in_the_file_are_fine(tmp_path: Path) -> None:
    path = tmp_path / "service_uuid"
    path.write_text("  7D2A0001-8C1E-4B6F-9A3D-5E1F0C2B4A10  \n")

    assert load_or_create_service_uuid(path) == "7d2a0001-8c1e-4b6f-9a3d-5e1f0c2b4a10"


@pytest.mark.parametrize("content", ["", "   \n", "not a uuid", "7d2a0001"])
def test_a_bad_file_is_replaced_with_a_new_uuid(tmp_path: Path, content: str) -> None:
    path = tmp_path / "service_uuid"
    path.write_text(content)

    value = load_or_create_service_uuid(path)

    assert uuid.UUID(value).version == 4
    assert load_or_create_service_uuid(path) == value  # and now it stays
