"""Tests for WinRtPeripheral, only what works without an adapter.

Advertising, writes and notifications need real hardware (a phone, or nRF Connect).
"""

import sys

import pytest

from phonedeck.transport.ble import BlePeripheral

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows (WinRT)")


def make_peripheral() -> BlePeripheral:
    from phonedeck.platform.winrt_peripheral import WinRtPeripheral

    # mypy checks here that it fits the BlePeripheral interface
    return WinRtPeripheral("11111111-2222-4333-8444-555555555555")


def test_it_can_be_created_without_touching_bluetooth() -> None:
    make_peripheral()


def test_handlers_can_be_set_before_start() -> None:
    peripheral = make_peripheral()

    peripheral.set_handlers(lambda _data: None, lambda: None)


def test_stopping_before_starting_is_fine() -> None:
    import asyncio

    peripheral = make_peripheral()

    asyncio.run(asyncio.wait_for(peripheral.stop(), timeout=2))
