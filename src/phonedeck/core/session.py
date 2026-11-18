"""One session: wait for a phone to prove it has the pairing key, then serve it."""

import asyncio
import logging

from phonedeck.core.handler import Handler
from phonedeck.core.pairing import Pairing
from phonedeck.core.secure_channel import HandshakeError, SecureChannel
from phonedeck.core.server import serve
from phonedeck.transport.base import TransportClosedError

log = logging.getLogger(__name__)


async def pair_and_serve(channel: SecureChannel, pairing: Pairing, handler: Handler) -> bool:
    """Wait for a phone to pair, then answer its requests until it disconnects.

    The phone has as much time as the pairing has left (60 seconds from when it was made) to
    connect AND finish the handshake. If the time runs out, the handshake fails, or the phone
    leaves, the channel is closed and the answer is False: nobody was served. The caller makes
    a new Pairing (a new key) for the next try.

    If the phone paired, it is served until it disconnects, and the answer is True.
    """
    try:
        async with asyncio.timeout(pairing.seconds_left):
            await channel.handshake()
    except TimeoutError:
        log.info("The pairing time ran out, and no phone paired")
        await channel.close()
        return False
    except HandshakeError as error:  # the channel has already been closed
        log.warning("Pairing failed: %s", error)
        return False
    except TransportClosedError:
        log.info("The phone left before pairing was done")
        return False

    log.info("A phone is paired")
    await serve(channel, handler)
    return True
