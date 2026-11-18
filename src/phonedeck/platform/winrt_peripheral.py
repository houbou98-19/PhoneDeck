"""BlePeripheral for Windows, built on WinRT (GattServiceProvider).

The only file that talks to the Windows Bluetooth stack. It needs a real adapter to be tried,
so it is kept small and the logic lives in phonedeck.transport.ble.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable

from winrt.windows.devices.bluetooth import BluetoothAdapter, BluetoothError
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattCharacteristicProperties,
    GattLocalCharacteristic,
    GattLocalCharacteristicParameters,
    GattServiceProvider,
    GattServiceProviderAdvertisingParameters,
    GattWriteOption,
    GattWriteRequestedEventArgs,
)
from winrt.windows.foundation import Deferral
from winrt.windows.storage.streams import DataWriter

from phonedeck.transport.ble import notify_characteristic_uuid, write_characteristic_uuid

log = logging.getLogger(__name__)


class WinRtPeripheral:
    """Advertises PhoneDeck's GATT service and moves bytes in and out of it."""

    def __init__(self, service_uuid: str) -> None:
        self._service_uuid = service_uuid
        self._write_handler: Callable[[bytes], None] = lambda _: None
        self._disconnect_handler: Callable[[], None] = lambda: None

        self._provider: GattServiceProvider | None = None

        self._write_characteristic: GattLocalCharacteristic | None = None
        self._notify_characteristic: GattLocalCharacteristic | None = None

        self._loop: asyncio.AbstractEventLoop | None = None

    def set_handlers(
        self, on_write: Callable[[bytes], None], on_disconnect: Callable[[], None]
    ) -> None:
        self._write_handler = on_write
        self._disconnect_handler = on_disconnect

    async def start(self) -> None:
        """Create the service and characteristics, then start advertising.

        Raise RuntimeError if Windows cannot, or if the adapter cannot be a peripheral.
        """
        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            raise RuntimeError("No Bluetooth adapter found")
        if not adapter.is_peripheral_role_supported:
            raise RuntimeError("Bluetooth adapter does not support peripheral role")
        created = await GattServiceProvider.create_async(uuid.UUID(self._service_uuid))
        if created.error != BluetoothError.SUCCESS:
            raise RuntimeError(f"Could not create GATT service: {created.error}")
        self._provider = created.service_provider

        self._write_characteristic = await self._create_characteristic(
            write_characteristic_uuid(self._service_uuid),
            GattCharacteristicProperties.WRITE
            | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE,
        )
        self._notify_characteristic = await self._create_characteristic(
            notify_characteristic_uuid(self._service_uuid), GattCharacteristicProperties.NOTIFY
        )

        self._loop = asyncio.get_running_loop()
        self._write_characteristic.add_write_requested(self._on_write_requested)
        self._notify_characteristic.add_subscribed_clients_changed(self._on_subscribers_changed)

        if self._provider is not None:
            adv = GattServiceProviderAdvertisingParameters()
            adv.is_connectable = True
            adv.is_discoverable = True
            self._provider.start_advertising(adv)

    async def _create_characteristic(
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
        if self._notify_characteristic is None:
            raise RuntimeError("Notify characteristic not initialized. Call start() first.")
        writer = DataWriter()
        writer.write_bytes(data)
        buffer = writer.detach_buffer()
        await self._notify_characteristic.notify_value_async(buffer)

    def _on_write_requested(
        self, sender: GattLocalCharacteristic, args: GattWriteRequestedEventArgs
    ) -> None:
        """Windows calls this on its own thread, so the work is handed to the event loop."""
        log.info("Write requested: %s", args)

        if self._loop is None:
            raise RuntimeError("Event loop not initialized. Call start() first.")
        deferral = args.get_deferral()
        asyncio.run_coroutine_threadsafe(self._handle_write_request(args, deferral), self._loop)

    def _on_subscribers_changed(self, sender: GattLocalCharacteristic, args: object) -> None:
        """No subscribers left means the phone is gone."""
        log.info("Subscribers changed: %s", args)
        if len(sender.subscribed_clients) == 0:
            if self._loop is None:
                raise RuntimeError("Event loop not initialized. Call start() first.")
            self._loop.call_soon_threadsafe(self._disconnect_handler)

    async def _handle_write_request(
        self, args: GattWriteRequestedEventArgs, deferral: Deferral
    ) -> None:
        try:
            request = await args.get_request_async()
            data = bytes(request.value)
            if request.option == GattWriteOption.WRITE_WITH_RESPONSE:
                log.info("Write with response received: %r", data)
                request.respond()

            self._write_handler(data)
        except Exception:
            log.exception("Error handling write request")
        finally:
            deferral.complete()
