"""Start PhoneDeck on the computer:  python -m phonedeck

This file only puts the finished parts together. It is tried with a real phone, not with tests.
"""

import asyncio
import logging
from pathlib import Path

from phonedeck.core.channel import MessageChannel
from phonedeck.core.handler import Handler
from phonedeck.core.identity import load_or_create_service_uuid
from phonedeck.core.server import serve
from phonedeck.platform.windows import WindowsSystemControl
from phonedeck.platform.winrt_peripheral import WinRtPeripheral
from phonedeck.transport.ble import BleTransport

log = logging.getLogger("phonedeck")

home = Path.home()


async def run() -> None:
    """Advertise, serve one phone until it disconnects, then do it again, until Ctrl+C."""
    while True:
        service_uuid = load_or_create_service_uuid(home / ".phonedeck" / "service_uuid")
        peripheral = WinRtPeripheral(service_uuid)
        transport = BleTransport(peripheral)
        channel = MessageChannel(transport)
        handler = Handler(WindowsSystemControl())

        await peripheral.start()
        log.info(
            "PhoneDeck is advertising service %s. Open the phone's web page to connect.",
            service_uuid,
        )
        try:
            await serve(channel, handler)
        finally:
            await channel.close()
            log.info("Phone disconnected, advertising stopped")


def main() -> None:
    """Set up logging, then run until Ctrl+C."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Ctrl+C pressed, stopping")


if __name__ == "__main__":
    main()
