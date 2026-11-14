"""SIP REFER for the sole SIP caller in the active LiveKit job; no new calls."""

import asyncio
import logging

from aiohttp import ClientError
from google.protobuf.duration_pb2 import Duration
from livekit import api, rtc
from livekit.agents import get_job_context

from src.config import advisor_transfer_settings

logger = logging.getLogger(__name__)


async def transfer_active_call() -> str:
    try:
        destination, ringing_timeout = advisor_transfer_settings()
    except ValueError:
        return "unavailable"

    # A browser/console session cannot be transferred. Never guess among callers.
    job = get_job_context()
    callers = [
        participant
        for participant in job.room.remote_participants.values()
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    ]
    if len(callers) != 1:
        return "unavailable"

    try:
        response = await asyncio.wait_for(
            job.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job.room.name,
                    participant_identity=callers[0].identity,
                    transfer_to=f"tel:{destination}",
                    play_dialtone=True,
                    ringing_timeout=Duration(seconds=ringing_timeout),
                ),
                # Let the server finish its ring window before the HTTP deadline.
                timeout=ringing_timeout + 5,
            ),
            timeout=ringing_timeout + 10,
        )
    except api.ServerError as error:
        reason = error.metadata.get("sip_transfer_reason")
        if reason in {"STR_RINGING_TIMEOUT", str(api.STR_RINGING_TIMEOUT)} or (
            error.status == 408 and not reason
        ):
            return "no_answer"
        if reason in {"STR_REJECTED", str(api.STR_REJECTED)}:
            return "rejected"
        # Do not log raw provider messages, SIP headers, identities or numbers.
        logger.warning("La transferencia SIP no se completó.")
        return "failed"
    except (ClientError, TimeoutError, OSError, ValueError):
        # The remote outcome can be uncertain: never automatically retry REFER.
        return "failed"

    if response.status == api.STS_TRANSFER_SUCCESSFUL:
        return "transferred"
    if response.reason == api.STR_RINGING_TIMEOUT:
        return "no_answer"
    if response.reason == api.STR_REJECTED:
        return "rejected"
    return "failed"
