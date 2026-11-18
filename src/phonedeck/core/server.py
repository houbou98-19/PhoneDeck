"""The server loop: answer the phone's requests until the phone disconnects."""

import logging

from phonedeck.core.channel import Channel
from phonedeck.core.handler import Handler
from phonedeck.core.secure_channel import SecureChannelError
from phonedeck.protocol.frame import FrameError
from phonedeck.protocol.message import MessageError
from phonedeck.transport.base import TransportClosedError

log = logging.getLogger(__name__)


async def serve(channel: Channel, handler: Handler) -> None:
    """Answer requests one at a time, until the transport closes or a message is not trusted.

    Garbage and messages the phone may not send are logged and skipped, and get no answer.
    """
    while True:
        try:
            message = await channel.receive()
            response = await handler.handle(message)
            await channel.send(response)
        except (FrameError, MessageError) as e:
            log.warning("Ignoring bad message: %s", e)
        except SecureChannelError as e:
            log.warning("Ending the session, a message could not be trusted: %s", e)
            return
        except TransportClosedError:
            log.info("Transport closed, stopping server")
            return
