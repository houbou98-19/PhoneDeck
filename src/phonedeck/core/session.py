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
    """Wait for a phone to pair within the time the pairing has left, then serve it.

    Return whether a phone was served. After a failed try the caller makes a new Pairing.
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
