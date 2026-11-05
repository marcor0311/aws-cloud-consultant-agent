import asyncio
import base64
import json
import time
from types import SimpleNamespace

from hf_voice.audio import MicrophoneClient


class Socket:
    def __init__(self, events=()):
        self.sent, self.events = [], events

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def __aiter__(self):
        for event in self.events:
            yield json.dumps(event)


async def test_cancel_clears_audio_even_after_server_completed():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.ws = Socket()
    client.response_id = "completed"
    client.playback.append(b"\x01\x00" * 16000)
    await client.cancel()
    assert client.playback.buffered_bytes == 0
    assert client.ws.sent == []  # No invalid server cancellation after response.done.
    client.generating = True
    await client.cancel()
    assert client.ws.sent == [{"type": "response.cancel"}]


async def test_late_audio_from_cancelled_response_is_discarded():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.response_id = "old"
    await client.cancel()
    audio = base64.b64encode(b"\x01\x00" * 512).decode()
    client.ws = Socket(
        [
            {"type": "response.output_audio.delta", "response_id": "old", "delta": audio},
            {"type": "response.created", "response": {"id": "new"}},
            {"type": "response.output_audio.delta", "response_id": "new", "delta": audio},
        ]
    )
    await client.receive()
    assert client.playback.buffered_bytes == 1024


def test_speaker_block_includes_coreaudio_tail():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.playback.append(b"\x01\x00" * 512)
    client.playback.finish()
    output = bytearray(1024)
    client.output_callback(
        output, 512, SimpleNamespace(outputBufferDacTime=1.1, currentTime=1), None
    )
    assert client.suppress_until > time.monotonic() + 0.4
    client.input_callback(b"\x01\x00" * 512, 512, None, None)
    assert client.queue.empty()
    assert client.stats["suppressed_frames"] == 512


def test_voice_interruption_discards_old_response_events():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime", display=False)
    client.handle_event({"type": "response.created", "response": {"id": "old"}})
    client.handle_event({"type": "input_audio_buffer.speech_started"})
    client.handle_event({"type": "response.created", "response": {"id": "new"}})
    client.playback.append(b"\x01\x00" * 512)
    client.handle_event({"type": "response.done", "response": {"id": "old", "status": "cancelled"}})
    client.handle_event(
        {
            "type": "response.output_audio.delta",
            "response_id": "old",
            "delta": base64.b64encode(b"\x01\x00" * 512).decode(),
        }
    )
    assert client.generating
    assert client.playback.buffered_bytes == 1024


async def test_stale_microphone_samples_are_not_sent():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime")
    client.ws = Socket()
    client.queue.put((time.monotonic() - 5, b"old"))
    task = asyncio.create_task(client.send())
    await asyncio.sleep(0.15)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert client.ws.sent == []


def test_streaming_gap_does_not_reopen_speaker_microphone():
    client = MicrophoneClient("ws://127.0.0.1:1/v1/realtime", display=False)
    client.generating = True
    client.response_audio_started = True
    assert not client.playback.is_active()
    client.input_callback(b"\x01\x00" * 512, 512, None, None)
    assert client.queue.empty()
    client.blocked = False  # Headphones still allow voice interruption during generation.
    client.input_callback(b"\x01\x00" * 512, 512, None, None)
    assert not client.queue.empty()
