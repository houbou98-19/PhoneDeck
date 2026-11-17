"""BlePeripheral for Windows, built on WinRT (GattServiceProvider).

This is the only file that talks to the Windows Bluetooth stack. It can only be tried with a
real adapter, so it is kept small, and the logic lives in phonedeck.transport.ble instead.
"""

import uuid
from collections.abc import Callable

from winrt.windows.devices.bluetooth import BluetoothAdapter, BluetoothError
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattCharacteristicProperties,
    GattLocalCharacteristic,
    GattLocalCharacteristicParameters,
    GattServiceProvider,
    GattServiceProviderAdvertisingParameters,
)

from phonedeck.transport.ble import notify_characteristic_uuid, write_characteristic_uuid


class WinRtPeripheral:
    """Advertises PhoneDeck's GATT service and moves bytes in and out of it.

    The four steps (the spike in spikes/ble_peripheral.py does steps 1, 2 and 4):
      1. Create the service, with service_uuid (different for every installation, so that PCs
         running PhoneDeck cannot be told apart by their advertisement, see core/identity.py).
      2. Add two characteristics:
           WRITE_CHARACTERISTIC_UUID   properties WRITE (and WRITE_WITHOUT_RESPONSE)
           NOTIFY_CHARACTERISTIC_UUID  properties NOTIFY
      3. When the phone writes, read the bytes out of the request and give them to on_write.
         When the phone has no subscribers left, call on_disconnect.
      4. notify() sends the bytes to everyone subscribed to the notify characteristic.

    Thread rule: WinRT calls your event handlers from another thread, but BlePeripheral says the
    handlers must run on the asyncio loop's thread. So do not call on_write directly from
    the WinRT handler. Hand it over with loop.call_soon_threadsafe(...).

    Constructing the object must not touch Bluetooth. Only start() does.

    TODO(you): decide what to remember (the loop, the handlers, the provider and the two
    characteristics). Think about where you get the loop from.
    """

    def __init__(self, service_uuid: str) -> None:
        """Initialize the object, but do not touch Bluetooth yet. The service_uuid is a string"""
        self._service_uuid = service_uuid
        self._write_handler: Callable[[bytes], None] = lambda _: None
        self._disconnect_handler: Callable[[], None] = lambda: None

        self._provider: GattServiceProvider | None = None

        self._write_characteristic: GattLocalCharacteristic | None = None
        self._notify_characteristic: GattLocalCharacteristic | None = None

    def set_handlers(
        self, on_write: Callable[[bytes], None], on_disconnect: Callable[[], None]
    ) -> None:
        """Say what to call when the phone writes a packet, and when the phone disconnects."""
        self._write_handler = on_write
        self._disconnect_handler = on_disconnect

    async def start(self) -> None:
        """Create the service and characteristics, then start advertising.

        Raise RuntimeError with a clear message if Windows cannot create the service, or if
        the adapter does not support the peripheral role.
        """
        service_uuid = uuid.UUID(self._service_uuid)
        created = await GattServiceProvider.create_async(service_uuid)
        if created.error != BluetoothError.SUCCESS:
            raise RuntimeError(f"Could not create GATT service: {created.error}")
        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            raise RuntimeError("No Bluetooth adapter found")
        if not adapter.is_peripheral_role_supported:
            raise RuntimeError("Bluetooth adapter does not support peripheral role")
        self._provider = created.service_provider

        self._write_characteristic = await self.create_characteristic(
            write_characteristic_uuid(self._service_uuid), GattCharacteristicProperties.WRITE
        )
        self._notify_characteristic = await self.create_characteristic(
            notify_characteristic_uuid(self._service_uuid), GattCharacteristicProperties.NOTIFY
        )
        if self._provider is not None:
            adv = GattServiceProviderAdvertisingParameters()
            adv.is_connectable = True
            adv.is_discoverable = True
            self._provider.start_advertising(adv)

    async def create_characteristic(
        self, characteristic_uuid: str, properties: GattCharacteristicProperties
    ) -> GattLocalCharacteristic:
        """Create a characteristic with the given UUID and properties."""
        if self._provider is None:
            raise RuntimeError("Service provider not initialized. Call start() first.")
        params = GattLocalCharacteristicParameters()
        params.characteristic_properties = properties
        char_result = await self._provider.service.create_characteristic_async(
            uuid.UUID(characteristic_uuid), params
        )
        if char_result.error != BluetoothError.SUCCESS:
            raise RuntimeError(f"Could not create characteristic: {char_result.error}")
        return char_result.characteristic

    async def stop(self) -> None:
        """Stop advertising. Stopping twice, or before start(), is fine."""
        if self._provider is not None:
            self._provider.stop_advertising()
            self._provider = None

    async def notify(self, data: bytes) -> None:
        """Send one notification to the connected phone."""
        raise NotImplementedError

    def _on_write(self, data: bytes) -> None:
        """Windows says the phone wrote: call _write_handler, on the asyncio loop's thread."""
        raise NotImplementedError

    def _on_disconnect(self) -> None:
        """Windows says the phone left: call _disconnect_handler, on the asyncio loop's thread."""
        raise NotImplementedError
