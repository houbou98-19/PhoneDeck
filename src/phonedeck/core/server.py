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
    """Answer requests from the phone, one at a time, until the session ends.

    For every message that arrives: let the handler answer it, and send the answer back.
    The channel is normally a SecureChannel, so only authentic messages get this far.

    What must NOT stop the server (log it as a warning and carry on with the next message):
      * garbage bytes (FrameError) and unknown message kinds (MessageError) from the phone;
      * a message the phone may not send, like a RESPONSE (the handler raises MessageError).
        No answer is sent for those.

    The server ends, by returning normally, when
      * the transport closes (TransportClosedError), whether while receiving or while sending;
      * a message cannot be trusted (SecureChannelError). The secure channel has then already
        closed the connection, and nothing was handled.
    Other errors are not hidden.
    """
    while True:
        try:
            message = await channel.receive()
            response = handler.handle(message)
            await channel.send(response)
        except (FrameError, MessageError) as e:
            log.warning("Ignoring bad message: %s", e)
        except SecureChannelError as e:
            log.warning("Ending the session, a message could not be trusted: %s", e)
            return
        except TransportClosedError:
            log.info("Transport closed, stopping server")
            return
