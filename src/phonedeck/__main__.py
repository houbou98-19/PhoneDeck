"""Start PhoneDeck on the computer:  python -m phonedeck

For every phone: a fresh one-time pairing key is made and shown as a QR code (and as text), the
computer advertises over Bluetooth, and a phone that scans the code and proves it has the key
is served. Everything else is refused. Then it starts over, ready for the next phone.

This file only puts the finished parts together. It is tried with a real phone, not with tests.
"""

import argparse
import asyncio
import logging
from pathlib import Path

import segno

from phonedeck.core.channel import MessageChannel
from phonedeck.core.handler import Handler
from phonedeck.core.identity import load_or_create_service_uuid
from phonedeck.core.pairing import Pairing
from phonedeck.core.secure_channel import Role, SecureChannel
from phonedeck.core.session import pair_and_serve
from phonedeck.platform.windows import WindowsSystemControl
from phonedeck.platform.winrt_peripheral import WinRtPeripheral
from phonedeck.transport.ble import BleTransport

log = logging.getLogger("phonedeck")

# Where the phone's web page is served. For development: the page runs on this computer and is
# forwarded to the phone with `adb reverse tcp:8000 tcp:8000`.
DEFAULT_WEB_URL = "http://localhost:8000/"


def show_pairing(link: str, seconds: float) -> None:
    """Show the pairing link as a QR code in the terminal, and as text."""
    segno.make(link, error="l").terminal(compact=True)
    log.info("Scan the code with the phone within %d seconds, or open: %s", seconds, link)


async def run(web_url: str) -> None:
    """Pair and serve one phone at a time, for ever, until Ctrl+C."""
    service_uuid = load_or_create_service_uuid(Path.home() / ".phonedeck" / "service_uuid")
    handler = Handler(WindowsSystemControl())

    while True:
        pairing = Pairing()
        peripheral = WinRtPeripheral(service_uuid)
        transport = BleTransport(peripheral)
        channel = SecureChannel(MessageChannel(transport), Role.SERVER, pairing.take_key())
        try:
            try:
                await peripheral.start()
            except RuntimeError as error:
                log.error("Cannot start Bluetooth: %s", error)
                return
            show_pairing(pairing.link(web_url, service_uuid), pairing.seconds_left)
            await pair_and_serve(channel, pairing, handler)
        finally:
            await channel.close()  # this also stops advertising
        log.info("Ready for the next phone")


def main() -> None:
    """Set up logging, then run until Ctrl+C."""
    first_line = (__doc__ or "").split("\n")[0]
    parser = argparse.ArgumentParser(prog="phonedeck", description=first_line)
    parser.add_argument(
        "--web-url",
        default=DEFAULT_WEB_URL,
        help=f"where the phone's web page is served (default: {DEFAULT_WEB_URL})",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(arguments.web_url))
    except KeyboardInterrupt:
        log.info("Ctrl+C pressed, stopping")


if __name__ == "__main__":
    main()
