"""Start PhoneDeck on the computer:  python -m phonedeck

Each phone gets a fresh one-time pairing key, shown as a QR code. Then it starts over for the next.
This file only puts the finished parts together, and is tried with a real phone, not with tests.
"""

import argparse
import asyncio
import logging
import sys
import webbrowser
from pathlib import Path

from phonedeck.core.channel import MessageChannel
from phonedeck.core.handler import Handler
from phonedeck.core.identity import load_or_create_service_uuid
from phonedeck.core.pairing import PAIRING_LIFETIME_SECONDS, Pairing
from phonedeck.core.pairing_page import render_pairing_page
from phonedeck.core.secure_channel import Role, SecureChannel
from phonedeck.core.session import pair_and_serve
from phonedeck.core.terminal_qr import render_terminal_qr
from phonedeck.platform.windows import WindowsSystemControl, enable_ansi_colors
from phonedeck.platform.winrt_peripheral import WinRtPeripheral
from phonedeck.transport.ble import BleTransport

log = logging.getLogger("phonedeck")

# Where the phone's web page is served: a static page on GitHub Pages, so no computer needs to
# host anything. For development, run the page on this computer (python -m http.server in web/)
# and use --web-url http://localhost:8000/ with `adb reverse tcp:8000 tcp:8000`.
DEFAULT_WEB_URL = "https://houbou98-19.github.io/phonedeck-web/"

PAIRING_PAGE = Path.home() / ".phonedeck" / "pairing.html"


def show_pairing(link: str, seconds: float) -> None:
    """Show the pairing link as a QR code in the terminal, and log it as text."""
    if sys.stdout.isatty():  # colour codes would only be noise in a file
        enable_ansi_colors()
        sys.stdout.write(render_terminal_qr(link) + "\n")
        sys.stdout.flush()
    log.info("Scan the code with the phone within %d seconds, or open: %s", seconds, link)


def write_pairing_page(link: str, seconds: float) -> None:
    """Write the pairing page that the browser shows and reloads."""
    PAIRING_PAGE.parent.mkdir(parents=True, exist_ok=True)
    temporary = PAIRING_PAGE.with_suffix(".tmp")
    temporary.write_text(render_pairing_page(link, seconds), encoding="utf-8")
    temporary.replace(PAIRING_PAGE)  # replaced in one go, so the browser never reads half a page


async def run(
    web_url: str,
    pairing_seconds: float = PAIRING_LIFETIME_SECONDS,
    open_browser: bool = False,
) -> None:
    """Pair and serve one phone at a time, for ever, until Ctrl+C."""
    service_uuid = load_or_create_service_uuid(Path.home() / ".phonedeck" / "service_uuid")
    handler = Handler(WindowsSystemControl())
    browser_opened = False

    try:
        while True:
            pairing = Pairing(lifetime=pairing_seconds)
            peripheral = WinRtPeripheral(service_uuid)
            transport = BleTransport(peripheral)
            channel = SecureChannel(MessageChannel(transport), Role.SERVER, pairing.take_key())
            try:
                try:
                    await peripheral.start()
                except RuntimeError as error:
                    log.error("Cannot start Bluetooth: %s", error)
                    return
                link = pairing.link(web_url, service_uuid)
                show_pairing(link, pairing.seconds_left)
                if open_browser:
                    write_pairing_page(link, pairing.seconds_left)
                    if not browser_opened:
                        webbrowser.open(PAIRING_PAGE.as_uri())  # a big QR code on screen
                        browser_opened = True
                await pair_and_serve(channel, pairing, handler)
            finally:
                await channel.close()  # this also stops advertising
            log.info("Ready for the next phone")
    finally:
        PAIRING_PAGE.unlink(missing_ok=True)  # an old code must not be left lying around


def main() -> None:
    """Set up logging, then run until Ctrl+C."""
    first_line = (__doc__ or "").split("\n")[0]
    parser = argparse.ArgumentParser(prog="phonedeck", description=first_line)
    parser.add_argument(
        "--web-url",
        default=DEFAULT_WEB_URL,
        help=f"where the phone's web page is served (default: {DEFAULT_WEB_URL})",
    )
    parser.add_argument(
        "--pairing-seconds",
        type=float,
        default=PAIRING_LIFETIME_SECONDS,
        help=f"how long a QR code is valid (default: {PAIRING_LIFETIME_SECONDS:.0f}; "
        "a longer time is only for trying things out)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="also show the QR code as a big page in the browser (it reloads by itself)",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(arguments.web_url, arguments.pairing_seconds, arguments.browser))
    except KeyboardInterrupt:
        log.info("Ctrl+C pressed, stopping")


if __name__ == "__main__":
    main()
